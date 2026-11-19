#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID != 0 ]]; then echo 'Run: sudo bash update-camera.sh'; exit 1; fi
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --app-only ) ]]; then
    echo 'Usage: sudo bash update-camera.sh [--app-only]'
    exit 2
fi
root=/opt/cassie-os
test -f "$root/app/server.py" || { echo 'Install CASSIE OS first.'; exit 1; }
exec 9>/run/lock/cassie-os-install.lock
flock -n 9 || { echo 'CASSIE OS setup is already running.'; exit 1; }

if [[ $# -eq 0 ]]; then bash install-vision.sh --no-restart; fi
for file in server.py command_center.py observer.py speech.py network_activity.py base_persona.txt integrity.json dataset_search.py dataset_catalog.json LICENSE-Awesome-Public-Datasets.txt; do
    install -m 0644 "app/$file" "$root/app/$file"
done
for file in index.html style.css app.js mic-worklet.js; do
    install -m 0644 "app/static/$file" "$root/app/static/$file"
done
install -m 0644 systemd/cassie-os.service /etc/systemd/system/
install -m 0644 systemd/cassie-os-network.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart cassie-os.service
systemctl enable cassie-os-network.service
systemctl restart cassie-os-network.service
for attempt in {1..12}; do
    if curl --disable --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
        if [[ $# -eq 0 ]]; then
            echo 'Camera update installed. Reopen CASSIE and select Awareness → Turn on always-on camera.'
        else
            echo 'Application updated. Sign out and back into CASSIE OS.'
        fi
        exit 0
    fi
    sleep 1
done
echo 'The CASSIE console did not start. Check: sudo journalctl -u cassie-os -n 40 --no-pager'
exit 1
