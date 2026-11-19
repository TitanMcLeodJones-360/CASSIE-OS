"""Local hotspot metadata, explicit device selection, and a separate packet collector."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import socket
import sqlite3
import struct
import time

MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
IFACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}")
RETENTION = 7 * 86400
MAX_DEVICES = 64


def valid_mac(value):
    if not isinstance(value, str) or not MAC.fullmatch(value):
        raise ValueError("Choose a device from the hotspot list.")
    if int(value[:2], 16) & 1 or value == "00:00:00:00:00:00":
        raise ValueError("Choose an ordinary device address.")
    return value


class Activity:
    def __init__(self, root, interface=None):
        self.db = Path(root) / "cassie.sqlite3"
        with self.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS activity_settings (
                  id INTEGER PRIMARY KEY CHECK(id=1), interface TEXT NOT NULL DEFAULT '',
                  enabled INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO activity_settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS activity_devices (mac TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS activity_traffic (
                  minute INTEGER NOT NULL, mac TEXT NOT NULL, sent INTEGER NOT NULL,
                  received INTEGER NOT NULL, PRIMARY KEY(minute,mac)
                );
                CREATE TABLE IF NOT EXISTS activity_dns (
                  minute INTEGER NOT NULL, mac TEXT NOT NULL, domain TEXT NOT NULL,
                  queries INTEGER NOT NULL, last_seen INTEGER NOT NULL,
                  PRIMARY KEY(minute,mac,domain)
                );
                CREATE TABLE IF NOT EXISTS activity_collector (
                  id INTEGER PRIMARY KEY CHECK(id=1), updated INTEGER NOT NULL,
                  state TEXT NOT NULL, detail TEXT NOT NULL
                );
            """)
            if interface is not None:
                interface = interface if IFACE.fullmatch(interface) else ""
                old = c.execute("SELECT interface FROM activity_settings WHERE id=1").fetchone()[0]
                if old != interface:
                    c.execute("UPDATE activity_settings SET interface=?,enabled=0,generation=generation+1 WHERE id=1", (interface,))
                    c.execute("DELETE FROM activity_devices")
        self.prune()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=4)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    @staticmethod
    def settings_from(c):
        value = dict(c.execute("SELECT * FROM activity_settings WHERE id=1").fetchone())
        value["enabled"] = bool(value["enabled"])
        value["devices"] = [r[0] for r in c.execute("SELECT mac FROM activity_devices ORDER BY mac")]
        return value

    def settings(self):
        with self.connect() as c:
            return self.settings_from(c)

    def select(self, mac, tracked):
        mac = valid_mac(mac)
        if type(tracked) is not bool:
            raise ValueError("Choose whether to track this device.")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            config = self.settings_from(c)
            if tracked:
                if not config["interface"]:
                    raise ValueError("Configure CASSIE_HOTSPOT_INTERFACE first.")
                if mac not in config["devices"] and len(config["devices"]) >= MAX_DEVICES:
                    raise ValueError("Up to 64 devices can be tracked at once.")
                c.execute("INSERT OR IGNORE INTO activity_devices VALUES(?)", (mac,))
            else:
                c.execute("DELETE FROM activity_devices WHERE mac=?", (mac,))
            any_selected = c.execute("SELECT 1 FROM activity_devices LIMIT 1").fetchone() is not None
            c.execute("UPDATE activity_settings SET enabled=?,generation=generation+1 WHERE id=1",
                      (int(any_selected and (tracked or config["enabled"])),))

    def enable(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Choose whether activity collection is on.")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            config = self.settings_from(c)
            if enabled and (not config["interface"] or not config["devices"]):
                raise ValueError("Choose a hotspot device to track first.")
            c.execute("UPDATE activity_settings SET enabled=?,generation=generation+1 WHERE id=1", (int(enabled),))

    def clear(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE activity_settings SET generation=generation+1 WHERE id=1")
            c.execute("DELETE FROM activity_traffic")
            c.execute("DELETE FROM activity_dns")

    def heartbeat(self, state, detail):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO activity_collector VALUES(1,?,?,?)", (int(time.time()), state, detail))

    def flush(self, generation, traffic, domains):
        now = int(time.time())
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            config = self.settings_from(c)
            if generation != config["generation"] or not config["enabled"]:
                return
            allowed = set(config["devices"])
            for (minute, mac), (sent, received) in traffic.items():
                if mac in allowed and now-RETENTION <= minute <= now:
                    c.execute("INSERT INTO activity_traffic VALUES(?,?,?,?) ON CONFLICT(minute,mac) DO UPDATE SET "
                              "sent=sent+excluded.sent,received=received+excluded.received", (minute, mac, sent, received))
            for (minute, mac, domain), (queries, last_seen) in domains.items():
                if mac in allowed and now-RETENTION <= minute <= now:
                    c.execute("INSERT INTO activity_dns VALUES(?,?,?,?,?) ON CONFLICT(minute,mac,domain) DO UPDATE SET "
                              "queries=queries+excluded.queries,last_seen=MAX(last_seen,excluded.last_seen)",
                              (minute, mac, domain, queries, last_seen))

    def prune(self):
        with self.connect() as c:
            for table, limit in (("activity_dns", 50000), ("activity_traffic", 30000)):
                c.execute(f"DELETE FROM {table} WHERE minute<?", (int(time.time())-RETENTION,))
                # Bound storage even on unusually busy networks. Keep newest records.
                boundary = c.execute(f"SELECT minute FROM {table} ORDER BY minute DESC LIMIT 1 OFFSET ?", (limit,)).fetchone()
                if boundary:
                    c.execute(f"DELETE FROM {table} WHERE minute<=?", (boundary[0],))

    def snapshot(self, mac=None):
        if mac is not None:
            valid_mac(mac)
        now = int(time.time())
        cutoff = now-RETENTION
        with self.connect() as c:
            config = self.settings_from(c)
            collector = c.execute("SELECT * FROM activity_collector WHERE id=1").fetchone()
            where = "minute>=?" + (" AND mac=?" if mac else "")
            args = (cutoff, mac) if mac else (cutoff,)
            totals = [dict(r) for r in c.execute(
                f"SELECT mac,SUM(sent) AS sent,SUM(received) AS received,MAX(minute) AS last_seen "
                f"FROM activity_traffic WHERE {where} GROUP BY mac ORDER BY last_seen DESC", args)]
            domains = [dict(r) for r in c.execute(
                f"SELECT mac,domain,SUM(queries) AS queries,MAX(last_seen) AS last_seen "
                f"FROM activity_dns WHERE {where} GROUP BY mac,domain ORDER BY last_seen DESC LIMIT 100", args)]
        state, detail = "off", "Select Track activity beside one of your devices."
        if config["enabled"]:
            state, detail = "unavailable", "Collector is not reporting. Run sudo systemctl status cassie-os-network."
            if collector and now-collector["updated"] < 15:
                state, detail = collector["state"], collector["detail"]
        elif config["devices"]:
            detail = "Collection is paused. Saved history remains available."
        return {"enabled":config["enabled"], "interface":config["interface"], "tracked":config["devices"],
                "state":state, "detail":detail, "totals":totals, "domains":domains, "retention_days":7,
                "coverage":"Unencrypted DNS lookups over UDP and approximate IP traffic totals. "
                           "Lookups can come from background apps. Encrypted DNS, VPNs, and cached names hide domains. "
                           "Exact pages, foreground apps, and message contents are not available."}


def dns_question(data):
    """Accept one conventional DNS question. Reject responses and malformed wire names."""
    if len(data) < 17:
        return None
    _, flags, questions, _, _, _ = struct.unpack_from("!6H", data)
    if flags & 0xF800 or questions != 1:
        return None
    labels, index, size = [], 12, 0
    while index < len(data):
        length = data[index]
        index += 1
        if length == 0:
            break
        if length > 63 or index+length > len(data):
            return None
        label = data[index:index+length]
        if not re.fullmatch(rb"[A-Za-z0-9_-]+", label):
            return None
        labels.append(label.decode("ascii").lower())
        size += length+1
        if size > 253:
            return None
        index += length
    else:
        return None
    if not labels or index+4 > len(data):
        return None
    _, qclass = struct.unpack_from("!HH", data, index)
    return ".".join(labels) if qclass == 1 else None


def packet_metadata(frame):
    """Read Ethernet/IP sizes and optional UDP DNS question without retaining packets."""
    if len(frame) < 14:
        return None
    destination = frame[:6].hex(":")
    source = frame[6:12].hex(":")
    protocol = struct.unpack_from("!H", frame, 12)[0]
    offset = 14
    for _ in range(2):
        if protocol not in (0x8100, 0x88A8):
            break
        if len(frame) < offset+4:
            return None
        protocol = struct.unpack_from("!H", frame, offset+2)[0]
        offset += 4
    if protocol == 0x0800:
        if len(frame) < offset+20 or frame[offset] >> 4 != 4:
            return None
        header = (frame[offset] & 15)*4
        length = struct.unpack_from("!H", frame, offset+2)[0]
        if header < 20 or length < header or len(frame) < offset+header:
            return None
        end = min(len(frame), offset+length)
        transport = frame[offset+9]
        fragments = struct.unpack_from("!H", frame, offset+6)[0]
        udp = offset+header if not fragments & 0x3FFF else None
    elif protocol == 0x86DD:
        if len(frame) < offset+40 or frame[offset] >> 4 != 6:
            return None
        length = 40+struct.unpack_from("!H", frame, offset+4)[0]
        end = min(len(frame), offset+length)
        transport, udp = frame[offset+6], offset+40
        for _ in range(8):
            if transport not in (0, 43, 60):
                break
            if udp+2 > end:
                return None
            nxt, count = frame[udp:udp+2]
            udp += (count+1)*8
            if udp > end:
                return None
            transport = nxt
        # Fragmented packets and unsupported extension headers still count as bytes.
    else:
        return None
    domain = None
    if transport == 17 and udp is not None and udp+8 <= end:
        _, port, size, _ = struct.unpack_from("!4H", frame, udp)
        if port == 53 and 8 <= size <= end-udp:
            domain = dns_question(frame[udp+8:udp+size])
    return source, destination, length, domain


class Batch:
    def __init__(self, config):
        self.generation = config["generation"]
        self.devices = set(config["devices"]) if config["enabled"] else set()
        self.traffic, self.domains = {}, {}

    def accept(self, frame, now=None):
        # Discard unselected MACs before inspecting any network-layer payload.
        if len(frame) < 14:
            return
        source, destination = frame[6:12].hex(":"), frame[:6].hex(":")
        if source not in self.devices and destination not in self.devices:
            return
        metadata = packet_metadata(frame)
        if metadata is None:
            return
        source, destination, size, domain = metadata
        now = int(time.time()) if now is None else now
        minute = now//60*60
        for mac, sent in ((source, True), (destination, False)):
            if mac in self.devices:
                key = (minute, mac)
                amounts = self.traffic.setdefault(key, [0, 0])
                amounts[0 if sent else 1] += size
        if domain and source in self.devices:
            key = (minute, source, domain)
            if key in self.domains or len(self.domains) < 2048:
                amount = self.domains.setdefault(key, [0, now])
                amount[0] += 1
                amount[1] = now


def run(root):
    activity = Activity(root)
    config, batch, capture = None, None, None
    checked = flushed = pruned = 0.0
    dropped = 0
    while True:
        now = time.monotonic()
        if now-checked >= 1:
            current = activity.settings()
            checked = now
            if current != config:
                if capture is not None:
                    capture.close()
                    capture = None
                config, batch = current, Batch(current)
            enabled = config["enabled"] and bool(config["devices"])
            if enabled and capture is None:
                interface = config["interface"]
                try:
                    if not IFACE.fullmatch(interface) or not (Path("/sys/class/net")/interface).exists():
                        raise OSError("interface unavailable")
                    if (Path("/sys/class/net")/interface/"type").read_text().strip() != "1":
                        raise OSError("interface has no Ethernet framing")
                    capture = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, 0)
                    capture.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
                    # Protocol 0 until bind keeps capture scoped to the configured interface.
                    capture.bind((interface, 3))
                    capture.settimeout(.25)
                except OSError:
                    if capture is not None:
                        capture.close()
                        capture = None
                    activity.heartbeat("unavailable", "Could not observe the hotspot. Check its interface and cassie-os-network service log.")
            if not enabled:
                activity.heartbeat("off", "Activity collection is paused.")
        if capture is None:
            time.sleep(.25)
        else:
            try:
                frame, address = capture.recvfrom(4096)
                # Ignore loopback and packets addressed to other hosts.
                if address[2] in (0, 1, 2, 4):
                    batch.accept(frame)
            except socket.timeout:
                pass
            except OSError:
                capture.close()
                capture = None
        if now-flushed >= 2:
            if batch is not None:
                activity.flush(batch.generation, batch.traffic, batch.domains)
                batch = Batch(config)
            if capture is not None:
                try:
                    stats = capture.getsockopt(263, 6, 12)  # SOL_PACKET, PACKET_STATISTICS
                    if len(stats) >= 8:
                        dropped += struct.unpack_from("=II", stats)[1]
                except OSError:
                    pass
                detail = "Observing selected hotspot devices. Domain lookups may be hidden by encryption or caching."
                if dropped:
                    detail += f" {dropped} packets dropped since the collector started; totals may be low."
                activity.heartbeat("observing", detail)
            flushed = now
        if now-pruned >= 60:
            activity.prune()
            pruned = now


if __name__ == "__main__":
    os.umask(0o077)
    run(Path(os.environ.get("CASSIE_STATE_DIR", "/var/lib/cassie-os")))
