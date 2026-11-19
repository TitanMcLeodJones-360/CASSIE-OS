# CASSIE OS Desktop · TitanGame

CASSIE OS is a complete login session on Ubuntu Desktop 24.04 LTS. It opens the command center full screen. You do not need to open a browser or enter a URL. Ubuntu supplies the kernel, boot, networking and drivers, and remains available as a recovery desktop. Chromium provides the renderer; the local assistant is a separate background service.

## Install once

1. Finish installing Ubuntu Desktop on the SSD and boot it with the installer drive unplugged.
2. Download this ZIP to Downloads and open Terminal (Ctrl+Alt+T).
3. Run:

   ```bash
   sudo apt update && sudo apt install -y unzip &&
   unzip -n "$HOME/Downloads/CASSIE-OS-Desktop.zip" -d "$HOME/cassie-os-desktop" &&
   cd "$HOME/cassie-os-desktop" &&
   sudo bash install-desktop.sh
   ```

Keep internet connected for the initial installation. This includes the CASSIE app and the 2B local model by default. If the CASSIE command center is already installed and running, use `sudo bash install-desktop.sh --session-only` to add only the desktop session and its dependencies. This script does not reformat drives or change your login defaults.

If an earlier desktop install stopped at step 5 with `model 'cassie:local' not found`, extract this ZIP into a fresh folder and run `sudo bash install-desktop.sh` from there. This build uses `cassie:desktop` and reuses the previously downloaded 2B model. If you originally chose 4B, pass `4b` again.

## Enter CASSIE

Sign out of Ubuntu. Select your name on the login screen and click the gear before entering your password. Select **CASSIE OS**, then sign in. The dashboard launches when the assistant is ready. Enter the private CASSIE access key printed during setup. If needed, retrieve it from Terminal:

```bash
sudo cat /var/lib/cassie-os/access.token
```

CASSIE’s access key and your Ubuntu login password are separate. The session does not bypass or auto-fill either one.

| Shortcut | Action |
|---|---|
| Ctrl+Alt+Space | Open CASSIE system controls for files, Terminal, network, Bluetooth, sound, sign-out, and power |
| Ctrl+Alt+T | Open Terminal above CASSIE |
| Ctrl+Alt+B | Open Bluetooth devices |
| Alt+Tab | Switch between windows |
| Alt+F4 | Close the current window. If you close the dashboard, choose **Open CASSIE** to bring it back. |

The startup screen can show the assistant’s service log and retry if the service is offline. If you want the standard desktop again, use **System controls → Sign out**, then select **Ubuntu** from the login-screen gear. If the graphical session fails to start, the original Ubuntu session is still available. This is a personal desktop session: it is not a locked-down public kiosk or a bootable CASSIE ISO.

See `README.md` for model, camera, storage and network configuration. The 5 TB drive is optional and can stay disconnected during installation.

## Connect a Bluetooth speaker

If CASSIE is already installed, run `sudo bash install-desktop.sh --session-only` from this version’s extracted folder to add Bluetooth to the desktop. Sign out and back into **CASSIE OS**.

1. Put the speaker in pairing mode and press **Ctrl+Alt+B**. In Bluetooth Manager, choose **Search**, select your speaker, and choose **Pair**. Use **Connect** if it stays disconnected after pairing.
2. Open **Ctrl+Alt+Space → Sound and microphones → Output Devices**. Select **Set as fallback** for your speaker to make it the default output. If the active CASSIE audio stream is still going to the previous output, play a test and select the speaker for Chromium under **Playback**.
3. In the dashboard, choose **Awareness → Test voice** to check that CASSIE is speaking through the speaker.

TitanGame needs a Bluetooth adapter. If Bluetooth Manager shows no adapters, run `bluetoothctl list` in Terminal to see whether Ubuntu recognizes one.

## Turn on continuous camera observation

From this version's extracted folder, run `sudo bash update-camera.sh` to update an existing CASSIE desktop and set up its detector. If you just installed the desktop from this version, you can run `sudo bash install-vision.sh` to add the detector.

Sign out and back into **CASSIE OS** to load the updated dashboard. Unlock the console, open **Awareness**, and select **Turn on always-on camera**. The service keeps outlining objects after you lock or close the console and resumes after a restart. Open the dock or Awareness and select **Stop camera** to turn it off. The dock shows the latest annotated frame while the console is unlocked.

## Update live video, the Knowledge Web, and local voice

Run `sudo bash update-desktop.sh` from this version’s extracted folder on TitanGame. The updater sets up the offline speech model, updates the dashboard and camera, and runs a short local Ollama generation test. After signing back into CASSIE, open **Awareness → Enable “CASSIE”** and accept the microphone prompt. Say **“CASSIE”** to hear an acknowledgement, or say **“CASSIE, what can you do?”** to send a question to the model. Voice replies play through the selected system audio output.

The live feed targets 18 frames per second. The camera hardware and system load affect the actual rate. The Knowledge Web supports pan, zoom, and draggable topic nodes.

## Talk, remember, and use the live camera

In **Command**, select **Start conversation** to speak hands-free. You can also select **Record a question**, speak, and select **Send recording**. The microphone stays available for the wake word when a conversation times out. **Turn microphone off** in Awareness stops it. **Type instead** opens the keyboard input.

In **Awareness**, enable the microphone to reveal its device names. Select the webcam’s microphone from **Microphone input**, then speak and check the meter. The console processes your audio locally without saving recordings. After a spoken reply, you have 45 seconds to begin a follow-up without repeating “CASSIE.”

Say **“Remember that I like short answers”** to save a memory, or ask **“What do you remember about me?”** to review your most recent saved notes. View and remove saved notes in **Knowledge Web → Owner memory**. The app can also recall relevant statements from older chat history. **Workshop → Clear chat** clears that history.

Turn on the always-on camera in **Awareness**. The detector continuously checks the feed and updates the in-view labels. Ask **“What do you see right now?”** to send a fresh camera image to the local vision model. Camera frames stay in memory. Local vision requests can take longer than text replies.

## Search the dataset database and clear conversation

Run `sudo bash update-desktop.sh --app-only` from this version’s extracted folder to update the application. It imports the supplied Awesome Public Datasets snapshot into CASSIE’s local SQLite database on startup. Knowledge Web and chat use this index. It contains dataset titles, summaries, categories, and source links. Use the original links to obtain the underlying files.

In **Command → Type instead**, try **`/datasets KITTI`** for direct local results. The database can answer this search independently of Ollama.

Select **Clear conversation** in Command or Workshop and confirm. You can also say **“CASSIE, clear conversation”** and confirm on screen. This deletes chat history and its contribution to recall. Saved memories, preferences, and the dataset index stay available.

## Direct replies and research

Ordinary conversation starts with the answer. For a research request, CASSIE also explains the sources she used, how she checked or compared them, and what still needs verification.

For an exact line, type or say **Say “The rover is ready.”** CASSIE replies and speaks **The rover is ready.** For typed commands, quotes preserve capitalization and punctuation. For spoken commands, the line comes from the microphone transcript.

## Track your hotspot devices

From this release's extracted folder, run `sudo bash update-desktop.sh --app-only`. Reopen the dashboard after the update.

Set the hotspot interface once with `sudo systemctl edit cassie-os`. Above the editor's discard marker, add the following using the interface that runs CASSIE-NET. For the current desktop this is `wlp10s0`.

```ini
[Service]
Environment=CASSIE_HOTSPOT_INTERFACE=wlp10s0
```

Run `sudo systemctl daemon-reload` and `sudo systemctl restart cassie-os`. An existing interface override stays in place during updates.

Connect your devices to the hotspot. In **CASSIE-NET**, select **Track activity** beside each device you own or have permission to observe. **Device activity** refreshes every five seconds and shows approximate sent/received IP bytes and visible domain lookups. Choose a device to filter the recent results. A domain lookup can be made by a background app and does not prove someone opened a website.

Ask **“Show network activity”** or type **`/activity`** for a factual summary from these local records, even if Ollama is unavailable. A summary saved in chat remains in chat until you clear that conversation, independently of clearing the activity database.

The collector sees conventional unencrypted DNS queries over UDP port 53. Encrypted DNS, VPNs, cached results, and DNS over TCP can leave gaps. It cannot show exact HTTPS pages, messages, passwords, or which app is on screen. Randomized device MAC addresses can appear as separate devices and require selecting again.

History stays in the local SQLite database for up to seven days, with a maximum of 50,000 domain records and 30,000 traffic records. Busy networks may reach these limits sooner. **Pause collection** pauses all selected devices; **Stop tracking activity** removes one device from collection. **Clear activity history** deletes recorded activity for every device after confirmation. Saved selections remain, so pause first if you want the history to stay empty. Clearing chat and clearing network activity are separate actions.

Collection continues while the dashboard is locked or closed if enabled. It resumes with saved selections after reboot. The separate `cassie-os-network.service` has packet-socket access limited by its capability configuration. The web service does not receive this capability. No packet captures or page contents are saved. No DNS redirection, certificate installation, or firewall changes are made.

If Device activity says the collector is unavailable, check `sudo journalctl -u cassie-os-network -n 40 --no-pager`. If the hotspot has no Ethernet-style packet framing, the collector reports it as unavailable. Actual wireless-adapter capture behavior must be checked on the target PC.
