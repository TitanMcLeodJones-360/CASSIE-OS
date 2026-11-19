#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID != 0 ]]; then echo 'Run: sudo bash update-desktop.sh'; exit 1; fi
test -f /opt/cassie-os/app/server.py || { echo 'Install CASSIE OS first.'; exit 1; }
if [[ $# -eq 1 && $1 == --app-only ]]; then
    exec bash update-camera.sh --app-only
fi
if [[ $# -ne 0 ]]; then
    echo 'Usage: sudo bash update-desktop.sh [--app-only]'
    exit 2
fi
voice_ready=1
bash install-speech.sh || voice_ready=0
if command -v snap >/dev/null && snap connections chromium 2>/dev/null |
    awk '$2 == "chromium:audio-record" && $3 == "-" {missing=1} END {exit !missing}'; then
    snap connect chromium:audio-record || echo 'Chromium microphone access still needs to be connected.'
fi
bash update-camera.sh
systemctl start cassie-os-model.service
echo 'Testing a local reply. The first generation can take a minute.'
if PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import sys
sys.path.insert(0, "/opt/cassie-os/app")
import server

try:
    names = server.installed_models()
    model = server.MODEL if server.MODEL in names else server.fallback_model()
    if not model:
        raise server.ModelError("No installed CASSIE or Qwen model was found.")
    reply = server.chat_result({
        "model": model, "stream": False, "think": False, "keep_alive": "5m",
        "options": {"num_ctx": 4096, "num_predict": 32},
        "messages": [{"role": "user", "content": "Reply with the single word ready."}],
    }, lambda part: None)
    if not reply.get("done") or not reply.get("message", {}).get("content", "").strip():
        raise server.ModelError("Ollama sent an empty or incomplete test reply.")
except server.ModelError as error:
    raise SystemExit(str(error)) from None
print(f"Local generation test passed ({model}).")
PY
then
    model_ready=1
else
    model_ready=0
    echo 'Check model logs with: sudo journalctl -u cassie-os-model -n 45 --no-pager'
fi
if [[ $voice_ready == 0 ]]; then echo 'Offline speech setup failed. Re-run this update to retry the speech installation.'; fi
echo 'Desktop app updated. Sign out and back into CASSIE OS to load the new dashboard.'
[[ $voice_ready == 1 && $model_ready == 1 ]]
