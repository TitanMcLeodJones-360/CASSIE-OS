#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID != 0 ]]; then
    printf '%s\n' 'Run: sudo bash install-desktop.sh'
    exit 1
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 || $(uname -m) != x86_64 ]]; then
    printf '%s\n' 'This release requires Ubuntu Desktop 24.04 LTS (x86-64).'
    exit 1
fi
if [[ ! -x /usr/sbin/gdm3 ]] || ! systemctl is-active --quiet display-manager.service; then
    printf '%s\n' 'Run this after booting the installed Ubuntu Desktop on the SSD and signing in.'
    exit 1
fi
if [[ $# -gt 1 ]]; then
    printf '%s\n' 'Usage: sudo bash install-desktop.sh [2b|4b|--session-only]'
    exit 2
fi
choice=${1:-2b}
case "$choice" in
    2b|4b|--session-only) ;;
    *) printf '%s\n' 'Usage: sudo bash install-desktop.sh [2b|4b|--session-only]'; exit 2 ;;
esac
if [[ $choice == --session-only ]] && ! systemctl is-active --quiet cassie-os.service; then
    printf '%s\n' 'The CASSIE service is not active. Run this installer without --session-only.'
    exit 1
fi

echo '[Desktop 1/3] Install the CASSIE desktop dependencies.'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    openbox xserver-xorg xterm thunar pavucontrol network-manager-gnome python3-gi gir1.2-gtk-3.0 \
    bluez blueman libspa-0.2-bluetooth
if ! systemctl enable --now bluetooth.service; then
    echo 'Bluetooth service did not start. Check systemctl status bluetooth.service.'
fi
if ! snap list chromium >/dev/null 2>&1; then
    snap install chromium
fi
test -x /snap/bin/chromium

echo '[Desktop 2/3] Prepare the local assistant.'
if [[ $choice != --session-only ]]; then
    CASSIE_INSTALL_DESKTOP=1 bash install.sh "$choice"
fi

echo '[Desktop 3/3] Register the CASSIE OS login session.'
install -d -m 0755 /opt/cassie-os/desktop /usr/local/bin /usr/share/xsessions
install -m 0644 session/openbox.xml session/session.py /opt/cassie-os/desktop/
install -m 0755 session/cassie-desktop-session /usr/local/bin/cassie-desktop-session
install -m 0644 session/cassie-os.desktop /usr/share/xsessions/cassie-os.desktop

cat <<'STEPS'
CASSIE OS desktop session installed.
Sign out of Ubuntu. On the login screen select your account, then the gear,
then CASSIE OS. Sign in to open CASSIE in full screen.
Ctrl+Alt+Space opens System controls. Ctrl+Alt+T opens Terminal.
Ctrl+Alt+B opens Bluetooth devices.
To retrieve the CASSIE access key privately: sudo cat /var/lib/cassie-os/access.token
To switch back, sign out and choose Ubuntu with the same login-screen gear.
STEPS
