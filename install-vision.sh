#!/usr/bin/env bash
# Optional local vision model. Does not enable the camera or alter network settings.
set -euo pipefail
if [[ $EUID != 0 ]]; then echo 'Run: sudo bash install-vision.sh'; exit 1; fi
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --no-restart ) ]]; then
    echo 'Run: sudo bash install-vision.sh'
    exit 2
fi
test -f /opt/cassie-os/app/command_center.py || { echo 'Install CASSIE OS first.'; exit 1; }
verify_weights() {
    cd -- "$1" || return 1
    sha256sum -c <<'HASHES'
2d180f723b3109e21f8287f6b3c691390d07b60eed998327cd3259ffa0e50608  deploy.prototxt
52eed8be80522c152a17fb56740de705b79881bde1a167e0e747310523685fc7  model.caffemodel
HASHES
}
if [[ ${1:-} == --no-restart ]] &&
   (verify_weights /opt/cassie-os/vision) >/dev/null 2>&1 &&
   /usr/bin/python3 -c 'import cv2' >/dev/null 2>&1; then
    echo 'Using the installed local detector.'
    exit 0
fi
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
base=https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/bb17b6c3eef36d80be441ae8e5339be66e8e3b7a
fetch(){ curl --disable --proto '=https' --proto-redir '=https' --location --fail --retry 2 --connect-timeout 12 --max-time 180 "$base/$1" -o "$tmp/$2"; }
fetch deploy.prototxt deploy.prototxt
fetch mobilenet_iter_73000.caffemodel model.caffemodel
(verify_weights "$tmp")
apt-get update
apt-get install -y python3-opencv
/usr/bin/python3 - "$tmp" <<'PY'
import cv2, numpy as np, pathlib, sys
folder = pathlib.Path(sys.argv[1])
net = cv2.dnn.readNetFromCaffe(str(folder/"deploy.prototxt"),str(folder/"model.caffemodel"))
net.setInput(cv2.dnn.blobFromImage(np.zeros((300,300,3),dtype=np.uint8),1/127.5,(300,300),(127.5,)*3))
if net.forward().shape[-1]!=7:
    raise SystemExit("Detector self-test failed.")
PY
install -d -m 0755 /opt/cassie-os/vision
install -m 0644 "$tmp"/{deploy.prototxt,model.caffemodel} /opt/cassie-os/vision/
if [[ $# -eq 0 ]]; then systemctl restart cassie-os; fi
echo 'Local detector installed.'
