#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID != 0 ]]; then echo 'Run: sudo bash install.sh'; exit 1; fi
if [[ "$(uname -m)" != x86_64 ]]; then echo 'This edition needs the x86-64 TitanGame PC.'; exit 1; fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 ]]; then echo 'This build targets Ubuntu 24.04 LTS (Desktop or Server).'; exit 1; fi
case "${1:-4b}" in
    4b) base=qwen3.5:4b ;;
    2b) base=qwen3.5:2b ;;
    *) echo 'Use sudo bash install.sh or sudo bash install.sh 2b'; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then echo 'Only one model size may be specified.'; exit 2; fi
exec 9>/run/lock/cassie-os-install.lock
flock -n 9 || { echo 'CASSIE OS installation is already running.'; exit 1; }
root=/opt/cassie-os
runtime=$root/ollama-0.40.4
profile=cassie:desktop
available=$(df -PB1 /opt | awk 'NR==2 {print $4}')
if (( available < 15000000000 )); then echo 'Free at least 15 GB on the Ubuntu disk for setup.'; exit 1; fi
tmp=
cleanup(){ if [[ -n "${tmp:-}" ]]; then rm -rf -- "$tmp"; fi; }
trap cleanup EXIT
echo '[1/5] Install Ubuntu dependencies.'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl zstd python3 python3-pil iproute2 espeak-ng

echo '[2/5] Install the local Ollama runtime.'
if [[ ! -x "$runtime/bin/ollama" ]]; then
    install -d -m 0755 "$root"
    if [[ -e "$runtime" ]]; then echo "Unexpected existing runtime at $runtime"; exit 1; fi
    tmp=$(mktemp -d "$root/.runtime.XXXXXXXX")
    curl --disable --proto '=https' --proto-redir '=https' --fail --location --retry 2 \
        --connect-timeout 15 --max-time 3600 \
        -o "$tmp/runtime.tar.zst" https://github.com/ollama/ollama/releases/download/v0.40.4/ollama-linux-amd64.tar.zst
    printf '%s  %s\n' 15f31e9576d15a481e099b4145dba6e9f8c1f295927d6b8895300ae30ed3740a "$tmp/runtime.tar.zst" | sha256sum -c -
    mkdir -m 0755 "$tmp/extracted"
    tar --zstd -xf "$tmp/runtime.tar.zst" --no-same-owner -C "$tmp/extracted"
    test -x "$tmp/extracted/bin/ollama"
    mv -- "$tmp/extracted" "$runtime"
    cleanup
    tmp=
fi

echo '[3/5] Configure local model and console services.'
for user in cassie-model cassie-os; do
    if ! id "$user" >/dev/null 2>&1; then useradd --system --user-group --no-create-home --home-dir "/var/lib/$user" --shell /usr/sbin/nologin "$user"; fi
done
for group in video render; do
    if getent group "$group" >/dev/null; then usermod -aG "$group" cassie-model; fi
done
install -d -m 0755 "$root/app/static"
for file in server.py command_center.py observer.py speech.py network_activity.py integrity.json dataset_search.py dataset_catalog.json LICENSE-Awesome-Public-Datasets.txt base_persona.txt; do
    install -m 0644 "app/$file" "$root/app/$file"
done
for file in index.html style.css app.js insignia.webp mic-worklet.js; do
    install -m 0644 "app/static/$file" "$root/app/static/$file"
done
install -m 0644 systemd/cassie-os.service systemd/cassie-os-model.service systemd/cassie-os-network.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart cassie-os-model.service
for attempt in {1..35}; do
    if curl --disable --noproxy '*' -fsS --max-time 2 http://127.0.0.1:11438/api/tags >/dev/null 2>&1; then break; fi
    sleep 1
done
systemctl is-active --quiet cassie-os-model.service
curl --disable --noproxy '*' -fsS --max-time 5 http://127.0.0.1:11438/api/tags >/dev/null

echo "[4/5] Prepare $base and create the local CASSIE profile."
ollama(){ OLLAMA_HOST=127.0.0.1:11438 NO_PROXY=127.0.0.1 no_proxy=127.0.0.1 "$runtime/bin/ollama" "$@"; }
models=$(ollama list)
if awk -v model="$base" 'NR > 1 && $1 == model { found = 1 } END { exit !found }' <<<"$models"; then
    echo "Using the installed $base model."
else
    ollama pull "$base"
fi
tmp=$(mktemp -d "$root/.model.XXXXXXXX")
# The client sends the local Modelfile to the loopback model service.
{
    printf 'FROM %s\nPARAMETER num_ctx 4096\nPARAMETER temperature 0.65\nSYSTEM """\n' "$base"
    cat "$root/app/base_persona.txt"
    printf '"""\n'
} >"$tmp/Modelfile"
ollama create "$profile" -f "$tmp/Modelfile"
cleanup
tmp=
echo '[5/5] Verify local generation and start CASSIE.'
python3 - "$profile" <<'PY'
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener
profile = sys.argv[1]
model={"model":profile,"messages":[{"role":"user","content":"Reply with the word ready."}],
       "stream":False,"think":False,"keep_alive":"1m","options":{"num_ctx":4096,"num_predict":32}}
req=Request("http://127.0.0.1:11438/api/chat",json.dumps(model).encode(),{"Content-Type":"application/json"})
try:
    with build_opener(ProxyHandler({})).open(req, timeout=240) as response:
        result = json.load(response)
except HTTPError as exc:
    detail = exc.read(4096).decode("utf-8", errors="replace").strip()
    raise SystemExit(f"Ollama could not run {profile} (HTTP {exc.code}): {detail}") from None
except (URLError, OSError, ValueError) as exc:
    raise SystemExit(f"Could not verify {profile} with Ollama: {exc}") from None
if not result.get("done") or not result.get("message",{}).get("content","").strip():
    raise SystemExit("CASSIE model generation test did not pass.")
print("Local generation test passed.")
PY
systemctl restart cassie-os.service
for attempt in {1..12}; do
    if curl --disable --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8787/api/health >/dev/null 2>&1; then break; fi
    sleep 1
done
systemctl is-active --quiet cassie-os.service
curl --disable --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8787/api/health >/dev/null
systemctl enable cassie-os-model.service cassie-os.service cassie-os-network.service
systemctl restart cassie-os-network.service
if ! nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null; then
    echo 'NVIDIA status unavailable. CASSIE passed the model test, but may be running on CPU. See README.md for driver setup.'
fi
echo
if [[ ${CASSIE_INSTALL_DESKTOP:-} == 1 ]]; then
    echo 'CASSIE assistant is ready. Registering the desktop session next.'
else
    echo 'CASSIE OS is ready: http://127.0.0.1:8787'
    echo 'From another computer, use the SSH tunnel in the README.'
fi
echo 'Enter the access key shown below. Keep it private.'
cat /var/lib/cassie-os/access.token
