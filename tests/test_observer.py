from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from observer import Observer


def test_observation_resumes_and_discards_frames_when_stopped(tmp_path, monkeypatch):
    live = threading.Event()
    released = threading.Event()

    def capture(observer, revision):
        observer.publish(revision, "Camera is observing.", {
            "id": str(time.monotonic_ns()), "boxes": [],
        }, b"test frame", (time.monotonic_ns(), b"raw frame"))
        live.set()
        observer.waiting(revision, 3)
        released.set()

    monkeypatch.setattr(Observer, "capture", capture)
    observer = Observer(tmp_path)
    try:
        assert not observer.snapshot()["enabled"]
        observer.set_enabled(True)
        assert live.wait(2)
        assert observer.next_frame(None, observer.revision)[1] == b"test frame"
        assert "jpeg" not in observer.snapshot()["sample"]
        assert observer.sight() == ("live", [], None)
        assert observer.sight(True) == ("live", [], b"raw frame")
        assert [file.name for file in tmp_path.iterdir()] == ["always-camera.enabled"]
    finally:
        observer.close()
    assert released.is_set()

    live.clear()
    released.clear()
    observer = Observer(tmp_path)
    try:
        assert live.wait(2)
        assert observer.snapshot()["enabled"]
        stopped = observer.set_enabled(False)
        assert not stopped["enabled"]
        assert stopped["sample"] is None
        assert observer.sight(True) == ("off", [], None)
        assert released.wait(2)
        assert observer.next_frame(None, observer.revision - 1) is None
        assert not list(tmp_path.iterdir())
    finally:
        observer.close()
