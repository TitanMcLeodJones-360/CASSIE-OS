"""Exercise real wire parsers and SQLite boundaries without observing a live network."""
import json
from pathlib import Path
import struct
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"app"))
from network_activity import Activity, Batch, dns_question, packet_metadata

PHONE = "02:11:22:33:44:55"
OTHER = "02:aa:bb:cc:dd:ee"
GATEWAY = "02:00:00:00:00:01"


def dns(name="example.org", flags=0x0100):
    qname = b"".join(bytes([len(label)])+label.encode() for label in name.split("."))+b"\0"
    return struct.pack("!6H", 7, flags, 1, 0, 0, 0)+qname+struct.pack("!HH", 1, 1)


def frame(payload=None, *, source=PHONE, destination=GATEWAY, ipv6=False, port=53, fragment=0, vlan=False):
    payload = dns() if payload is None else payload
    udp = struct.pack("!4H", 20000, port, len(payload)+8, 0)+payload
    if ipv6:
        header = struct.pack("!IHBB16s16s", 6 << 28, len(udp), 17, 64, b"\x20\x01"+b"\0"*14, b"\x20\x02"+b"\0"*14)
        proto = 0x86DD
    else:
        header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20+len(udp), 1, fragment, 64, 17, 0, b"\x0a\x2a\0\x02", b"\x0a\x2a\0\x01")
        proto = 0x0800
    prefix = bytes.fromhex(destination.replace(":", ""))+bytes.fromhex(source.replace(":", ""))
    return prefix+(struct.pack("!HHH", 0x8100, 1, proto) if vlan else struct.pack("!H", proto))+header+udp


@pytest.mark.parametrize("ipv6,vlan", [(False, False), (True, False), (False, True)])
def test_dns_metadata_and_byte_direction(ipv6, vlan):
    config = {"generation":1, "enabled":True, "devices":[PHONE]}
    batch = Batch(config)
    outgoing = frame(ipv6=ipv6, vlan=vlan)
    batch.accept(outgoing, 180)
    incoming = frame(b"opaque downloaded content", source=GATEWAY, destination=PHONE, port=443, ipv6=ipv6)
    batch.accept(incoming, 180)
    assert batch.domains == {(180, PHONE, "example.org"):[1, 180]}
    assert batch.traffic[(180, PHONE)] == [len(outgoing)-(18 if vlan else 14), len(incoming)-14]
    assert "opaque downloaded content" not in repr(batch.__dict__)


def test_no_inference_from_encrypted_payloads_or_unselected_devices():
    batch = Batch({"generation":0, "enabled":True, "devices":[PHONE]})
    batch.accept(frame(source=OTHER), 120)
    assert not batch.traffic and not batch.domains
    batch.accept(frame(dns("hidden.example"), port=443), 120)
    assert batch.traffic and not batch.domains
    off = Batch({"generation":0, "enabled":False, "devices":[PHONE]})
    off.accept(frame())
    assert not off.traffic and not off.domains


def test_malformed_dns_fragments_and_short_packets_do_not_create_domains():
    assert dns_question(dns(flags=0x8180)) is None
    assert dns_question(dns()[:18]) is None
    assert dns_question(dns("bad!name.example")) is None
    assert dns_question(struct.pack("!6H", 1, 0, 1, 0, 0, 0)+b"\xc0\x0c\x00\x01\x00\x01") is None
    assert packet_metadata(frame(fragment=0x2000))[-1] is None
    for length in range(14+20+8):
        result = packet_metadata(frame()[:length])
        assert result is None or result[-1] is None


def test_selection_pause_clear_and_restart_do_not_resurrect_pending_history(tmp_path):
    activity = Activity(tmp_path, "wlp10s0")
    assert not activity.settings()["enabled"]
    activity.select(PHONE, True)
    settings = activity.settings()
    batch = Batch(settings)
    batch.accept(frame())
    activity.flush(batch.generation, batch.traffic, batch.domains)
    snapshot = activity.snapshot()
    assert snapshot["totals"][0]["sent"] > 0
    assert snapshot["domains"][0]["domain"] == "example.org"
    activity.clear()
    activity.flush(batch.generation, batch.traffic, batch.domains)
    assert not activity.snapshot()["domains"] and not activity.snapshot()["totals"]
    settings = activity.settings()
    batch = Batch(settings)
    batch.accept(frame())
    activity.enable(False)
    activity.flush(batch.generation, batch.traffic, batch.domains)
    assert not activity.snapshot()["totals"]
    reopened = Activity(tmp_path, "wlp10s0")
    assert reopened.settings()["devices"] == [PHONE] and not reopened.settings()["enabled"]
    reopened.enable(True)
    batch = Batch(reopened.settings())
    batch.accept(frame())
    reopened.select(PHONE, False)
    reopened.flush(batch.generation, batch.traffic, batch.domains)
    assert not reopened.snapshot()["domains"]


def test_filters_retention_and_interface_change(tmp_path):
    activity = Activity(tmp_path, "wlp10s0")
    for mac in (PHONE, OTHER):
        activity.select(mac, True)
    config = activity.settings()
    batch = Batch(config)
    batch.accept(frame())
    batch.accept(frame(dns("another.example"), source=OTHER))
    activity.flush(batch.generation, batch.traffic, batch.domains)
    assert [r["domain"] for r in activity.snapshot(PHONE)["domains"]] == ["example.org"]
    assert len(activity.snapshot()["domains"]) == 2
    with activity.connect() as c:
        c.execute("INSERT INTO activity_dns VALUES(0,?,?,1,0)", (PHONE,"expired.example"))
    activity.prune()
    with activity.connect() as c:
        assert not c.execute("SELECT 1 FROM activity_dns WHERE minute=0").fetchone()
    changed = Activity(tmp_path, "another0")
    assert not changed.settings()["enabled"] and changed.settings()["devices"] == []
    assert len(changed.snapshot()["domains"]) == 2
    with pytest.raises(ValueError):
        changed.select("ff:ff:ff:ff:ff:ff", True)


def test_heartbeat_and_missing_collector_report_actual_state(tmp_path, monkeypatch):
    activity = Activity(tmp_path, "wlp10s0")
    activity.select(PHONE, True)
    assert activity.snapshot()["state"] == "unavailable"
    activity.heartbeat("observing", "Running")
    assert activity.snapshot()["state"] == "observing"
    with activity.connect() as c:
        c.execute("UPDATE activity_collector SET updated=0")
    assert activity.snapshot()["state"] == "unavailable"


def test_collector_binds_only_configured_interface_and_flushes_metadata(tmp_path, monkeypatch):
    import network_activity as module
    activity = Activity(tmp_path, "wlp10s0")
    activity.select(PHONE, True)
    fake_sys = tmp_path/"interfaces"
    (fake_sys/"wlp10s0").mkdir(parents=True)
    (fake_sys/"wlp10s0/type").write_text("1")
    real_path = Path
    monkeypatch.setattr(module, "Path", lambda p: fake_sys if str(p)=="/sys/class/net" else real_path(p))
    opened, bound, clock = [], [], [0]

    class Done(Exception):
        pass

    class Capture:
        reads = 0

        def setsockopt(self, *args): pass
        def settimeout(self, timeout): pass
        def close(self): pass
        def bind(self, address): bound.append(address)
        def getsockopt(self, *args): return struct.pack("=II", 4, 0)

        def recvfrom(self, size):
            self.reads += 1
            if self.reads > 4:
                raise Done()
            return frame(), ("wlp10s0", 0, 0, 1, b"")

    def open_socket(*args):
        opened.append(args)
        return Capture()

    def monotonic():
        clock[0] += 1
        return clock[0]

    monkeypatch.setattr(module.socket, "socket", open_socket)
    monkeypatch.setattr(module.time, "monotonic", monotonic)
    with pytest.raises(Done):
        module.run(tmp_path)
    assert opened[0][2] == 0  # No packets until binding to the selected interface.
    assert bound == [("wlp10s0", 3)]
    assert activity.snapshot()["domains"][0]["queries"] == 4
