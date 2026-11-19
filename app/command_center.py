"""Local telemetry, bounded optional sensors, and in-app defensive containment."""
from functools import lru_cache
from io import BytesIO
from itertools import islice
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import threading
import time
import uuid

from PIL import Image

ROOT = Path(__file__).resolve().parent
MAC = re.compile(r"(?i)[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
IFACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}")
ASSETS = ("command_center.py", "server.py", "observer.py", "speech.py", "base_persona.txt", "static/app.js", "static/mic-worklet.js", "static/style.css", "static/index.html", "static/insignia.webp", "dataset_catalog.json", "dataset_search.py")
VOC = ("background", "airplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat",
       "chair", "cow", "dining table", "dog", "horse", "motorcycle", "person",
       "potted plant", "sheep", "sofa", "train", "TV monitor")
PROPOSALS = {"persona": "base_persona.txt", "dashboard": "static/style.css", "module": "command_center.py"}
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,79}")


def baseline():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ASSETS}


class Monitor:
    """Scheduled, read-only probes; no external network requests."""
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.integrity = {"state": "unknown", "detail": "The first integrity check is pending."}
        self.interface = os.environ.get("CASSIE_HOTSPOT_INTERFACE", "")
        self.devices = {}
        self.watched = set()
        self.netpath = store.root/"watched-devices.json"
        try:
            if self.netpath.stat().st_size <= 16384:
                values = json.loads(self.netpath.read_text())
                if isinstance(values, list):
                    self.watched = {x for x in values if isinstance(x, str) and MAC.fullmatch(x)}
        except (OSError, ValueError):
            pass
        self.network_error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.worker, daemon=True, name="sentinel")
        self.thread.start()

    def worker(self):
        ticks = 0
        while not self.stop.is_set():
            if ticks % 6 == 0:
                self.check_integrity()
            self.scan_neighbors()
            ticks += 1
            self.stop.wait(20)

    def check_integrity(self):
        try:
            expected = json.loads((ROOT/"integrity.json").read_text())
            if expected != baseline():
                result = {"state":"critical","detail":"Installed command files differ from the packaged baseline. Investigate before restoring or replacing them."}
            else:
                with self.store.connect() as c:
                    expires = time.monotonic()+2
                    c.set_progress_handler(lambda: int(time.monotonic()>expires), 1000)
                    row = c.execute("PRAGMA quick_check(1)").fetchone()
                result = ({"state":"ok","detail":"Database quick check and packaged file hashes passed."}
                          if row and row[0]=="ok" else
                          {"state":"critical","detail":"The local database reported an integrity problem. Stop writes and examine a copy. This check does not establish whether a breach occurred."})
        except sqlite3.Error as e:
            failure = getattr(e, "sqlite_errorcode", 0) & 255 in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
            result = {"state":"critical" if failure else "unknown",
                      "detail":"Database corruption was reported; investigate a copy." if failure else "The database check could not finish. Review the service log."}
        except (ValueError, OSError):
            result = {"state":"unknown","detail":"The installed integrity baseline is missing or could not be read."}
        with self.lock:
            self.integrity = result

    def scan_neighbors(self):
        if not self.interface:
            return
        try:
            if not IFACE.fullmatch(self.interface) or not (Path("/sys/class/net")/self.interface).exists():
                raise ValueError()
            raw = subprocess.run(["ip","-j","neigh","show","dev",self.interface], capture_output=True,
                                 text=True, timeout=3, check=True).stdout
            observations = []
            for row in json.loads(raw)[:600]:
                addr = row.get("lladdr", "").lower()
                if not MAC.fullmatch(addr) or "REACHABLE" not in row.get("state", []):
                    continue
                ip = ipaddress.ip_address(row["dst"])
                if ip.is_multicast or ip.is_unspecified:
                    continue
                observations.append((addr, str(ip)))
        except (OSError, TypeError, KeyError, ValueError, subprocess.SubprocessError):
            with self.lock:
                self.network_error = "Could not read the configured CASSIE-NET interface."
            return
        now = int(time.time())
        with self.lock:
            self.network_error = None
            for mac, ip in observations:
                if len(self.devices)>=256 and mac not in self.devices:
                    continue
                if mac not in self.devices or now-self.devices[mac]["last_seen"]>604800:
                    self.devices[mac] = {"ip":ip,"first_seen":now,"last_seen":now}
                self.devices[mac].update(ip=ip,last_seen=now)

    def network(self):
        now = int(time.time())
        with self.lock:
            entries = []
            for mac in self.watched | self.devices.keys():
                row = self.devices.get(mac, {})
                first, last = row.get("first_seen"), row.get("last_seen")
                watched = mac in self.watched
                state = ("awaiting observation" if last is None else "missing" if watched and now-last>900
                         else "new" if now-first<300 else "seen" if now-last<180 else "last seen")
                entries.append({"mac":mac,"ip":row.get("ip",mac),"state":state,"watched":watched,"last_seen":last})
            entries.sort(key=lambda x: (not x["watched"], -(x["last_seen"] or 0), x["mac"]))
            return {"configured":bool(self.interface),"error":self.network_error,"devices":entries}

    def watch(self, mac, watched):
        if not isinstance(mac, str) or not MAC.fullmatch(mac) or type(watched) is not bool:
            raise ValueError("Invalid device selection.")
        with self.lock:
            if mac not in self.devices and mac not in self.watched:
                raise ValueError("That device has not been observed.")
            changed = (self.watched|{mac}) if watched else (self.watched-{mac})
            temp = self.netpath.with_suffix(".tmp")
            temp.write_text(json.dumps(sorted(changed)))
            os.chmod(temp,0o600)
            temp.replace(self.netpath)
            self.watched = changed

    def status(self, machine):
        path = Path(os.environ.get("CASSIE_BULK_MOUNT", "/srv/cassie-data"))
        bulk = {"mounted":False}
        if path.is_absolute() and path != Path("/") and path.is_mount():
            try:
                fs = path.statvfs()
                bulk = {"mounted":True,"free_gib":round(fs.f_bavail*fs.f_frsize/2**30,1)}
            except OSError:
                pass
        with self.lock:
            result = self.integrity.copy()
        return {"machine":machine,"bulk":bulk,"integrity":result,"network":self.network(),
                "voice":shutil.which("espeak-ng") is not None}

    def quarantine(self, name):
        if not isinstance(name,str) or not SAFE_NAME.fullmatch(name):
            raise ValueError("Choose an ordinary file from the CASSIE inbox.")
        inbox = self.store.root/"inbox"
        dest = self.store.root/"quarantine"
        with self.lock:
            dest.mkdir(mode=0o700,exist_ok=True)
            flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY
            try:
                first = os.open(inbox,flags)
            except FileNotFoundError:
                raise ValueError("The app inbox has not been provisioned.") from None
            try:
                second = os.open(dest,flags)
                try:
                    info = os.stat(name,dir_fd=first,follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError("Only ordinary, single-link inbox files can be isolated.")
                    fd = os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=first)
                    try:
                        before = os.fstat(fd)
                        if (info.st_ino,info.st_dev)!=(before.st_ino,before.st_dev) or before.st_nlink!=1:
                            raise ValueError("The inbox file changed during inspection.")
                        os.fchmod(fd,0o400)
                        item = uuid.uuid4().hex+".isolated"
                        os.rename(name,item,src_dir_fd=first,dst_dir_fd=second)
                        moved = os.stat(item,dir_fd=second,follow_symlinks=False)
                        if (moved.st_ino,moved.st_dev)!=(before.st_ino,before.st_dev):
                            raise ValueError("The inbox entry changed during the move. Inspect quarantine locally.")
                    finally:
                        os.close(fd)
                except FileNotFoundError:
                    raise ValueError("That file is no longer in the app inbox.") from None
                finally:
                    os.close(second)
            finally:
                os.close(first)
        return {"isolated":item}

    def inbox(self):
        try:
            with os.scandir(self.store.root/"inbox") as paths:
                return [p.name for p in islice(paths,128)
                        if p.is_file(follow_symlinks=False) and SAFE_NAME.fullmatch(p.name)]
        except OSError:
            return []


def voice(text):
    try:
        r = subprocess.run(["espeak-ng","-v","en-us+f3","-s","168","--stdout","--stdin"],
                           input=text.encode(),capture_output=True,timeout=10,check=True)
        if not r.stdout.startswith(b"RIFF") or len(r.stdout)>4_000_000:
            raise ValueError("The speech sample was too long.")
        return {"wav":base64.b64encode(r.stdout).decode("ascii")}
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Local voice unavailable. Install eSpeak NG on TitanGame.") from None


VISION_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def load_detector():
    import cv2
    directory = Path("/opt/cassie-os/vision")
    try:
        net = cv2.dnn.readNetFromCaffe(str(directory/"deploy.prototxt"), str(directory/"model.caffemodel"))
    except cv2.error:
        raise RuntimeError("The local detector could not load. Run the camera update again.") from None
    return cv2, net


def detect(jpeg):
    if jpeg is None:
        raise ValueError("Provide one camera frame.")
    with Image.open(BytesIO(base64.b64decode(jpeg))) as image:
        pixels = image.convert("RGB")
    try:
        import numpy as np
    except ImportError:
        raise RuntimeError("Install the local OpenCV detector to outline objects.") from None
    return {"boxes": detect_frame(np.asarray(pixels)[:, :, ::-1].copy())}


def detect_frame(frame):
    """Find objects in an OpenCV BGR frame."""
    if not VISION_LOCK.acquire(blocking=False):
        return []
    try:
        cv2, net = load_detector()
        net.setInput(cv2.dnn.blobFromImage(frame, 1/127.5, (300,300), (127.5,127.5,127.5)))
        predictions = net.forward()
        boxes = []
        for _, cls, score, *points in predictions[0,0]:
            i = int(cls)
            if not 0<i<len(VOC) or not .58<float(score)<=1:
                continue
            coords = [round(max(0,min(1,float(v))),4) for v in points]
            if coords[0]>=coords[2] or coords[1]>=coords[3]:
                continue
            boxes.append({"label":VOC[i],"score":round(float(score),3),"rect":coords})
        return boxes[:20]
    except ImportError:
        raise RuntimeError("Camera preview works. Install the optional OpenCV detector to outline objects.") from None
    except Exception as e:
        if type(e).__module__.startswith("cv2"):
            raise RuntimeError("Object detector files are missing or invalid. See the Command Center README.") from None
        raise
    finally:
        VISION_LOCK.release()
