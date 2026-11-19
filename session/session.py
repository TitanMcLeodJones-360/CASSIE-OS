"""CASSIE's local graphical session. Operates entirely as the signed-in user."""

import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

APP_URL = "http://127.0.0.1:8787/"
WM_CONFIG = "/opt/cassie-os/desktop/openbox.xml"
CHROMIUM = "/snap/bin/chromium"


def app_ready():
    """Verify the expected local service; do not follow redirects or use proxies."""
    conn = http.client.HTTPConnection("127.0.0.1", 8787, timeout=1.0)
    try:
        conn.request("GET", "/api/health")
        response = conn.getresponse()
        if response.status != 200 or response.getheader("Content-Type", "").split(";")[0] != "application/json":
            return False
        body = response.read(257)
        return len(body) <= 256 and json.loads(body) == {"service": "cassie-os"}
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        conn.close()


def browser_command(home):
    return [
        CHROMIUM, "--ozone-platform=x11", "--kiosk", "--no-first-run",
        "--no-default-browser-check", "--disable-session-crashed-bubble",
        "--user-data-dir=" + str(home / "snap/chromium/common/cassie-desktop"),
        APP_URL,
    ]


def send_group(proc, sig):
    if proc is not None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass


def shutdown_children(*procs):
    # A browser process can have profile helpers left over even after its parent exits.
    for proc in procs:
        send_group(proc, signal.SIGTERM)
    deadline = time.monotonic() + 2
    for proc in procs:
        if proc is not None:
            try:
                proc.wait(timeout=max(0, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                send_group(proc, signal.SIGKILL)
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass


def ui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    css = Gtk.CssProvider()
    css.load_from_data(b"""
      window { background: #080c15; color: #edf3fc; }
      .hero { font-weight: 800; font-size: 27px; color: #e5efff; }
      .muted { color: #aec0de; }
      button { margin: 2px; background: #142543; color: #edf3fc;
               border: 1px solid #456cad; border-radius: 5px; }
      button:hover { background: #203b68; }
    """)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    def label(text, css_class):
        widget = Gtk.Label(label=text)
        widget.set_line_wrap(True)
        widget.set_xalign(0)
        widget.get_style_context().add_class(css_class)
        return widget

    def new_window(title, heading, detail, application=None):
        window = Gtk.ApplicationWindow(application=application) if application else Gtk.Window()
        window.set_title(title)
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_default_size(470, -1)
        window.set_keep_above(True)
        window.set_border_width(22)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        window.add(box)
        box.pack_start(label(heading, "hero"), False, False, 0)
        descr = label(detail, "muted")
        box.pack_start(descr, False, False, 0)
        return window, box, descr

    def button(box, text, callback):
        widget = Gtk.Button(label=text)
        widget.set_halign(Gtk.Align.FILL)
        widget.connect("clicked", callback)
        box.pack_start(widget, False, False, 0)
        return widget

    def run_command(argv, status):
        try:
            subprocess.Popen(argv, start_new_session=True)
        except OSError:
            status.set_text("Could not open " + argv[0] + ".")

    def confirm(window, question, action, argv, status):
        dialog = Gtk.MessageDialog(transient_for=window, modal=True, text=question)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, action, Gtk.ResponseType.OK)
        choice = dialog.run()
        dialog.destroy()
        if choice == Gtk.ResponseType.OK:
            run_command(argv, status)

    def controls():
        app = Gtk.Application(application_id="os.cassie.controls")

        def activate(application):
            if application.get_active_window() is not None:
                application.get_active_window().present()
                return
            window, box, status = new_window(
                "CASSIE • System controls", "System controls",
                "Open tools over CASSIE. Alt+Tab switches between them.", application
            )
            actions = (
                ("Files", ["/usr/bin/thunar"]),
                ("Terminal", ["/usr/bin/xterm"]),
                ("Network connections", ["/usr/bin/nm-connection-editor"]),
                ("Bluetooth devices", ["/usr/bin/blueman-manager"]),
                ("Sound and microphones", ["/usr/bin/pavucontrol"]),
            )
            for name, cmd in actions:
                button(box, name, lambda _, argv=cmd: run_command(argv, status))
            button(box, "Sign out", lambda _: confirm(
                window, "Sign out of the CASSIE session?", "Sign out",
                ["/usr/bin/openbox", "--exit"], status
            ))
            button(box, "Power off", lambda _: confirm(
                window, "Shut down this computer?", "Power off",
                ["/usr/bin/systemctl", "poweroff"], status
            ))
            button(box, "Back to CASSIE", lambda _: window.close())
            window.show_all()

        app.connect("activate", activate)
        return app.run([])

    def desktop():
        wm = subprocess.Popen(
            ["/usr/bin/openbox", "--config-file", WM_CONFIG],
            start_new_session=True,
        )
        browser = None
        checking = False
        launch_wanted = True
        started = time.monotonic()
        window, box, status = new_window(
            "CASSIE • Starting", "CASSIE OS",
            "Starting the assistant. The dashboard will open as soon as it’s ready."
        )
        window.connect("delete-event", lambda *_: True)

        def finish():
            Gtk.main_quit()
            return False

        def check_result(ready):
            nonlocal checking, browser, launch_wanted
            checking = False
            if ready and launch_wanted and browser is None:
                launch_wanted = False
                try:
                    browser = subprocess.Popen(browser_command(Path.home()), start_new_session=True)
                except OSError:
                    status.set_text("Chromium could not start. Use System controls or sign out.")
                else:
                    window.hide()
            elif launch_wanted and time.monotonic()-started>18:
                status.set_text("CASSIE is not ready. You can open its service log, retry, or sign out.")
            return False

        def check():
            nonlocal browser, checking
            if wm.poll() is not None:
                return finish()
            if browser is not None:
                if browser.poll() is None:
                    return True
                send_group(browser, signal.SIGTERM)
                browser = None
                status.set_text("The dashboard closed. Choose Open CASSIE to bring it back.")
                window.show_all()
                window.present()
            if launch_wanted and not checking:
                checking = True
                threading.Thread(
                    target=lambda: GLib.idle_add(check_result, app_ready()), daemon=True
                ).start()
            return True

        def retry(_):
            nonlocal launch_wanted, started
            launch_wanted = True
            started = time.monotonic()
            status.set_text("Checking the CASSIE service…")

        button(box, "Open CASSIE", retry)
        button(box, "System controls", lambda _: run_command(
            ["/usr/bin/python3", __file__, "--controls"], status))
        button(box, "View service log", lambda _: run_command(
            ["/usr/bin/xterm", "-hold", "-e", "/usr/bin/journalctl",
             "-u", "cassie-os", "-n", "60", "--no-pager"], status))
        button(box, "Sign out", lambda _: confirm(window, "Return to the login screen?", "Sign out",
                                                   ["/usr/bin/openbox", "--exit"], status))
        try:
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, finish)
            GLib.timeout_add(900, check)
            window.show_all()
            Gtk.main()
        finally:
            shutdown_children(browser, wm)
        return 0

    return controls() if sys.argv[1:] == ["--controls"] else desktop()


if __name__ == "__main__":
    if os.geteuid() == 0 or not os.environ.get("DISPLAY"):
        sys.exit("Start CASSIE through the graphical login screen as a normal user.")
    sys.exit(ui())
