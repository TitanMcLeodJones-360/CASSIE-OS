"""Only deterministic checks: do not need real Wi-Fi, a microphone, or Ollama."""
import os
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"app"))
import command_center
import server


@pytest.fixture
def node(tmp_path, monkeypatch):
    monkeypatch.delenv("CASSIE_HOTSPOT_INTERFACE", raising=False)
    store = server.Store(tmp_path)
    monitor = command_center.Monitor(store)
    try:
        yield monitor
    finally:
        monitor.stop.set()
        monitor.thread.join(3)


def test_integrity_flags_mismatch(node, monkeypatch):
    node.check_integrity()
    assert node.integrity["state"] == "ok"
    real = command_center.baseline
    monkeypatch.setattr(command_center, "baseline", lambda: {**real(), "server.py":"changed"})
    node.check_integrity()
    assert node.integrity["state"] == "critical"


def test_watch_requires_observation_and_persists_only_selected_addresses(node):
    mac = "aa:bb:cc:dd:ee:ff"
    assert not node.network()["configured"]
    with pytest.raises(ValueError):
        node.watch(mac, True)
    node.devices[mac] = dict(first_seen=100, last_seen=100, ip="10.77.0.9")
    assert node.network()["devices"][0]["state"] != "missing"
    node.watch(mac, True)
    assert node.network()["devices"][0]["state"] == "missing"
    assert json.loads(node.netpath.read_text()) == [mac]
    assert "10.77" not in node.netpath.read_text()


def test_quarantine_preserves_payload_but_rejects_links_and_path_escape(node):
    root = node.store.root
    inbox = root/"inbox"
    inbox.mkdir()
    (inbox/"example.bin").write_bytes(b"original fragment")
    (inbox/"link").symlink_to(root/"access.token")
    os.link(root/"access.token", inbox/"hard")
    for name in ("../access.token","link","hard"):
        with pytest.raises(ValueError):
            node.quarantine(name)
    result = node.quarantine("example.bin")
    isolated = root/"quarantine"/result["isolated"]
    assert isolated.read_bytes() == b"original fragment" and not (inbox/"example.bin").exists()
    assert (isolated.stat().st_mode & 0o777) == 0o400
    assert (root/"access.token").exists()
