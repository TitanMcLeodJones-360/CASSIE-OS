"""CASSIE's local web console and model gateway."""
import base64
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import threading
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError

from PIL import Image, UnidentifiedImageError
import dataset_search
import command_center
from observer import Observer
import speech

HOST, PORT = "127.0.0.1", 8787
ORIGIN = f"http://{HOST}:{PORT}"
ALLOWED_HOSTS = {f"{HOST}:{PORT}", f"localhost:{PORT}"}
MODEL_URL = "http://127.0.0.1:11438/api"
MODEL = "cassie:desktop"
HOME = Path(__file__).resolve().parent
SYSTEM = (HOME/"base_persona.txt").read_text().strip()
STATE = Path(os.environ.get("CASSIE_STATE_DIR","/var/lib/cassie-os"))
MAX_BODY = 1_650_000
MAX_TEXT = 4800
Image.MAX_IMAGE_PIXELS = 4_000_000
class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirects())
CHAT = threading.Lock()
TONES = {"adaptive":"Match the user's tone.","warm":"Warm and steady; acknowledge what the user actually said.",
         "technical":"Concise and precise; give checks and actionable details.",
         "casual":"Relaxed and conversational; keep judgments grounded."}
EXACT_REQUEST = re.compile(
    r"^(?:(?:hey[ ,]+)?cassie[,:]?\s+)?(?:(?:please|just|only|(?:can|could|would|will) you)\s+)*"
    r"(?:say|repeat(?:\s+after me)?)(?=\s|:|[“‘\"'])\s*", re.I
)
EXACT_MODIFIERS = re.compile(r"^(?:(?:only|exactly|just)(?=\s|:|[“‘\"'])\s*)+", re.I)
LINE_LABEL = re.compile(
    r"^(?:(?:this|the(?: following)?)\s+(?:line|sentence|phrase|word)(?=\s|:|[“‘\"'])\s*|"
    r"this\s*(?=[:“‘\"']))", re.I
)
SAY_GENERATIVE = re.compile(
    r"^(?:something|anything|why|whether|how|what you think|it again|that again|the same thing again|"
    r"(?:the|your) (?:last )?(?:answer|response|reply)|(?:a|an) (?:word|sentence|line|joke) (?:about|on))\b", re.I
)
RESEARCH_REQUEST = re.compile(
    r"^(?:(?:please|can you|could you|would you|i need you to)\s+)*"
    r"(?:research|investigate|look up|fact[- ]check|verify|find (?:me )?(?:credible |reliable )?sources|"
    r"do (?:some )?research)\b|\b(?:cite your sources|show your sources|explain your research process)\b", re.I
)
REMEMBER = re.compile(r"^(?:please\s+)?(?:remember(?:\s+(?:that|this)[:,]?\s+|[:,]\s*|\s+(?=(?:i|my|we|our)\b))|save\s+(?:this\s+)?(?:to\s+)?(?:your\s+)?memory[:,]?\s+)(.+)$", re.I | re.S)
RECALL = re.compile(r"^(?:what do you (?:remember(?: about me)?|know about me)|(?:tell me|show me) (?:my|your) (?:saved )?memories)[.!? ]*$", re.I)
CAMERA_QUESTION = re.compile(
    r"\b(?:look (?:at (?:this|me|my desk|the camera)|through the camera)|what (?:do|can) you see|"
    r"what are you seeing|what am i holding|describe (?:the|this|my) (?:room|scene|view|object)|"
    r"(?:camera|webcam) (?:see|feed|view))\b", re.I
)
RECALL_STOP = set("about again before cassie could from have just like more said tell that their them then there these thing this want were what when where which will with would your".split())


def time_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, root):
        self.root=root
        self.db=root/"cassie.sqlite3"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        p=root/"access.token"
        try:
            fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,"w") as f:
                f.write(secrets.token_urlsafe(32)+"\n")
        self.token=p.read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}",self.token):
            raise RuntimeError("Invalid CASSIE access token file.")
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS chat (
              id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL,
              created TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]', had_image INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS memory (
              id INTEGER PRIMARY KEY, note TEXT NOT NULL, created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile (
              id INTEGER PRIMARY KEY CHECK(id=1), tone TEXT NOT NULL, style TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dataset_catalog (
              id INTEGER PRIMARY KEY CHECK(id=1), snapshot_sha256 TEXT NOT NULL,
              source_url TEXT NOT NULL, source_revision TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS datasets (
              ordinal INTEGER PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
              summary TEXT NOT NULL, url TEXT NOT NULL,
              flagged INTEGER NOT NULL CHECK(flagged IN (0,1))
            );
            INSERT OR IGNORE INTO profile VALUES (1,'adaptive','');
            """)
        self.seed_catalog()

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=4)
        c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally:
            c.close()

    def chat(self, limit=60):
        with self.connect() as c:
            rows=c.execute("SELECT * FROM chat ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
        return [{**r,"sources":json.loads(r["sources"])} for r in reversed(rows)]

    def seed_catalog(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT snapshot_sha256 FROM dataset_catalog WHERE id=1").fetchone()
            try:
                data = dataset_search.CATALOG.read_bytes()
            except FileNotFoundError:
                if current:
                    return
                raise
            digest = hashlib.sha256(data).hexdigest()
            if current and current["snapshot_sha256"] == digest:
                return
            snapshot = json.loads(data)
            entries = dataset_search.catalog_entries(snapshot)
            if not entries:
                raise ValueError("The bundled dataset catalog has no valid entries.")
            c.execute("DELETE FROM datasets")
            c.executemany(
                "INSERT INTO datasets VALUES (?,?,?,?,?,?)",
                ((i, entry.category, entry.title, entry.summary, entry.url, entry.flagged)
                 for i, entry in enumerate(entries, 1)),
            )
            c.execute(
                "INSERT INTO dataset_catalog VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "snapshot_sha256=excluded.snapshot_sha256, source_url=excluded.source_url, "
                "source_revision=excluded.source_revision",
                (digest, snapshot["source"], snapshot["blob_sha"]),
            )

    def catalog(self):
        with self.connect() as c:
            rows = c.execute(
                "SELECT category,title,summary,url,flagged FROM datasets WHERE flagged=0 ORDER BY ordinal"
            ).fetchall()
        return tuple(dataset_search.Entry(*row[:4], bool(row[4])) for row in rows)

    def catalog_info(self):
        with self.connect() as c:
            info = c.execute("SELECT source_url,source_revision FROM dataset_catalog WHERE id=1").fetchone()
            total, flagged = c.execute("SELECT COUNT(*),COALESCE(SUM(flagged),0) FROM datasets").fetchone()
        return {**dict(info), "total": total, "flagged": flagged}

    def clear_chat(self):
        with self.connect() as c:
            c.execute("DELETE FROM chat")

    def profile(self):
        with self.connect() as c:
            return dict(c.execute("SELECT tone,style FROM profile WHERE id=1").fetchone())

    def memory(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM memory ORDER BY id DESC")]

    def save_memory(self, note):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM memory WHERE note=? COLLATE NOCASE", (note,)).fetchone():
                return False
            if c.execute("SELECT COUNT(*) FROM memory").fetchone()[0] >= 200:
                raise ValueError("My saved memory is full. Remove an old note in Knowledge Web first.")
            c.execute("INSERT INTO memory (note,created) VALUES (?,?)", (note, time_now()))
        return True

    def earlier_relevant(self, text, before):
        def terms(value):
            return {word for word in dataset_search.words(value) if len(word) >= 4} - RECALL_STOP

        query = terms(text)
        if len(query) < 2 or before is None:
            return []
        with self.connect() as c:
            rows = c.execute(
                "SELECT id,substr(content,1,320) AS content FROM chat "
                "WHERE role='user' AND id<? AND had_image=0 ORDER BY id DESC LIMIT 250",
                (before,),
            ).fetchall()
        matches = [(len(query & terms(row["content"])), row["id"], row["content"])
                   for row in rows if not REMEMBER.match(row["content"])]
        return [content for score, _, content in sorted(matches, reverse=True)[:2] if score >= 2]

    def record(self, text, reply, sources, had_image):
        now=time_now()
        with self.connect() as c:
            c.executemany("INSERT INTO chat (role,content,created,sources,had_image) VALUES (?,?,?,?,?)",
                [("user",text,now,"[]",bool(had_image)),("assistant",reply,now,json.dumps(sources),False)])
        return {"content":reply,"sources":sources,"created":now}


def required_text(value, limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ValueError(f"Enter text between 1 and {limit:,} characters.")
    return value.strip()


def decode_image(encoded):
    if encoded is None:
        return None
    if not isinstance(encoded,str) or len(encoded)>1_600_000:
        raise ValueError("Choose a smaller JPG or PNG image.")
    try:
        data=base64.b64decode(encoded,validate=True)
        with Image.open(BytesIO(data), formats=["JPEG","PNG","WEBP"]) as image:
            if image.width*image.height>4_000_000:
                raise ValueError("Image exceeds 4 megapixels.")
            image.thumbnail((768,768))
            out=BytesIO()
            image.convert("RGB").save(out,"JPEG",quality=85)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError):
        raise ValueError("Use a valid JPG, PNG or WebP image under 4 megapixels.") from None
    return base64.b64encode(out.getvalue()).decode("ascii")


class ModelError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


@contextmanager
def model_response(path, body, timeout):
    data=None if body is None else json.dumps(body).encode()
    req=Request(MODEL_URL+path,data=data,headers={"Content-Type":"application/json"})
    try:
        with OPENER.open(req,timeout=timeout) as resp:
            yield resp
    except HTTPError as exc:
        with exc:
            try:
                detail = json.loads(exc.read(2048)).get("error", "")
            except (ValueError, AttributeError):
                detail = ""
        suffix = " " + str(detail)[:400] if detail else ""
        raise ModelError(f"Ollama returned HTTP {exc.code}." + suffix, exc.code) from exc
    except TimeoutError as exc:
        raise ModelError("The local model timed out while generating a reply.") from exc
    except (URLError, OSError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise ModelError("The local model took too long to start answering.") from exc
        raise ModelError("Could not reach Ollama on this PC. Check cassie-os-model.service.") from exc


def request_model(path, body=None, timeout=180):
    with model_response(path, body, timeout) as response:
        return model_object(response.read(1_000_001))


def model_object(raw):
    try:
        obj = json.loads(raw) if len(raw) <= 1_000_000 else None
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        raise ModelError("Ollama returned an invalid response.")
    return obj


def installed_models():
    return {row.get("name") for row in request_model("/tags", timeout=4).get("models", [])
            if isinstance(row, dict)}


def fallback_model():
    available = installed_models()
    return next((model for model in ("qwen3.5:2b", "qwen3.5:4b") if model in available), None)


def chat_result(body, on_delta):
    if on_delta is None:
        return request_model("/chat", body)
    # Keep a final copy for the store while sending text to the console as it arrives.
    parts, size = [], 0
    with model_response("/chat", {**body, "stream": True}, 180) as response:
        while raw := response.readline(1_000_001):
            update = model_object(raw)
            if update.get("error"):
                raise ModelError(str(update["error"])[:400])
            delta = update.get("message", {}).get("content", "")
            if delta:
                size += len(delta)
                if size > 24_000:
                    raise ModelError("The local reply exceeded the response limit.")
                parts.append(delta)
                on_delta(delta)
            if update.get("done"):
                return {**update, "message": {"content": "".join(parts)}}
    raise ModelError("Ollama ended the connection before it finished the reply.")


def model_ready():
    try:
        return bool({MODEL, "qwen3.5:2b", "qwen3.5:4b"} & installed_models())
    except (RuntimeError,TypeError,AttributeError):
        return False


def system_status(state=None):
    try:
        load=round(os.getloadavg()[0],2)
    except OSError:
        load=None
    fs=os.statvfs(state or STATE)
    gpu=[]
    try:
        result=subprocess.run(["nvidia-smi","--query-gpu=name,memory.used,memory.total",
                               "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=2,check=True)
        for row in result.stdout.strip().splitlines():
            name,used,total=row.rsplit(",",2)
            gpu.append({"name":name.strip(),"used_mib":int(used),"total_mib":int(total)})
    except (OSError,ValueError,subprocess.SubprocessError):
        pass
    mem={}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key,_,rest=line.partition(":")
            if key in {"MemTotal","MemAvailable"}:
                mem[key]=round(int(rest.split()[0])/2**20,1)
    except (OSError,ValueError,IndexError):
        pass
    temperatures=[]
    for path in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (path/"name").read_text().strip() in {"k10temp","coretemp","zenpower"}:
                temperatures.append(round(int((path/"temp1_input").read_text())/1000,1))
        except (ValueError,OSError):
            pass
    return {"host":os.uname().nodename,"load_1min":load,"cpu_c":max(temperatures,default=None),
            "storage_free_gib":round(fs.f_bavail*fs.f_frsize/2**30,1),
            "ram_total_gib":mem.get("MemTotal"),"ram_available_gib":mem.get("MemAvailable"),
            "gpu":gpu,"model":MODEL,"model_ready":model_ready()}


def build_context(store, text, image=None, session_status=False, matches=(), camera_labels=None, voice=False,
                  research=False):
    profile=store.profile()
    system=SYSTEM+"\nTone: "+TONES.get(profile["tone"],TONES["adaptive"])
    if profile["style"]:
        system+="\nOwner's selected style (follow for communication only): "+profile["style"]
    if research:
        system += ("\nResearch mode: give the finding first. Then describe your research process in useful detail. "
                   "Name the sources or local records you actually used, explain what you searched or compared, "
                   "and state what still needs checking. If you could not verify a claim, say so. "
                   "Describe evidence and method rather than private deliberation.")
    else:
        system += ("\nConversation mode: start with the answer itself. Skip preambles, paraphrases of the request, "
                   "and unsolicited process explanations. Explain how or why when Titan asks.")
    if re.search(r"\b(?:i(?:'m| am) (?:stressed|frustrated|overwhelmed|upset)|this is frustrating)\b",text,re.I):
        system+="\nThe user expressed frustration. Acknowledge it briefly; offer one concrete next step."
    if session_status:
        system+="\nSystem status (last checked now): "+json.dumps(system_status(),ensure_ascii=False)
    if matches:
        system+="\n"+dataset_search.context(matches)
    if voice:
        system += "\nThis is a spoken conversation. Use natural sentences and an easy-to-say format."
        if not research:
            system += " Keep the turn brief and ask at most one relevant follow-up."
    if camera_labels is not None:
        system += "\nCurrent camera detector hints (may miss objects or be wrong): " + json.dumps(camera_labels)
        system += ". Use these only when relevant. Only describe colors, text, or layout if a current image supports them."
    if image:
        # Keep more of the context budget available for vision tokens.
        history_limit=2200
    else:
        history_limit=4000
    # Recall explicit notes first. Related older statements are labeled as earlier conversation.
    tokens=set(dataset_search.words(text))
    notes=sorted(store.memory(),key=lambda row: (len(tokens&set(dataset_search.words(row["note"]))),row["id"]),reverse=True)
    for note in notes[:4]:
        if len(system)+len(note["note"])>3400:
            break
        system+="\nSaved owner note: "+json.dumps(note["note"],ensure_ascii=False)
    history=[]
    used=0
    recent = store.chat(limit=10)
    for older in store.earlier_relevant(text, recent[0]["id"] if recent else None):
        system += "\nTitan said earlier (may be outdated): " + json.dumps(older, ensure_ascii=False)
    for row in reversed(recent):
        if used+len(row["content"])>history_limit:
            break
        entry={"role":row["role"],"content":row["content"]}
        if row["had_image"]: entry["content"]+=" [A previous image is no longer available.]"
        history.append(entry)
        used+=len(entry["content"])
    if history and history[-1]["role"]=="assistant":
        history.pop()
    current={"role":"user","content":text}
    if image: current["images"]=[image]
    return [{"role":"system","content":system},*reversed(history),current]


def exact_line(text):
    command = EXACT_REQUEST.match(text)
    if not command:
        return None
    payload = text[command.end():]
    line = EXACT_MODIFIERS.sub("", payload, count=1)
    line = LINE_LABEL.sub("", line, count=1)
    explicit = line != payload or line.startswith(":")
    line = line.removeprefix(":").strip()
    if not line:
        return None
    closer = {'"': '"', "'": "'", "“": "”", "‘": "’"}.get(line[0])
    if closer:
        end = line.rfind(closer, 1)
        if end != -1 and re.fullmatch(r"[\s,.!?]*(?:please[\s,.!?]*)?", line[end+1:], re.I):
            return line[1:end] if line[1:end].strip() else None
    if not explicit and (line.rstrip(".!? ").lower() in {"that", "this", "it", "again"} or SAY_GENERATIVE.match(line)):
        return None
    return line


def respond(store, data, on_delta=None, observer=None):
    text=required_text(data.get("text"),MAX_TEXT)
    line = exact_line(text)
    if line is not None:
        return {**store.record(text, line, [], False), "verbatim": True}
    if request := REMEMBER.fullmatch(text):
        note = required_text(request.group(1), 600)
        saved = store.save_memory(note)
        reply = "Got it. I’ll remember that." if saved else "I already have that saved."
        return {**store.record(text, reply, [], False), "memory_changed": True}
    if RECALL.fullmatch(text):
        notes = store.memory()
        reply = ("Here are your latest saved memories. " + " ".join(
            row["note"].rstrip(".!?") + "." for row in notes[:5]
        ) if notes else "You haven’t asked me to save anything yet. Tell me what you’d like me to remember.")
        return store.record(text, reply, [], False)
    image=decode_image(data.get("image"))
    voice = data.get("voice") is True
    use_camera = (data.get("use_camera") is True or bool(CAMERA_QUESTION.search(text)) or
                  (voice and text.lower().rstrip("?!. ") in ("what is this", "what's this", "whats this")))
    camera_labels = None
    camera_image = False
    if observer is not None:
        camera_state, labels, jpeg = observer.sight(use_camera and image is None)
        if camera_state == "live":
            camera_labels = labels
        if use_camera and image is None:
            if camera_state != "live":
                message = ("Turn on the always-on camera in Awareness and ask me to look again."
                           if camera_state == "off" else "I’m waiting for a live camera frame. Ask me to look again once the feed appears.")
                return store.record(text, message, [], False)
            if jpeg:
                image = base64.b64encode(jpeg).decode("ascii")
                camera_image = True
            else:
                reply = "I don’t have a fresh image yet."
                if labels:
                    reply += " The detector suggests " + ", ".join(dict.fromkeys(labels)) + "."
                return store.record(text, reply, [], False)
    context=data.get("include_status",False) is True
    lookup=dataset_search.prompt_for_lookup(store.chat(limit=6)+[{"role":"user","content":text}])
    matches=dataset_search.find(lookup, entries=store.catalog()) if lookup else []
    research = bool(lookup or RESEARCH_REQUEST.search(text))
    sources=[{"title":row.title,"url":row.url} for row in matches]
    if lookup and not matches and not image:
        return store.record(text,"I searched the local catalog’s dataset titles, categories, and descriptions. I didn’t find a match. Try a specific name, sensor, or data type.",[],False)
    if matches and dataset_search.COMMAND.search(text) and image is None:
        return store.record(text, dataset_reply(matches, lookup), sources, False)
    budget = 480 if research else 180 if voice else 400 if image else 320
    body={
        "model":MODEL,"stream":False,"think":False,"keep_alive":"5m",
        "options":{"num_ctx":4096,"num_predict":budget,"temperature":0.65},
        "messages":build_context(store,text,image,context,matches,camera_labels,voice,research),
    }
    emitted = False

    def emit(part):
        nonlocal emitted
        emitted = True
        on_delta(part)

    sink = emit if on_delta is not None else None
    try:
        result = chat_result(body, sink)
    except ModelError as error:
        if matches and not emitted and image is None:
            return store.record(text, dataset_reply(matches, lookup), sources, False)
        if camera_image and not emitted and re.search(r"does not support (?:images|vision)|no (?:vision|multimodal) projector|model does not support image", str(error), re.I):
            reply = "My local model couldn’t read this camera image."
            if camera_labels:
                reply += " The object detector suggests " + ", ".join(dict.fromkeys(camera_labels)) + "."
            return store.record(text, reply, sources, False)
        if error.status != 404:
            raise
        model = fallback_model()
        if not model:
            raise ModelError("The CASSIE profile and its Qwen base model are missing. Check the local model setup.") from error
        result = chat_result({**body, "model": model}, sink)
    reply=result.get("message",{}).get("content","").strip()
    if not result.get("done") or not reply:
        raise RuntimeError("The local model returned an incomplete answer. Try a shorter prompt.")
    if result.get("done_reason")=="length":
        reply+="\n\n[Response limit reached.]"
    result = store.record(text,reply,sources,image is not None)
    if camera_image:
        result["used_camera"] = True
    return result


def dataset_reply(matches, query):
    items = ["• " + entry.title + (" — " + entry.summary if entry.summary else "") for entry in matches]
    query = dataset_search.safe_line(dataset_search.COMMAND.sub("", query).strip(), 160)
    method = ("I searched the local catalog for “" + query + "” and ranked matches by title, category, and description. "
              "The results are catalog listings. Check the source links for the files and access terms.")
    return "Here’s what I found in the local dataset database.\n\n" + "\n".join(items) + "\n\n" + method


class App(ThreadingHTTPServer):
    daemon_threads=True

    def __init__(self, address, store):
        self.store=store
        super().__init__(address, Handler)
        self.monitor=command_center.Monitor(store)
        self.observer=Observer(store.root)

    def server_close(self):
        self.observer.close()
        self.monitor.stop.set()
        self.monitor.thread.join(timeout=5)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.0"

    def log_message(self, format, *args):
        # Do not log user content, filenames, keys or URLs.
        pass

    def reply(self, data, code=200, mime="application/json; charset=utf-8"):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.headers_for(code, mime, len(body))
        self.wfile.write(body)

    def headers_for(self, code, mime, length=None):
        self.send_response(code)
        self.send_header("Content-Type",mime)
        if length is not None:
            self.send_header("Content-Length",str(length))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Permissions-Policy","camera=(self), microphone=(self), geolocation=(), on-device-speech-recognition=(self)")
        self.send_header("Content-Security-Policy","default-src 'self'; connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()

    def camera_stream(self):
        observer = self.server.observer
        with observer.condition:
            revision, enabled = observer.revision, observer.enabled
        if not enabled:
            self.reply({"error": "Always-on camera is off."}, 409)
            return
        self.headers_for(200, "application/octet-stream")
        self.connection.settimeout(6)
        previous = None
        try:
            while frame := observer.next_frame(previous, revision):
                previous, jpeg = frame
                self.wfile.write(len(jpeg).to_bytes(4, "big") + jpeg)
        except OSError:
            pass

    def chat_stream(self, store, data):
        self.headers_for(200, "application/x-ndjson; charset=utf-8")

        def send(update):
            self.wfile.write(json.dumps(update, ensure_ascii=False).encode() + b"\n")

        try:
            send({"reply": respond(store, data, lambda part: send({"delta": part}), self.server.observer)})
        except (RuntimeError, ValueError) as error:
            send({"error": str(error)})
        except sqlite3.Error:
            send({"error": "CASSIE storage is busy or unavailable."})

    def gate(self, auth=True):
        host=self.headers.get("Host","")
        if host not in ALLOWED_HOSTS:
            self.reply({"error":"Invalid app address."},403)
            return False
        origin=self.headers.get("Origin")
        if origin is not None and origin!=f"http://{host}":
            self.reply({"error":"Open the console directly from its local address."},403)
            return False
        header=self.headers.get("Authorization","")
        if auth and (not header.isascii() or not compare_digest(header,"Bearer "+self.server.store.token)):
            self.reply({"error":"Enter your CASSIE access key."},401)
            return False
        return True

    def do_GET(self):
        path=self.path
        static={"/":("index.html","text/html; charset=utf-8"),"/style.css":("style.css","text/css"),
                "/app.js":("app.js","text/javascript"),"/insignia.webp":("insignia.webp","image/webp"),
                "/mic-worklet.js":("mic-worklet.js","text/javascript")}
        if path in static:
            if self.gate(False):
                name,mime=static[path]
                self.reply((HOME/"static"/name).read_bytes(),mime=mime)
            return
        if path=="/api/health":
            if self.gate(False): self.reply({"service":"cassie-os"})
            return
        if not self.gate(): return
        store=self.server.store
        if path=="/api/session":
            self.reply({"chat":store.chat(),"notes":store.memory(),"profile":store.profile()})
        elif path=="/api/command":
            self.reply(self.server.monitor.status(system_status(store.root)))
        elif path=="/api/camera":
            self.reply(self.server.observer.snapshot())
        elif path=="/api/camera/stream":
            self.camera_stream()
        elif path=="/api/speech":
            self.reply({"available": speech.available()})
        elif path=="/api/inbox":
            self.reply({"files":self.server.monitor.inbox()})
        elif path=="/api/catalog":
            self.reply({"entries":[[r.category,r.title,r.summary,r.url] for r in store.catalog()],
                        "catalog":store.catalog_info()})
        elif path=="/api/status":
            self.reply(system_status())
        elif path=="/api/export":
            self.reply({"chat":store.chat(limit=-1),"memory":store.memory(),"profile":store.profile(),"exported":time_now()})
        else: self.reply({"error":"Not found."},404)

    def do_POST(self):
        if not self.gate(): return
        store=self.server.store
        try:
            if self.headers.get_content_type()!="application/json":
                self.reply({"error":"Use JSON."},415)
                return
            length=int(self.headers.get("Content-Length","0"))
            if not 0<length<=MAX_BODY:
                self.reply({"error":"Message or attachment exceeds the size limit."},413)
                return
            self.connection.settimeout(8)
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError("Expected a JSON object.")
            if self.path in ("/api/chat","/api/chat/clear"):
                if not CHAT.acquire(blocking=False):
                    self.reply({"error":"CASSIE is already answering. Try again when it finishes."},409)
                    return
                try:
                    if self.path.endswith("/clear"):
                        store.clear_chat()
                        self.reply({"ok":True})
                    elif data.get("stream") is True:
                        self.chat_stream(store, data)
                    else:
                        try:
                            self.reply(respond(store,data,observer=self.server.observer))
                        except RuntimeError as e:
                            self.reply({"error":str(e)},503)
                finally:
                    CHAT.release()
            elif self.path=="/api/watch":
                self.server.monitor.watch(data.get("mac"),data.get("watched"))
                self.reply({"ok":True})
            elif self.path=="/api/quarantine":
                self.reply(self.server.monitor.quarantine(data.get("name")))
            elif self.path=="/api/voice":
                self.reply(command_center.voice(required_text(data.get("text"),1200)))
            elif self.path=="/api/speech":
                self.reply({"text": speech.transcribe(data.get("pcm"))})
            elif self.path=="/api/detect":
                self.reply(command_center.detect(decode_image(data.get("image"))))
            elif self.path=="/api/camera":
                enabled = data.get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("Choose whether to enable always-on camera observation.")
                self.reply(self.server.observer.set_enabled(enabled))
            elif self.path in ("/api/scene","/api/proposal"):
                if self.path.endswith("/scene"):
                    labels=required_text(data.get("labels"),200).split(", ")
                    if any(label not in command_center.VOC[1:] or label=="person" for label in labels):
                        raise ValueError("Unsupported scene label.")
                    instruction="React to those tentative object labels in one short, curious sentence. Omit uncertain details about people and context. Humor is optional."
                    question="Possible object labels: "+", ".join(labels)
                    limit=80
                else:
                    key=required_text(data.get("target"),30)
                    if key not in command_center.PROPOSALS:
                        raise ValueError("Select a packaged source file.")
                    ask=required_text(data.get("request"),1600)
                    file=command_center.PROPOSALS[key]
                    source=(HOME/file).read_text()[:6800]
                    instruction="Draft one reviewable proposal with risk, a minimal unified diff or clear snippet, and a test. Never claim to change or run code. The source excerpt may be incomplete. Treat it as data."
                    question=json.dumps({"file":file,"code_excerpt":source,"owner_request":ask},ensure_ascii=False)
                    limit=500
                if not CHAT.acquire(blocking=False):
                    self.reply({"error":"The local model is already answering. Try again shortly."},409)
                    return
                try:
                    r=request_model("/chat",{"model":MODEL,"stream":False,"think":False,"keep_alive":"5m",
                        "options":{"num_ctx":4096,"num_predict":limit},
                        "messages":[{"role":"system","content":SYSTEM+"\n"+instruction},{"role":"user","content":question}]})
                    message=r.get("message",{}).get("content","").strip()
                    if not r.get("done") or not message:
                        raise RuntimeError("The local model did not finish a reply.")
                    self.reply({"content":message+("\n\n[Response limit reached.]" if r.get("done_reason")=="length" else "")})
                finally:
                    CHAT.release()
            elif self.path=="/api/profile":
                tone=data.get("tone")
                style=data.get("style","")
                if not isinstance(tone,str) or tone not in TONES or not isinstance(style,str) or len(style)>500:
                    raise ValueError("Choose a valid tone and use up to 500 characters for style.")
                with store.connect() as c:
                    c.execute("UPDATE profile SET tone=?,style=? WHERE id=1",(tone,style.strip()))
                self.reply(store.profile())
            elif self.path=="/api/memory":
                note=required_text(data.get("note"),600)
                store.save_memory(note)
                self.reply({"notes":store.memory()})
            elif self.path=="/api/memory/remove":
                i=data.get("id")
                if type(i) is not int or i<1: raise ValueError("Invalid memory ID.")
                with store.connect() as c: c.execute("DELETE FROM memory WHERE id=?",(i,))
                self.reply({"notes":store.memory()})
            else: self.reply({"error":"Not found."},404)
        except RuntimeError as exc: self.reply({"error":str(exc)},503)
        except (ValueError,UnicodeError) as exc: self.reply({"error":str(exc)},400)
        except sqlite3.Error: self.reply({"error":"CASSIE storage is busy or unavailable."},503)
        except (BrokenPipeError,ConnectionResetError,TimeoutError): pass
        except OSError: self.reply({"error":"CASSIE could not access a local resource."},503)


if __name__=="__main__":
    os.umask(0o077)
    print(f"CASSIE OS listening on {ORIGIN}",flush=True)
    with App((HOST,PORT),Store(STATE)) as server:
        server.serve_forever()
