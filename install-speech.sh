#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if [[ $EUID != 0 ]]; then echo 'Run: sudo bash install-speech.sh'; exit 1; fi
root=/opt/cassie-os/speech
model=vosk-model-small-en-us-0.15
exec 9>/run/lock/cassie-os-speech-install.lock
flock -n 9 || { echo 'Speech setup is already running.'; exit 1; }
if [[ -f "$root/$model/am/final.mdl" && -x "$root/runtime/bin/python3" ]] &&
    "$root/runtime/bin/python3" -c 'import vosk' >/dev/null 2>&1; then
    echo 'Using the installed offline speech recognizer.'
    exit 0
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-venv unzip ca-certificates curl
install -d -m 0755 "$root"
tmp=$(mktemp -d "$root/.setup.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
curl --disable --proto '=https' --proto-redir '=https' --fail --location --retry 2 \
    --connect-timeout 15 --max-time 300 -o "$tmp/model.zip" "https://alphacephei.com/vosk/models/$model.zip"
printf '%s  %s\n' 30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498 "$tmp/model.zip" | sha256sum -c -
unzip -q "$tmp/model.zip" -d "$tmp"
/usr/bin/python3 -m venv "$tmp/runtime"
"$tmp/runtime/bin/python3" -m pip --isolated install --no-input --disable-pip-version-check \
    --index-url https://pypi.org/simple 'vosk==0.3.45'
"$tmp/runtime/bin/python3" - "$tmp/$model" <<'PY'
import sys
from vosk import KaldiRecognizer, Model, SetLogLevel
SetLogLevel(-1)
KaldiRecognizer(Model(sys.argv[1]), 16000)
PY
chmod -R a+rX "$tmp/runtime" "$tmp/$model"
for asset in runtime "$model"; do
    if [[ -e "$root/$asset" ]]; then mv -T -- "$root/$asset" "$tmp/old-$asset"; fi
    if ! mv -T -- "$tmp/$asset" "$root/$asset"; then
        if [[ -e "$tmp/old-$asset" ]]; then mv -T -- "$tmp/old-$asset" "$root/$asset"; fi
        exit 1
    fi
done
echo 'Offline speech recognizer ready.'
