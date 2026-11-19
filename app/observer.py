"""Sample TitanGame's camera while its owner has enabled continuous observation."""
import os
from pathlib import Path
import stat
import threading
import time

from command_center import detect_frame


FRAME_INTERVAL = 1 / 18
DETECT_INTERVAL = 0.19
BOX_MAX_AGE_NS = 1_000_000_000
RETRY_INTERVAL = 4
FRAME_TTL_NS = 3_000_000_000
EYE_SAMPLE_NS = 600_000_000


def camera_devices():
    configured = os.environ.get("CASSIE_CAMERA_DEVICE")
    if configured:
        devices = [Path(configured)]
    else:
        devices = sorted(Path("/dev").glob("video[0-9]*"),
                         key=lambda device: (len(device.name), device.name))
    for device in devices:
        try:
            if stat.S_ISCHR(device.stat().st_mode):
                yield str(device)
        except OSError:
            continue


def outlined_jpeg(cv2, frame, boxes):
    height, width = frame.shape[:2]
    for box in boxes:
        x, y, right, bottom = (round(value * (width - 1 if index % 2 == 0 else height - 1))
                               for index, value in enumerate(box["rect"]))
        cv2.rectangle(frame, (x, y), (right, bottom), (255, 202, 93), 2)
        title = f'{box["label"]} {box["score"]:.0%}'
        text_y = max(13, y - 5)
        (text_width, text_height), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, .42, 1)
        text_x = min(x, max(0, width - text_width - 7))
        cv2.rectangle(frame, (text_x, text_y - text_height - 3),
                      (text_x + text_width + 6, text_y + 3), (26, 18, 10), -1)
        cv2.putText(frame, title, (text_x + 3, text_y), cv2.FONT_HERSHEY_SIMPLEX,
                    .42, (245, 233, 204), 1, cv2.LINE_AA)
    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
    if not success:
        raise RuntimeError("Could not read a preview from the camera. Retrying.")
    return encoded.tobytes()


def prepare_tracks(cv2, gray, boxes):
    import numpy as np

    height, width = gray.shape
    features = []
    for box in boxes:
        x, y, right, bottom = (int(v * (width if i % 2 == 0 else height))
                               for i, v in enumerate(box["rect"]))
        roi = gray[y:bottom, x:right]
        corners = (cv2.goodFeaturesToTrack(roi, 10, .06, 4)
                   if min(roi.shape) >= 7 else None)
        if corners is not None:
            corners += np.array([x, y], dtype=np.float32)
        features.append(corners)
    return features


def follow_tracks(cv2, reference, gray, boxes, features):
    import numpy as np

    groups = [points for points in features if points is not None]
    if not groups:
        return boxes
    height, width = gray.shape
    if reference.shape != gray.shape:
        return []
    starts = np.concatenate(groups)
    ends, valid, _ = cv2.calcOpticalFlowPyrLK(reference, gray, starts, None,
                                             winSize=(15, 15), maxLevel=2)
    if ends is None or valid is None:
        return boxes
    moves = (ends - starts).reshape(-1, 2)
    valid = valid.ravel().astype(bool) & np.isfinite(moves).all(axis=1)
    followed, offset = [], 0
    for box, points in zip(boxes, features):
        count = 0 if points is None else len(points)
        indices = slice(offset, offset + count)
        offset += count
        if not count:
            followed.append(box)
            continue
        trusted = moves[indices][valid[indices]]
        if not len(trusted):
            continue
        dx, dy = np.median(trusted, axis=0) / [width, height]
        if max(abs(dx), abs(dy)) > .33:
            continue
        rect = [max(0, min(1, value + (dy if index % 2 else dx)))
                for index, value in enumerate(box["rect"])]
        if rect[0] < rect[2] and rect[1] < rect[3]:
            followed.append({**box, "rect": rect})
    return followed


class Observer:
    def __init__(self, state):
        self.flag = state / "always-camera.enabled"
        self.enabled = self.flag.is_file()
        self.closed = False
        self.revision = 0
        self.condition = threading.Condition()
        self.detail = "Starting the camera." if self.enabled else "Always-on camera is off."
        self.sample = None
        self.frame = None
        self.eye = None
        self.pending = None
        self.detected = None
        self.detector_error = ""
        self.detector = threading.Thread(target=self.infer, daemon=True, name="camera-detector")
        self.detector.start()
        self.thread = threading.Thread(target=self.run, daemon=True, name="camera-observer")
        self.thread.start()

    def snapshot(self):
        with self.condition:
            sample, detail = self.sample, self.detail
            if sample and time.monotonic_ns() - int(sample["id"]) > FRAME_TTL_NS:
                sample, detail = None, "Waiting for a fresh camera frame."
            return {"enabled": self.enabled, "detail": detail, "sample": sample}

    def sight(self, include_image=False):
        with self.condition:
            state = self.snapshot()
            if not state["enabled"]:
                return "off", [], None
            if not state["sample"]:
                return "waiting", [], None
            image = None
            if include_image and self.eye and time.monotonic_ns() - self.eye[0] <= FRAME_TTL_NS:
                image = self.eye[1]
            labels = [box["label"] for box in state["sample"]["boxes"]]
            return "live", labels, image

    def set_enabled(self, enabled):
        with self.condition:
            if enabled != self.enabled:
                if enabled:
                    self.flag.touch(mode=0o600)
                else:
                    self.flag.unlink(missing_ok=True)
                self.enabled = enabled
                self.revision += 1
                self.sample = self.frame = self.pending = self.detected = None
                self.eye = None
                self.detector_error = ""
                self.detail = "Starting the camera." if enabled else "Always-on camera is off."
                self.condition.notify_all()
            return self.snapshot()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join(timeout=2)
        self.detector.join(timeout=2)

    def waiting(self, revision, delay=0):
        with self.condition:
            return self.condition.wait_for(lambda: self.closed or self.revision != revision,
                                           timeout=delay)

    def next_frame(self, previous, revision):
        with self.condition:
            self.condition.wait_for(
                lambda: self.closed or self.revision != revision or
                        (self.frame is not None and self.frame[0] != previous),
                timeout=5,
            )
            if self.closed or self.revision != revision or not self.enabled:
                return None
            return self.frame if self.frame and self.frame[0] != previous else (previous, b"")

    def publish(self, revision, detail, sample=None, jpeg=None, eye=None):
        with self.condition:
            if self.revision == revision and not self.closed:
                self.detail = detail
                self.sample = sample
                self.frame = (sample["id"], jpeg) if jpeg is not None else None
                if sample is None or eye is not None:
                    self.eye = eye
                self.condition.notify_all()

    def infer(self):
        previous = None
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or
                                        (self.pending is not None and self.pending[1] != previous))
                if self.closed:
                    return
                revision, previous, cv2, frame, gray = self.pending
            try:
                boxes = detect_frame(frame)
                result = (revision, previous, gray, boxes, prepare_tracks(cv2, gray, boxes))
                error = ""
            except (ImportError, RuntimeError, cv2.error):
                result = None
                error = "Video is live. Run the camera update to restore object detection."
            with self.condition:
                if revision == self.revision:
                    self.detected = result
                    self.detector_error = error
            self.waiting(revision, DETECT_INTERVAL if not error else RETRY_INTERVAL)

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.enabled or self.closed)
                if self.closed:
                    return
                revision = self.revision
            try:
                self.capture(revision)
            except (ImportError, OSError):
                self.publish(revision, "Install the local vision detector to start observation.")
            except RuntimeError as error:
                self.publish(revision, str(error))
            self.waiting(revision, RETRY_INTERVAL)

    def capture(self, revision):
        import cv2
        cv2.setNumThreads(2)
        for device in camera_devices():
            if self.waiting(revision):
                return
            capture = cv2.VideoCapture()
            try:
                if not capture.open(device, cv2.CAP_V4L2):
                    continue
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                capture.set(cv2.CAP_PROP_FPS, 30)
                last_eye = 0
                while not self.waiting(revision):
                    started = time.monotonic()
                    ok, frame = capture.read()
                    if not ok:
                        break
                    height, width = frame.shape[:2]
                    longest = max(width, height)
                    if longest > 640:
                        size = (max(1, round(width * 640 / longest)), max(1, round(height * 640 / longest)))
                        frame = cv2.resize(frame, size,
                                           interpolation=cv2.INTER_AREA)
                    stamp = time.monotonic_ns()
                    gray = cv2.cvtColor(cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2GRAY)
                    with self.condition:
                        if revision != self.revision or self.closed:
                            break
                        self.pending = (revision, stamp, cv2, frame.copy(), gray)
                        detection, error = self.detected, self.detector_error
                        self.condition.notify_all()
                    boxes = []
                    if detection and stamp - detection[1] <= BOX_MAX_AGE_NS:
                        _, _, reference, recent, features = detection
                        boxes = follow_tracks(cv2, reference, gray, recent, features)
                    eye = None
                    if stamp - last_eye >= EYE_SAMPLE_NS:
                        # Keep a clean frame for the model, independently of the annotated display.
                        eye = (stamp, outlined_jpeg(cv2, frame, []))
                        last_eye = stamp
                    preview = eye[1] if eye and not boxes else outlined_jpeg(cv2, frame, boxes)
                    self.publish(revision, error or "Local camera is live.",
                                 {"id": str(stamp), "boxes": boxes}, preview, eye)
                    self.waiting(revision, max(0, FRAME_INTERVAL - (time.monotonic() - started)))
            except cv2.error as error:
                raise RuntimeError("Camera input encountered a problem. Retrying.") from error
            finally:
                capture.release()
        if not self.waiting(revision):
            self.publish(revision, "Waiting for a camera. Plug it in or close other apps using it.")
