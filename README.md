# CASSIE OS · CASSIE Command Center

Start with [START-HERE.md](START-HERE.md) to install the full-screen desktop session or update an existing installation.

This package is the application and its service definitions for Ubuntu 24.04 LTS on x86-64. It is not an OS image and does not prepare or format disks. No previous Raspberry Pi configuration is required.

## What the Ubuntu build does

| Module | Behavior |
|---|---|
| DSM / 01 · Data storage | System database, keys and chat under `/var/lib/cassie-os`; model under `/var/lib/cassie-model`. The optional archive reading appears only when `/srv/cassie-data` (or the administrator's `CASSIE_BULK_MOUNT`) is an actual mount. File ingestion and archive backup are not automatic. |
| DSM / 02 · Memory cache | Reads available and total RAM; Linux manages the disk cache. Nominal 20 GB RAM is not a reservation. |
| PAS · Public address | Locally synthesized feminine eSpeak NG English preset and spoken replies. Enable “CASSIE” once per session to use the local Vosk speech recognizer. Saying “CASSIE” or “Hey CASSIE” opens Command and starts a short follow-up window. The mic turns off when you lock or close the dashboard. |
| DMM · Decision-making | `cassie:desktop` is a local model profile using Qwen3.5 2B (or 4B). Witty/adaptive personality, editable tone preferences, retrieved owner notes, and catalog links. GPU use depends on drivers and free VRAM. This build runs inference offline and uses pretrained weights. |
| HDM · Hardware diagnostics | Reads available CPU temperature, load, RAM, SSD capacity and optional NVIDIA telemetry. Sentinel checks release file hashes and SQLite integrity approximately every two minutes. These checks don't establish physical faults, malware signatures, or whether a breach occurred. |
| SMH · Standby | App and inference service have separate systemd restart policies; model weights unload after five minutes of idle time. The quick camera preview ends when its view is hidden or locked. The optional always-on camera continues under the system service. Both services share TitanGame; independent hardware watchdogs and power-fail failover are outside this build. |

**Ω Red — integrity failure.** The console reports local database corruption or a release-file change. Workshop offers an operator-confirmed quarantine action for an ordinary single-link file in the app's staging inbox. It moves the file to a private directory with owner-read-only permissions and no executable bit. It never deletes the original data, runs it, attempts to neutralize a remote system, or touches other directories. Manual code edits intentionally trip the file hash check until you review and refresh the release baseline. A clean integrity check is not a clean bill of health.

**Δ Yellow — new or possibly missing device.** The app samples reachable neighbor addresses on the configured CASSIE-NET interface every 20 seconds. A newly observed device stays yellow for five minutes; a device you've chosen to watch is marked missing after 15 minutes without observation. Idle clients can go quiet. This is not a client inventory, location tracker, or authentication mechanism. Optional activity collection is configured separately for selected devices.

**γ Green — happy expression.** Changes the orb's expression; it has no effect on security or monitoring. An actual red signal takes precedence over yellow and green, and yellow takes precedence over green.

**Awareness.** Run `sudo bash update-camera.sh` on an existing desktop install to set up the pinned, SHA-256-verified MobileNet SSD weights and OpenCV. In Awareness, **Turn on always-on camera** starts TitanGame’s attached camera and streams the camera at up to 18 frames per second while a separate worker detects objects and tracks the outlines between detections. CASSIE keeps the latest annotated frame in memory and replaces it as new frames arrive. Sign-out, dashboard lock, and reboot leave the preference enabled. **Stop camera** clears the frame and disables automatic restart. The unlocked dashboard shows the feed in Awareness or in a small view on other pages. The detector covers a fixed set of common categories and uses bounding boxes. Enable **Occasional comments** to have the open console comment on changes in recognized object labels. For a specific camera, set `CASSIE_CAMERA_DEVICE=/dev/v4l/by-id/…` in a `cassie-os.service` override and restart the service. The quick camera preview still uses the browser’s camera. The offline demo uses a simulated frame.

**Knowledge web.** CASSIE imports its [Awesome Public Datasets](https://github.com/awesomedata/awesome-public-datasets) snapshot into local SQLite, alongside an Owner memory branch. Drag the map to pan, drag a node to move it, zoom with the wheel or buttons, and select a node to explore its sources. Each dataset entry has a title, summary, category, and original source link. Use `/datasets KITTI` for a direct search even if the model is offline. Follow the source links to get the underlying files and review their use and license terms.

**Workshop.** The model can propose changes with a test or draft diff against a bounded excerpt of a selected shipped source file. Proposals don't apply or execute anything. Diagnostic commands are copied for the owner to run in their Ubuntu terminal. `./open-cassie` opens the dashboard in locally installed Chromium; source links open as separate browser tabs with no access to the console token. There is no terminal or unrestricted command runner exposed by the web app.

## When you're ready to install

To make CASSIE your full-screen login session, follow `START-HERE.md`. The commands below cover installing the assistant service by itself.

Use [Ubuntu Desktop 24.04 LTS](https://ubuntu.com/download/desktop) if you want CASSIE to use the camera, microphone, speakers, and Chromium at TitanGame. It can still serve as a server. Use Ubuntu Server 24.04 LTS if another computer will host the interface and sensors. Keep any HDD with data you want disconnected if choosing the installer option that erases your SSD.

Copy this ZIP to the Ubuntu machine and extract it into a new folder. From that folder:

```bash
sudo bash install.sh 2b
```

The 2B variant is the practical starting point for 4 GB VRAM. Try the default `sudo bash install.sh` for 4B once the GPU and latency are measured. Installation needs internet for packages and the pinned Ollama runtime/model downloads, with at least 15 GB temporarily free. It does not install NVIDIA drivers. Check `nvidia-smi` after following [Ubuntu’s driver instructions](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/) if needed. Use `OLLAMA_HOST=127.0.0.1:11438 /opt/cassie-os/ollama-0.40.4/bin/ollama ps` to check actual offload.

On TitanGame use `http://127.0.0.1:8787/`, or run `./open-cassie` once Chromium is installed. The operator token is private; view it when you need it with `sudo cat /var/lib/cassie-os/access.token`. The app and model port stay bound to loopback by default. On another computer connecting to TitanGame through a trusted local network, if SSH is enabled you may instead use:

```bash
ssh -N -L 127.0.0.1:8787:127.0.0.1:8787 USER@TITANGAME_LAN_IP
```

Then open the same local URL on that computer. Joining CASSIE-NET alone does not expose the dashboard in this build. Direct access from phones would require a trusted HTTPS entry point restricted to the hotspot, plus the existing owner auth; don't forward the model port.

### Optional private CASSIE-NET
Set up a password-protected network with NetworkManager’s hotspot option when TitanGame has an adapter that supports AP mode. Connect TitanGame to an authorized upstream by Ethernet or a separate Wi-Fi radio when sharing Wi-Fi in and out; do not assume the same card and driver support both modes at once. NetworkManager's [shared IPv4 mode](https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html) supplies client addressing, DNS forwarding and NAT through TitanGame’s default connection. Neither installer changes the host's network. Verify network policy before redistributing a campus uplink.

When the hotspot works, use `sudo systemctl edit cassie-os` to put the **hotspot interface name**, not the uplink interface, in a drop-in:
```ini
[Service]
Environment=CASSIE_HOTSPOT_INTERFACE=YOUR_AP_INTERFACE
```
Apply it with `sudo systemctl restart cassie-os`. Remove the override if you want to stop neighbor monitoring. Only the chosen watched MAC addresses persist through reboot; passive observation starts again empty.

To enable app-scoped quarantine, create the private staging directory as follows:
```bash
sudo install -d -m 0700 -o cassie-os -g cassie-os /var/lib/cassie-os/inbox
```
Deliberately stage only files you want reviewed. Workshop displays the resulting isolation ID. Originals are kept under `/var/lib/cassie-os/quarantine`; inspect or recover them from a trusted local administrative session.

Logs: `sudo journalctl -u cassie-os -u cassie-os-model -n 80 --no-pager`.
The included `build_preview.py` writes the standalone preview and release baseline from source. Only rebuild and apply the baseline after reviewing the changed files. Dataset source and its license are included under `app/`.

## Hotspot activity

The optional device activity view records visible DNS lookups and approximate sent/received IP byte totals for individually selected hotspot devices. Install it with `sudo bash update-desktop.sh --app-only`, then open **CASSIE-NET → Track activity** beside an observed device. Configure `CASSIE_HOTSPOT_INTERFACE` on the web service as described above. Collection starts only after a device is selected.

Activity records stay in local SQLite for up to seven days with bounded record counts. The dashboard includes device filtering, pause/resume, stop tracking, and a confirmed clear-history action. Closing or locking the dashboard leaves enabled collection running. Clear activity history is separate from Clear conversation.

Domain records are unencrypted DNS questions over UDP, including background requests. They are not verified browsing visits or a list of foreground apps. HTTPS page paths and contents are unavailable. Encrypted DNS, VPNs, and cached names can hide domain activity. See [START-HERE.md](START-HERE.md#track-your-hotspot-devices) for setup, limits, and troubleshooting.

The separate `cassie-os-network.service` runs the bundled Python collector with `CAP_NET_RAW`, binds to the configured interface, and discards packet bytes after extracting metadata. It does not enable promiscuous mode, redirect DNS, decrypt traffic, install certificates, change hotspot settings, or change firewall rules. The web service retains its existing capabilities.

## Development

On a development machine with Python 3.12 and Node.js, create an environment and run the automated checks.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pytest pillow
.venv/bin/python -m pytest -q tests
node --check app/static/app.js
node --check app/static/mic-worklet.js
```

These tests use simulated model replies and camera input. Camera, microphone, Bluetooth audio, GPU inference, and login-session behavior also need verification on the target Ubuntu machine.

To generate an offline dashboard preview, run `python3 build_preview.py` and open `../output/CASSIE-Command-Preview.html`. It uses simulated chat, device, and camera data. It also refreshes the application integrity baseline, so run it only after reviewing application changes.
