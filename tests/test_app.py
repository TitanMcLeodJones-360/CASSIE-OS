import base64
from contextlib import contextmanager
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import sys
from threading import Thread

from PIL import Image
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
import server


@pytest.fixture
def instance(tmp_path,monkeypatch):
    monkeypatch.setattr(server,"STATE",tmp_path)
    outbound=[]
    def fake(path,body=None,timeout=180):
        outbound.append((path,body))
        if path=="/tags":
            return {"models":[{"name":server.MODEL}]}
        return {"done":True,"message":{"content":"A local answer."}}
    monkeypatch.setattr(server,"request_model",fake)
    store=server.Store(tmp_path)
    app=server.App(("127.0.0.1",0),store)
    worker=Thread(target=app.serve_forever,kwargs={"poll_interval":.01})
    worker.start()
    host=f"127.0.0.1:{app.server_port}"
    monkeypatch.setattr(server,"ALLOWED_HOSTS",{host})
    def call(path,payload=None,*,auth=True,origin=None,host_override=None):
        headers={"Host":host_override or host}
        if auth:headers["Authorization"]="Bearer "+store.token
        if origin is not None:headers["Origin"]=origin
        if payload is not None:headers["Content-Type"]="application/json"
        connection=HTTPConnection("127.0.0.1",app.server_port,timeout=10)
        try:
            connection.request("GET" if payload is None else "POST",path,
                               None if payload is None else json.dumps(payload),headers)
            res=connection.getresponse()
            raw=res.read()
            return res.status,json.loads(raw) if res.getheader("Content-Type").startswith("application/json") else raw
        finally:connection.close()
    call.app=app
    try:yield call,outbound,tmp_path
    finally:
        app.shutdown();worker.join();app.server_close()


def test_session_access_and_browser_origin(instance):
    call,outbound,_=instance
    assert call("/")[0]==200
    assert call("/api/session",auth=False)[0]==401
    assert call("/api/chat",{"text":"Hello"},origin="https://example.org")[0]==403
    assert call("/api/session",host_override="another.example")[0]==403
    assert not outbound


def test_network_activity_requires_auth_and_an_observed_device(instance, monkeypatch):
    call, _, path = instance
    import network_activity
    activity = network_activity.Activity(path, "wlp10s0")
    mac = "02:11:22:33:44:55"
    assert call("/api/network/activity", auth=False)[0] == 401
    assert call("/api/network/activity", {"action":"track","mac":mac,"tracked":True}, auth=False)[0] == 401
    assert call("/api/network/activity", {"action":"track","mac":mac,"tracked":True})[0] == 400
    call.app.monitor.devices[mac]={"ip":"10.42.0.2","first_seen":1,"last_seen":1}
    assert call("/api/network/activity", {"action":"track","mac":mac,"tracked":True})[0] == 200
    code, snapshot = call("/api/network/activity")
    assert code == 200 and snapshot["tracked"] == [mac]
    code, answer = call("/api/chat", {"text":"/activity"})
    assert code == 200 and "No visible domain lookups" in answer["content"]
    assert call("/api/network/activity?mac=not-a-mac")[0] == 400
    assert call("/api/network/activity", {"action":"enable","enabled":False})[1]["enabled"] is False
    assert call("/api/network/activity", {"action":"clear"})[0] == 200
    assert call("/api/network/activity", {"action":"track","mac":mac,"tracked":False})[1]["tracked"] == []


@pytest.mark.parametrize(("command", "line"), [
    ('Say “The rover is ready.”', "The rover is ready."),
    ('CASSIE, could you just say "Hello, Titan!"?', "Hello, Titan!"),
    ("Repeat after me: ‘Don’t drop it.’", "Don’t drop it."),
    ("Say exactly: Sensors online.", "Sensors online."),
    ("Say the line Nice work.", "Nice work."),
    ('Say "clear conversation", please.', "clear conversation"),
    ('Say: something about me', "something about me"),
])
def test_requested_line_is_returned_verbatim_without_inference(instance, command, line):
    call, outbound, _ = instance
    status, raw = call("/api/chat", {"text": command, "voice": True, "stream": True})
    assert status == 200
    events = [json.loads(event) for event in raw.splitlines()]
    assert len(events) == 1
    reply = events[0]["reply"]
    assert reply["content"] == line and reply["verbatim"] and reply["sources"] == []
    assert call("/api/session")[1]["chat"][-1]["content"] == line
    assert not outbound


def test_research_method_is_requested_only_for_research(instance):
    call, outbound, _ = instance
    assert call("/api/chat", {"text": "Say something about my rover."})[1]["content"] == "A local answer."
    ordinary = outbound[-1][1]
    assert "Conversation mode" in ordinary["messages"][0]["content"]
    assert "Research mode" not in ordinary["messages"][0]["content"]
    assert call("/api/chat", {"text": "Can you research motor controllers?", "voice": True})[0] == 200
    research = outbound[-1][1]
    assert "Research mode" in research["messages"][0]["content"]
    assert "sources or local records you actually used" in research["messages"][0]["content"]
    assert research["options"]["num_predict"] > ordinary["options"]["num_predict"]
    dataset = call("/api/chat", {"text": "/datasets KITTI"})[1]
    assert "ranked matches by title, category, and description" in dataset["content"]


def test_style_memory_and_conversation_persist(instance):
    call,outbound,path=instance
    assert call("/api/profile",{"tone":"technical","style":"Give testable steps"})[0]==200
    status,notes=call("/api/memory",{"note":"My rover uses ROS 2."})
    assert status==200
    assert call("/api/chat",{"text":"Help me debug my rover."})[0]==200
    msg=outbound[0][1]["messages"][0]["content"]
    assert "ROS 2" in msg and "Give testable steps" in msg
    reopened=server.Store(path)
    assert reopened.profile()["tone"]=="technical" and len(reopened.chat())==2
    assert call("/api/memory/remove",{"id":notes["notes"][0]["id"]})[1]["notes"]==[]
    assert call("/api/chat/clear",{})[0]==200 and server.Store(path).chat()==[]


def test_dataset_links_and_image_bytes_not_persisted(instance):
    call,outbound,path=instance
    code,reply=call("/api/chat",{"text":"/datasets KITTI"})
    assert code==200 and any("KITTI" in r["title"] for r in reply["sources"])
    io=BytesIO()
    Image.new("RGB",(1024,512)).save(io,"PNG")
    payload=base64.b64encode(io.getvalue()).decode()
    assert call("/api/chat",{"text":"What do you see?","image":payload})[0]==200
    img=outbound[-1][1]["messages"][-1]["images"][0]
    assert Image.open(BytesIO(base64.b64decode(img))).size==(768,384)
    code,data=call("/api/export")
    assert code==200 and data["chat"][-2]["had_image"]
    assert payload not in json.dumps(data) and img not in json.dumps(data)
    assert all(p.suffix in {".sqlite3",".token"} or p.name.startswith("cassie.sqlite3-") for p in path.iterdir())


def test_dataset_database_and_memories_survive_a_cleared_conversation(instance, monkeypatch):
    call, outbound, state = instance
    code, before = call("/api/catalog")
    assert code == 200
    assert before["catalog"]["total"] == 1134 and before["catalog"]["flagged"] == 99
    assert len(before["entries"]) == 1035
    assert call("/api/memory", {"note": "My rover uses ROS 2."})[0] == 200
    assert call("/api/chat", {"text": "/datasets KITTI"})[1]["sources"]
    assert not outbound
    assert call("/api/chat/clear", {}, auth=False)[0] == 401
    assert len(call("/api/session")[1]["chat"]) == 2
    assert call("/api/chat/clear", {}) == (200, {"ok": True})
    session = call("/api/session")[1]
    assert session["chat"] == [] and session["notes"][0]["note"] == "My rover uses ROS 2."
    assert call("/api/catalog")[1] == before

    monkeypatch.setattr(server.dataset_search, "CATALOG", state/"missing-seed.json")
    restarted = server.Store(state)
    assert len(restarted.catalog()) == 1035
    assert restarted.chat() == []
    assert server.respond(restarted, {"text": "/datasets KITTI"})["sources"]
    assert not outbound


def test_natural_dataset_search_returns_results_if_model_fails(instance, monkeypatch):
    call, _, _ = instance

    def offline(path, body=None, timeout=180):
        raise server.ModelError("Ollama is offline.")

    monkeypatch.setattr(server, "request_model", offline)
    status, reply = call("/api/chat", {"text": "Find me datasets for KITTI."})
    assert status == 200
    assert "local dataset database" in reply["content"]
    assert any("KITTI" in source["title"] for source in reply["sources"])


def test_status_only_included_when_selected(instance):
    call,outbound,_=instance
    assert call("/api/chat",{"text":"Hello"})[0]==200
    assert "System status (last checked now)" not in outbound[-1][1]["messages"][0]["content"]
    assert call("/api/chat",{"text":"What is this PC doing?","include_status":True})[0]==200
    assert "System status (last checked now)" in outbound[-1][1]["messages"][0]["content"]


def test_bad_image_or_unknown_dataset_does_not_call_model(instance):
    call,outbound,_=instance
    assert call("/api/chat",{"text":"Describe this","image":"eHl6"})[0]==400
    code,data=call("/api/chat",{"text":"/datasets qzxnotfoundxx"})
    assert code==200 and "didn’t find a match" in data["content"] and not outbound


def test_command_routes_do_not_make_changes_or_leak_without_auth(instance):
    call,outbound,path=instance
    for endpoint in ("command","catalog","inbox"):
        assert call("/api/"+endpoint,auth=False)[0]==401
    assert call("/api/quarantine",{"name":"thing"},auth=False)[0]==401
    assert call("/api/command")[1]["machine"]["model_ready"]
    assert len(call("/api/catalog")[1]["entries"])>=1000
    assert call("/api/proposal",{"target":"../../access.token","request":"Review it"})[0]==400
    assert call("/api/proposal",{"target":"persona","request":"Review it"})[0]==200
    proposal = json.loads(outbound[-1][1]["messages"][-1]["content"])
    assert proposal["file"] == "base_persona.txt"
    assert proposal["code_excerpt"].startswith("You are CASSIE")
    assert call("/api/scene",{"labels":"person"})[0]==400
    assert call("/api/scene",{"labels":"chair, bottle"})[0]==200
    assert "chair, bottle" in outbound[-1][1]["messages"][-1]["content"]
    assert call("/api/session")[1]["chat"]==[]


def test_continuous_camera_control_requires_owner_authorization(instance):
    call, _, state = instance
    assert call("/api/camera", auth=False)[0] == 401
    assert call("/api/camera", {"enabled": True}, auth=False)[0] == 401
    assert call("/api/camera", {"enabled": "true"})[0] == 400
    assert not call("/api/camera")[1]["enabled"]
    assert call("/api/camera", {"enabled": True})[1]["enabled"]
    assert (state / "always-camera.enabled").is_file()
    assert call("/api/camera", {"enabled": False})[1]["sample"] is None
    assert not (state / "always-camera.enabled").exists()


def test_chat_stream_retries_a_missing_alias_and_saves_the_reply(instance, monkeypatch):
    call, _, _ = instance
    seen = []

    @contextmanager
    def model_response(path, body, timeout):
        seen.append(body["model"])
        assert body["stream"] is True and path == "/chat"
        if body["model"] == server.MODEL:
            raise server.ModelError("Alias missing", 404)
        assert "You are CASSIE" in body["messages"][0]["content"]
        yield BytesIO(b'{"message":{"content":"I am "}}\n{"message":{"content":"CASSIE"},"done":true}\n')

    monkeypatch.setattr(server, "model_response", model_response)
    monkeypatch.setattr(server, "installed_models", lambda: {"qwen3.5:2b"})
    status, raw = call("/api/chat", {"text": "Who are you?", "stream": True})
    assert status == 200
    updates = [json.loads(line) for line in raw.splitlines()]
    assert [row["delta"] for row in updates[:-1]] == ["I am ", "CASSIE"]
    assert updates[-1]["reply"]["content"] == "I am CASSIE"
    assert call("/api/session")[1]["chat"][-1]["content"] == "I am CASSIE"
    assert seen == [server.MODEL, "qwen3.5:2b"]


def test_speech_input_remains_authenticated_and_does_not_save_audio(instance, monkeypatch):
    call, _, state = instance
    clip = base64.b64encode(b"\x00\x00" * 160).decode()

    class Decoder:
        def __init__(self, model, rate):
            assert rate == 16_000

        def AcceptWaveform(self, chunk):
            assert chunk == b"\x00\x00" * 160
            return False

        def FinalResult(self):
            return '{"text":"cassie hello"}'

    monkeypatch.setattr(server.speech, "recognizer_assets", lambda: (Decoder, object()))
    assert call("/api/speech", {"pcm": clip}, auth=False)[0] == 401
    assert call("/api/speech", {"pcm": clip}) == (200, {"text": "cassie hello"})
    assert {path.name for path in state.iterdir()} <= {
        "access.token", "cassie.sqlite3", "cassie.sqlite3-shm", "cassie.sqlite3-wal",
    }


def test_conversation_memory_command_saves_once_and_is_reviewable(instance):
    call, outbound, _ = instance
    msg = {"text": "Remember that I prefer short answers", "voice": True}
    assert call("/api/chat", msg)[1]["memory_changed"] is True
    assert call("/api/chat", msg)[1]["content"] == "I already have that saved."
    assert call("/api/session")[1]["notes"][0]["note"] == "I prefer short answers"
    assert len(call("/api/session")[1]["notes"]) == 1
    assert "I prefer short answers" in call("/api/chat", {"text": "What do you remember about me?"})[1]["content"]
    assert not outbound


def test_related_older_owner_statements_are_available_to_conversation(instance):
    call, outbound, state = instance
    saved = server.Store(state)
    saved.record("The rover’s wheel controller is running ROS 2.", "Understood.", [], False)
    for n in range(7):
        saved.record(f"Other conversation {n}.", "Understood.", [], False)
    assert call("/api/chat", {"text": "What did we decide for the rover wheel controller?", "voice": True})[0] == 200
    body = next(payload for path, payload in reversed(outbound) if path == "/chat")
    assert "wheel controller is running ROS 2" in body["messages"][0]["content"]
    assert "spoken conversation" in body["messages"][0]["content"]


def test_visual_question_uses_fresh_camera_image_but_normal_chat_does_not(instance, monkeypatch):
    call, outbound, _ = instance
    calls = []
    photo = b"unenhanced camera jpeg bytes"

    def sight(observer, include_image=False):
        calls.append(include_image)
        return "live", ["chair"], photo if include_image else None

    monkeypatch.setattr(server.Observer, "sight", sight)
    status, reply = call("/api/chat", {"text": "What do you see right now?", "voice": True})
    assert status == 200 and reply["used_camera"]
    first = next(payload for path, payload in reversed(outbound) if path == "/chat")
    assert base64.b64decode(first["messages"][-1]["images"][0]) == photo
    assert "chair" in first["messages"][0]["content"]
    assert call("/api/chat", {"text": "Look at my Python code next."})[0] == 200
    ordinary = next(payload for path, payload in reversed(outbound) if path == "/chat")
    assert "images" not in ordinary["messages"][-1] and calls == [True, False]
