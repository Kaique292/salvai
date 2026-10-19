import hashlib
import http.client
import io
import json
import re
import subprocess
import threading
import time
import types
import urllib.error
import zipfile
from pathlib import Path

import pytest
from conftest import FakeEvent, FakeWindow, app, http_request, json_body, wait_until


class RoomApi:
    def __init__(self):
        self.changes = 0
        self.events = []

    def _room_changed(self):
        self.changes += 1

    def _room_event(self, kind, text):
        self.events.append((kind, text))


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(app, "ROOM_SCHEME", "http")
    room = app.Room(RoomApi())
    room.name = "Kaique"
    room._serve()
    room.port = room.server.server_address[1]
    room.public_host = f"127.0.0.1:{room.port}"
    room.code = "ABC123"
    room.phase = "open"
    yield room
    room.close()


@pytest.fixture
def client(host, monkeypatch):
    monkeypatch.setattr(app, "ROOM_LINK_RE", re.compile(r"(http://127\.0\.0\.1:\d+)(?:/\S*)?"))
    monkeypatch.setattr(app, "ROOM_POLL", 0.01)
    guest = app.RoomClient(host.api)
    guest.base = f"http://127.0.0.1:{host.port}"
    yield guest
    guest.phase = "idle"


def call(room, method, path, body=None, sid="", headers=None, raw=None):
    head = {"X-Sala": "1"}
    if sid:
        head["Cookie"] = f"sala={sid}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    head.update(headers or {})
    return http_request(room.port, method, path, headers=head, body=data)


def join(room, name="Ana", approve=True):
    status, headers, _ = call(room, "POST", "/api/join", {"name": name, "code": "abc 123"})
    assert status == 200
    sid = re.search(r"sala=([\w-]+)", headers["Set-Cookie"]).group(1)
    person = room.sessions[sid]["id"]
    if approve:
        room.approve(person)
    return sid, person


def offer(room, sid, items):
    status, _, data = call(room, "POST", "/api/offer", {"items": items}, sid)
    assert status == 200
    return json_body(data)["ids"]


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class FakeProc:
    def __init__(self, lines, running=True, slow=False):
        self.stderr = iter(lines)
        self.running = running
        self.slow = slow
        self.calls = []

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.calls.append("terminate")

    def wait(self, timeout):
        self.calls.append("wait")
        if self.slow:
            raise subprocess.TimeoutExpired("cloudflared", timeout)

    def kill(self):
        self.calls.append("kill")


def test_release_checksums_and_codes():
    body = "notes\ncloudflared-windows-amd64.exe: " + "A" * 64 + "\nother.msi:  " + "b" * 64 + "\nlinha: curta"
    assert app.release_checksums(body) == {"cloudflared-windows-amd64.exe": "a" * 64, "other.msi": "b" * 64}
    assert app.release_checksums(None) == {}
    code = app.new_room_code()
    assert len(code) == 6 and set(code) <= set(app.ROOM_CODE_ALPHABET)
    assert app.normalize_code(" ab-c 12 3 ") == "ABC123" and app.normalize_code(None) == ""
    assert app.format_code("ABC123") == "ABC 123" and app.format_code("") == ""


def test_names_and_paths(tmp_path):
    assert app.clean_label("  Ana <b>\x01 ") == "Ana b" and app.clean_label("", "PC") == "PC"
    assert app.clean_name("a:b*c?.txt. ") == "a_b_c_.txt" and app.clean_name("") == "arquivo"
    assert app.clean_name("con.txt") == "_con.txt" and app.clean_name("x" * 300) == "x" * 180
    assert app.clean_rel("../a\\..\\b/./c:d") == ["a", "b", "c_d"] and app.clean_rel("..") == ["arquivo"]
    target = tmp_path / "f.txt"
    assert app.unique_path(target) == target
    target.write_text("1")
    (tmp_path / "f (2).txt").write_text("2")
    assert app.unique_path(target) == tmp_path / "f (3).txt"
    assert app.is_risky("a/setup.EXE") and not app.is_risky("foto.jpg")


def test_scan_local(tmp_path, monkeypatch):
    file = write(tmp_path / "solo.bin", b"123")
    assert app.scan_local(file) == {
        "kind": "file",
        "name": "solo.bin",
        "files": [{"rel": "solo.bin", "size": 3, "path": str(file)}],
    }
    folder = tmp_path / "Pasta"
    write(folder / "b.txt", b"bb")
    write(folder / "sub" / "a.txt", b"a")
    scanned = app.scan_local(folder)
    assert scanned["kind"] == "folder" and [f["rel"] for f in scanned["files"]] == ["Pasta/b.txt", "Pasta/sub/a.txt"]
    with pytest.raises(ValueError, match="Não achei"):
        app.scan_local(tmp_path / "nada")
    (tmp_path / "vazia").mkdir()
    with pytest.raises(ValueError, match="vazia"):
        app.scan_local(tmp_path / "vazia")
    real_walk = app.os.walk
    monkeypatch.setattr(app.os, "walk", lambda p: [(str(folder), [], ["fantasma.txt", "b.txt"])])
    assert [f["rel"] for f in app.scan_local(folder)["files"]] == ["Pasta/b.txt"]
    monkeypatch.setattr(app.os, "walk", real_walk)
    monkeypatch.setattr(app, "ROOM_MAX_FILES", 1)
    with pytest.raises(ValueError, match="demais"):
        app.scan_local(folder)


def test_items_and_offers():
    item = app.make_item("host", "folder", "Fo:to", [{"rel": "a.exe", "size": 2}, {"rel": "b", "size": 3}])
    assert item["name"] == "Fo_to" and item["size"] == 5 and item["count"] == 2 and item["risky"]
    assert app.public_item(item) == dict(
        {k: item[k] for k in ("id", "kind", "name", "size", "count", "risky")}, thumb=False
    )
    assert app.item_signature(item) == ("folder", "Fo_to", (("a.exe", 2), ("b", 3)))
    parsed = app.parse_offer({"kind": "folder", "files": [{"rel": "x/../y", "size": 1}]})
    assert parsed == {"kind": "folder", "name": "x/y", "files": [{"rel": "x/y", "size": 1}]}
    bad = [
        None,
        {"kind": "zip"},
        {"kind": "file"},
        {"kind": "file", "files": []},
        {"kind": "file", "files": [{"rel": "a", "size": 1}, {"rel": "b", "size": 1}]},
        {"kind": "file", "files": ["a"]},
        {"kind": "file", "files": [{"rel": "a", "size": True}]},
        {"kind": "file", "files": [{"rel": "a", "size": -1}]},
        {"kind": "file", "files": [{"rel": 3, "size": 1}]},
    ]
    for entry in bad:
        with pytest.raises(ValueError):
            app.parse_offer(entry)


def test_jobs_lifecycle(tmp_path, monkeypatch):
    single = {"id": "i", "owner": "o", "kind": "file", "name": "a.txt", "files": [{"rel": "a.txt", "size": 0}]}
    [(target, root)] = app.plan_targets(single, tmp_path)
    assert target == root == tmp_path / "a.txt"
    write(tmp_path / "a.txt", b"x")
    job = app.new_job(single, 0, target, root)
    app.finish_job(job)
    assert job["state"] == "done" and job["dest"] == job["root"] == tmp_path / "a (2).txt"
    folder = {
        "id": "f",
        "owner": "o",
        "kind": "folder",
        "name": "P",
        "files": [{"rel": "P/s/b.txt", "size": 2}, {"rel": "solto", "size": 1}],
    }
    (tmp_path / "P").mkdir()
    plan = app.plan_targets(folder, tmp_path)
    assert plan == [
        (tmp_path / "P (2)" / "s" / "b.txt", tmp_path / "P (2)"),
        (tmp_path / "P (2)" / "solto", tmp_path / "P (2)"),
    ]
    jobs = [app.new_job(folder, i, t, r) for i, (t, r) in enumerate(plan)]
    write(jobs[0]["part"], b"ok")
    jobs[0]["received"] = 2
    app.finish_job(jobs[0])
    assert jobs[0]["root"] == tmp_path / "P (2)" and (tmp_path / "P (2)" / "s" / "b.txt").read_bytes() == b"ok"
    assert app.job_progress([]) is None
    assert app.job_progress([jobs[0]])["state"] == "done"
    assert app.job_progress(jobs)["state"] == "waiting"
    jobs[1]["state"] = "sending"
    assert app.job_progress(jobs)["state"] == "sending"
    jobs[1]["state"], jobs[1]["error"] = "error", "falhou"
    progress = app.job_progress(jobs)
    assert progress == {"state": "error", "done": 2, "total": 3, "files": 2, "finished": 1, "error": "falhou"}
    assert app.restart_jobs([]) is False and app.restart_jobs([jobs[0]]) is False
    assert app.restart_jobs(jobs) is True and jobs[1]["state"] == "waiting" and jobs[1]["error"] == ""
    write(jobs[1]["part"], b"1")
    app.drop_parts(jobs)
    assert not jobs[1]["part"].exists()
    monkeypatch.setattr(app.Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(OSError("busy")))
    app.drop_parts(jobs)


def test_write_part(tmp_path):
    part = tmp_path / "d" / "x.part"
    assert app.write_part(part, 0, io.BytesIO(b"abcdef"), 4) == 4 and part.read_bytes() == b"abcd"
    assert app.write_part(part, 2, io.BytesIO(b"ZZ"), 5) == 2 and part.read_bytes() == b"abZZ"

    class Broken:
        def read(self, size):
            raise ConnectionResetError()

    assert app.write_part(part, 4, Broken(), 3) == 0 and part.read_bytes() == b"abZZ"


def test_zip_entries_and_sink(tmp_path):
    a = write(tmp_path / "a.txt", b"a")
    items = [
        {"files": [{"rel": "a.txt", "path": str(a)}, {"rel": "gone.txt", "path": str(tmp_path / "gone")}]},
        {
            "files": [
                {"rel": "A.txt", "path": str(a)},
                {"rel": "p/a.txt", "path": str(a)},
                {"rel": "p/a.txt", "path": str(a)},
            ]
        },
    ]
    names = [name for name, _ in app.zip_entries(items)]
    assert names == ["a.txt", "A (2).txt", "p/a.txt", "p/a (2).txt"]
    out = io.BytesIO()
    sink = app.StreamSink(out)
    assert sink.write(b"xy") == 2
    sink.flush()
    assert out.getvalue() == b"xy"
    message = app.room_whatsapp_message("https://x.trycloudflare.com", "ABC 123", "Kaique")
    assert "Kaique" in message and "https://x.trycloudflare.com" in message and "*ABC 123*" in message


def test_ensure_cloudflared(isolated, monkeypatch):
    data = b"MZ-cloudflared"
    digest = hashlib.sha256(data).hexdigest()
    url = app.CLOUDFLARED_PREFIX + "2026.10.1/cloudflared-windows-amd64.exe"
    release = {
        "assets": [{"name": app.CLOUDFLARED_ASSET, "browser_download_url": url}],
        "body": f"{app.CLOUDFLARED_ASSET}: {digest}",
    }
    path = isolated / "bin" / "cloudflared.exe"
    monkeypatch.setattr(app, "CLOUDFLARED_PATH", path)
    monkeypatch.setattr(app, "github_latest", lambda repo: release)
    progress = []
    monkeypatch.setattr(app, "download", lambda u, cb=None: (cb(1.0), data)[1])
    assert app.ensure_cloudflared(progress.append) == path and path.read_bytes() == data and progress == [1.0]
    monkeypatch.setattr(app, "download", lambda u, cb=None: pytest.fail("não devia baixar"))
    assert app.ensure_cloudflared() == path
    old = time.time() - app.CLOUDFLARED_MAX_AGE - 10
    app.os.utime(path, (old, old))
    monkeypatch.setattr(app, "download", lambda u, cb=None: b"outro")
    assert app.ensure_cloudflared() == path and path.read_bytes() == data
    path.unlink()
    with pytest.raises(RuntimeError, match="hash"):
        app.ensure_cloudflared()
    assert not path.with_name("cloudflared.exe.part").exists()
    release["assets"][0]["browser_download_url"] = "https://evil.example/cloudflared.exe"
    with pytest.raises(RuntimeError, match="oficial"):
        app.ensure_cloudflared()
    monkeypatch.setattr(app, "github_latest", lambda repo: {"assets": None, "body": None})
    with pytest.raises(RuntimeError, match="oficial"):
        app.ensure_cloudflared()


def test_tunnel(monkeypatch):
    lines = [
        "INF Requesting new quick Tunnel on https://api.trycloudflare.com...\n",
        "INF |  https://Abc-Def.trycloudflare.com  |\n",
        "INF Registered tunnel connection connIndex=0\n",
    ]
    procs = []
    monkeypatch.setattr(app.subprocess, "Popen", lambda *a, **k: procs.append(FakeProc(lines)) or procs[-1])
    tunnel = app.Tunnel()
    assert tunnel.start(1234, Path("cloudflared.exe")) == "https://abc-def.trycloudflare.com"
    assert tunnel.alive()
    procs[-1].slow = True
    tunnel.stop()
    assert procs[-1].calls == ["terminate", "wait", "kill"] and not tunnel.alive()
    tunnel.stop()
    monkeypatch.setattr(
        app.subprocess,
        "Popen",
        lambda *a, **k: procs.append(FakeProc(["INF https://x.trycloudflare.com\n"])) or procs[-1],
    )
    with pytest.raises(RuntimeError, match="Cloudflare"):
        app.Tunnel().start(1, Path("c.exe"), timeout=5)
    monkeypatch.setattr(app.subprocess, "Popen", lambda *a, **k: procs.append(FakeProc([], running=False)) or procs[-1])
    gone = app.Tunnel()
    with pytest.raises(RuntimeError):
        gone.start(1, Path("c.exe"), timeout=0)
    assert procs[-1].calls == []


def test_wait_public(monkeypatch, no_sleep):
    answers = iter(
        [OSError("rede"), {"Status": 3}, {"Status": 0, "Answer": []}, {"Status": 0, "Answer": [{"data": "1.2.3.4"}]}]
    )
    asked = []

    def fake_urlopen(req, timeout):
        asked.append((req.full_url, req.get_header("Accept")))
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return RawResponse(200, json.dumps(answer).encode())

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    assert app.wait_public("https://sala-x.trycloudflare.com") is True
    assert asked[0] == (app.DOH_URL + "sala-x.trycloudflare.com", "application/dns-json") and len(asked) == 4
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda req, timeout: RawResponse(200, b""))
    assert app.wait_public("https://y.trycloudflare.com", timeout=0.05) is False


def test_client_knock_retries(client, monkeypatch, no_sleep):
    attempts = []

    def flaky(method, path, body=None, **kwargs):
        attempts.append(path)
        if len(attempts) < 3:
            raise urllib.error.URLError("getaddrinfo failed")
        return {"state": "pending"}

    monkeypatch.setattr(client, "request", flaky)
    client.phase = "joining"
    assert client._knock("abc") == {"state": "pending"} and len(attempts) == 3
    monkeypatch.setattr(app, "ROOM_JOIN_RETRY", -1)
    attempts.clear()
    with pytest.raises(urllib.error.URLError):
        client._knock("abc")
    monkeypatch.setattr(app, "ROOM_JOIN_RETRY", 60)
    client.phase = "idle"
    attempts.clear()
    with pytest.raises(urllib.error.URLError):
        client._knock("abc")
    assert len(attempts) == 1


def test_room_open_and_watch(monkeypatch, no_sleep):
    api = RoomApi()
    tunnels = []

    class FakeTunnel:
        def __init__(self):
            self.up = True
            self.stopped = False
            tunnels.append(self)

        def start(self, port, exe):
            return "https://sala-teste.trycloudflare.com"

        def alive(self):
            return self.up

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(app, "Tunnel", FakeTunnel)
    monkeypatch.setattr(app, "ensure_cloudflared", lambda progress: (progress(0.5), Path("c.exe"))[1])
    monkeypatch.setattr(app, "wait_public", lambda url: True)
    monkeypatch.setattr(app, "ROOM_TICK", 0)
    room = app.Room(api)
    room.start("  ")
    room.start("outro")
    assert wait_until(lambda: room.phase == "open")
    assert room.url == "https://sala-teste.trycloudflare.com" and room.public_host == "sala-teste.trycloudflare.com"
    assert room.name == app.socket.gethostname() and len(room.code) == 6 and room.progress is None
    status, _, data = http_request(room.server.server_address[1], "GET", "/api/ping", host=room.public_host)
    assert status == 200 and json_body(data) == {"ok": True}
    tunnels[-1].up = False
    assert wait_until(lambda: room.phase == "closed" and api.events)
    assert "Cloudflare caiu" in room.reason and tunnels[-1].stopped and api.events[-1][0] == "closed"
    room.close()
    room.close("de novo")
    assert room.phase == "closed"


def test_room_watch_idle_and_stop(monkeypatch):
    room = app.Room(RoomApi())
    room.tunnel = types.SimpleNamespace(alive=lambda: True, stop=lambda: None)
    room.phase = "open"
    room.last_activity = time.time() - app.ROOM_IDLE_LIMIT - 5
    room.busy = 1
    ticks = []

    def tick(seconds):
        ticks.append(seconds)
        if len(ticks) == 2:
            room.busy = 0

    monkeypatch.setattr(app.time, "sleep", tick)
    room._watch()
    assert room.phase == "closed" and "30 minutos" in room.reason
    room.phase = "open"
    monkeypatch.setattr(app.time, "sleep", lambda s: setattr(room, "phase", "idle"))
    room._watch()
    assert room.phase == "idle"


def test_room_open_failures(monkeypatch):
    api = RoomApi()
    monkeypatch.setattr(app, "ensure_cloudflared", lambda progress: (_ for _ in ()).throw(RuntimeError("sem internet")))
    room = app.Room(api)
    room.start("Kaique")
    assert wait_until(lambda: room.phase == "error") and room.error == "sem internet"

    def cancel(progress):
        room.phase = "idle"
        raise RuntimeError("tarde demais")

    monkeypatch.setattr(app, "ensure_cloudflared", cancel)
    room.start("Kaique")
    assert wait_until(lambda: room.phase == "idle" and api.changes >= 4)
    assert room.error == ""

    class FakeTunnel:
        def start(self, port, exe):
            return "https://cancelada.trycloudflare.com"

        def stop(self):
            pass

    monkeypatch.setattr(app, "ensure_cloudflared", lambda progress: Path("c.exe"))
    monkeypatch.setattr(app, "Tunnel", FakeTunnel)
    monkeypatch.setattr(app, "wait_public", lambda url: setattr(room, "phase", "idle"))
    room.start("Kaique")
    assert wait_until(lambda: room.server is None and room.phase == "idle" and room.url == "")


def test_handler_guards(host, monkeypatch):
    status, _, _ = http_request(host.port, "GET", "/api/ping", host="evil.example")
    assert status == 403
    status, _, data = call(host, "POST", "/api/join", {"code": "x"}, headers={"X-Sala": "0"})
    assert status == 403 and "link" in json_body(data)["error"]
    status, _, _ = call(host, "POST", "/api/join", {"code": "x"}, headers={"Origin": "https://evil.example"})
    assert status == 403
    status, _, _ = call(host, "POST", "/api/join", {"code": "abc123"}, headers={"Origin": f"http://{host.public_host}"})
    assert status == 200
    status, headers, data = http_request(host.port, "HEAD", "/api/state", headers={"Cookie": "sala=nada"})
    assert status == 403 and data == b""
    for _ in range(10):
        host.fail("127.0.0.1")
    status, _, _ = call(host, "GET", "/api/ping")
    assert status == 429
    host.failures.clear()
    for error, code in ((PermissionError("não"), 403), (ValueError("ruim"), 400), (RuntimeError("x"), 500)):
        monkeypatch.setattr(host, "route", lambda *a, e=error: (_ for _ in ()).throw(e))
        status, _, data = call(host, "GET", "/api/ping")
        assert status == code
    monkeypatch.setattr(host, "route", lambda *a: (_ for _ in ()).throw(ConnectionResetError()))
    with pytest.raises(http.client.RemoteDisconnected):
        call(host, "GET", "/api/ping")
    host.public_host = ""
    status, _, _ = call(host, "GET", "/api/ping")
    assert status == 403


def test_pages(host):
    status, headers, page = call(host, "GET", "/")
    assert status == 200 and b"Sala de troca" in page and "Content-Security-Policy" in headers
    status, headers, page = call(host, "HEAD", "/")
    assert status == 200 and page == b""
    status, headers, css = call(host, "GET", "/room.css")
    assert status == 200 and headers["Content-Type"] == "text/css"


def test_join_flow(host, monkeypatch):
    status, _, data = call(host, "GET", "/api/me")
    assert json_body(data) == {"state": "none", "host": "Kaique", "name": ""}
    status, _, data = call(host, "POST", "/api/join", {"name": "Ana", "code": "errado"})
    assert status == 403 and "Código errado" in json_body(data)["error"] and len(host.join_failures) == 1
    status, _, data = call(host, "GET", "/api/state")
    assert status == 403 and "código" in json_body(data)["error"]
    sid, person = join(host, approve=False)
    assert host.api.events[-1] == ("join", "Ana")
    status, _, data = call(host, "GET", "/api/me", sid=sid)
    assert json_body(data) == {"state": "pending", "host": "Kaique", "name": "Ana"}
    status, _, data = call(host, "POST", "/api/join", {"code": "nada"}, sid)
    assert json_body(data) == {"state": "pending"}
    status, _, _ = call(host, "GET", "/api/state", sid=sid)
    assert status == 403
    host.approve(person)
    assert host.status()["people"][0]["state"] == "approved"
    status, _, data = call(host, "POST", "/api/join", {"code": "abc123"}, headers={"User-Agent": "Mozilla (iPhone)"})
    assert host.status()["people"][1]["name"] == "iPhone"
    monkeypatch.setattr(app, "ROOM_MAX_PENDING", 1)
    status, _, data = call(host, "POST", "/api/join", {"code": "abc123"})
    assert status == 429 and "esperando" in json_body(data)["error"]
    host.join_failures.clear()
    host.join_failures.extend([time.time() - 700] + [time.time()] * 60)
    status, _, data = call(host, "POST", "/api/join", {"code": "abc123"})
    assert status == 429 and "erradas demais" in json_body(data)["error"]
    host.join_failures.clear()
    monkeypatch.setattr(app, "ROOM_MAX_PENDING", 8)
    host.kick(person)
    status, _, data = call(host, "GET", "/api/me", sid=sid)
    assert json_body(data)["state"] == "revoked"
    status, _, data = call(host, "GET", "/api/state", sid=sid)
    assert status == 403 and "tirou você" in json_body(data)["error"]
    status, _, _ = call(host, "GET", "/api/nada", sid=join(host, "Bia")[0])
    assert status == 404


def test_host_files_and_zip(host, tmp_path):
    folder = tmp_path / "Fotos"
    write(folder / "a.jpg", b"A" * 10)
    write(folder / "b" / "c.jpg", b"C" * 5)
    solo = write(tmp_path / "setup.exe", b"MZ" * 4)
    host.add_paths([str(folder), str(solo)])
    sid, _ = join(host)
    status, _, data = call(host, "GET", "/api/state", sid=sid)
    state = json_body(data)
    assert (
        state["host"] == "Kaique"
        and state["chunk"] == app.ROOM_CHUNK
        and state["mine"] == []
        and state["requests"] == []
    )
    folder_item, exe_item = state["items"]
    assert folder_item["kind"] == "folder" and folder_item["count"] == 2 and exe_item["risky"] is True
    status, _, data = call(host, "GET", f"/api/files?item={folder_item['id']}", sid=sid)
    assert json_body(data)["files"] == [{"rel": "Fotos/a.jpg", "size": 10}, {"rel": "Fotos/b/c.jpg", "size": 5}]
    status, headers, body = call(host, "GET", f"/api/file?item={folder_item['id']}&f=1&dl=1", sid=sid)
    assert status == 200 and body == b"C" * 5 and headers["Content-Disposition"].startswith("attachment")
    status, headers, body = call(
        host, "GET", f"/api/file?item={folder_item['id']}&f=0", sid=sid, headers={"Range": "bytes=4-"}
    )
    assert status == 206 and body == b"A" * 6
    status, _, body = call(host, "HEAD", f"/api/file?item={exe_item['id']}", sid=sid)
    assert status == 200 and body == b""
    assert host.status()["mine"][0]["fetched"] == ["Ana"]
    status, _, data = call(host, "GET", f"/api/file?item={folder_item['id']}&f=9", sid=sid)
    assert status == 400
    status, _, data = call(host, "GET", "/api/file?item=nada", sid=sid)
    assert status == 400 and "Não achei" in json_body(data)["error"]
    status, headers, body = call(host, "GET", f"/api/zip?items={folder_item['id']},{exe_item['id']}", sid=sid)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert archive.namelist() == ["Fotos/a.jpg", "Fotos/b/c.jpg", "setup.exe"]
        assert archive.read("Fotos/b/c.jpg") == b"C" * 5
    assert "Sala%20de%20Kaique.zip" in headers["Content-Disposition"]
    status, headers, body = call(host, "GET", f"/api/zip?items={folder_item['id']}", sid=sid)
    assert "Fotos.zip" in headers["Content-Disposition"]
    status, _, data = call(host, "GET", "/api/zip?items=", sid=sid)
    assert status == 400 and "Escolha" in json_body(data)["error"]
    solo.unlink()
    status, _, data = call(host, "GET", f"/api/file?item={exe_item['id']}", sid=sid)
    assert status == 400 and "não está mais" in json_body(data)["error"]
    assert host.busy == 0 and host.remove_item(exe_item["id"]) is True and host.remove_item("nada") is False


def test_add_paths_limit(host, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ROOM_MAX_ITEMS", 1)
    file = write(tmp_path / "a.txt", b"a")
    host.add_paths([str(file)])
    with pytest.raises(ValueError, match="demais"):
        host.add_paths([str(file)])


def test_offer_upload_and_pull(host, tmp_path, monkeypatch):
    sid, person = join(host)
    entries = [
        {"kind": "file", "name": "video.mp4", "files": [{"rel": "video.mp4", "size": 6}]},
        {
            "kind": "folder",
            "name": "Docs",
            "files": [{"rel": "Docs/a.txt", "size": 2}, {"rel": "Docs/vazio", "size": 0}],
        },
    ]
    video, docs = offer(host, sid, entries)
    assert offer(host, sid, entries[:1]) == [video]
    status, _, data = call(host, "POST", "/api/offer", {"items": []}, sid)
    assert status == 400
    dest = tmp_path / "recebidos"
    assert host.download([video, docs, "nada"], dest) == 2
    theirs = {i["name"]: i for i in host.status()["theirs"]}
    assert theirs["video.mp4"]["owner"] == "Ana" and theirs["video.mp4"]["progress"]["state"] == "waiting"
    status, _, data = call(host, "GET", "/api/state", sid=sid)
    requests = json_body(data)["requests"]
    assert len(requests) == 2 and {r["item"] for r in requests} == {video, docs}
    req = next(r for r in requests if r["item"] == video)
    upload = f"/api/upload?t={req['id']}&offset="
    status, _, data = call(host, "PUT", upload + "0", sid=sid, raw=b"abc")
    assert status == 200 and json_body(data) == {"received": 3}
    status, _, data = call(host, "PUT", upload + "0", sid=sid, raw=b"abc")
    assert status == 409 and json_body(data) == {"received": 3}
    status, _, data = call(host, "PUT", upload + "3", sid=sid, raw=b"defgh")
    assert status == 409
    host.jobs[req["id"]]["writing"] = True
    status, _, data = call(host, "PUT", upload + "3", sid=sid, raw=b"def")
    assert status == 409
    host.jobs[req["id"]]["writing"] = False
    monkeypatch.setattr(app, "ROOM_MAX_CHUNK", 2)
    status, _, data = call(host, "PUT", upload + "3", sid=sid, raw=b"def")
    assert status == 400 and "grande" in json_body(data)["error"]
    monkeypatch.setattr(app, "ROOM_MAX_CHUNK", 16)
    status, _, data = call(host, "PUT", upload + "3", sid=sid, raw=b"def")
    assert status == 200 and (dest / "video.mp4").read_bytes() == b"abcdef"
    status, _, data = call(host, "PUT", upload + "6", sid=sid, raw=b"")
    assert status == 400 and "não existe" in json_body(data)["error"]
    other, _ = join(host, "Bia")
    req_docs = next(r for r in requests if r["item"] == docs)
    status, _, _ = call(host, "PUT", f"/api/upload?t={req_docs['id']}&offset=0", sid=other, raw=b"xx")
    assert status == 400
    assert host.download([video], dest) == 1
    assert len(host.item_jobs(video)) == 1 and host.item_jobs(video)[0]["state"] == "waiting"
    monkeypatch.setattr(app, "write_part", lambda *a: (_ for _ in ()).throw(PermissionError("disco")))
    status, _, _ = call(host, "PUT", f"/api/upload?t={req_docs['id']}&offset=0", sid=sid, raw=b"xx")
    assert status == 403
    job = host.jobs[req_docs["id"]]
    assert job["state"] == "error" and job["writing"] is False
    monkeypatch.undo()
    monkeypatch.setattr(app, "ROOM_SCHEME", "http")
    assert host.download([docs], dest) == 1 and job["state"] == "waiting"
    status, _, data = call(host, "PUT", f"/api/upload?t={req_docs['id']}&offset=0", sid=sid, raw=b"xx")
    assert status == 200
    assert (dest / "Docs" / "a.txt").read_bytes() == b"xx" and (dest / "Docs" / "vazio").read_bytes() == b""
    assert host.item_root(docs) == dest / "Docs" and host.item_root("nada") is None
    status, _, data = call(host, "GET", "/api/state", sid=sid)
    mine = {i["name"]: i for i in json_body(data)["mine"]}
    assert mine["Docs"]["progress"]["state"] == "done"
    status, _, data = call(host, "POST", "/api/unoffer", {"id": docs}, sid)
    assert status == 200 and docs not in host.items
    monkeypatch.setattr(app, "ROOM_MAX_ITEMS", 1)
    status, _, data = call(host, "POST", "/api/offer", {"items": [entries[1]]}, sid)
    assert status == 400 and "demais" in json_body(data)["error"]
    host.kick(person)
    assert not any(i["owner"] == person for i in host.items.values())


def test_leave_and_close(host, tmp_path):
    sid, person = join(host)
    status, _, data = call(host, "POST", "/api/leave", {}, sid)
    assert status == 200 and not host.sessions and sid not in host.revoked
    sid, person = join(host)
    [item] = offer(host, sid, [{"kind": "file", "name": "a", "files": [{"rel": "a", "size": 4}]}])
    host.download("*", tmp_path)
    write(host.item_jobs(item)[0]["part"], b"12")
    host.close("fechou")
    assert host.phase == "closed" and host.server is None and host.api.events[-1] == ("closed", "fechou")
    assert not (tmp_path / "a.salvai-part").exists()


def test_client_request_errors(client, monkeypatch):
    client.base = "http://127.0.0.1:1"

    def raise_http(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, io.BytesIO(b"<html>"))

    monkeypatch.setattr(app.urllib.request, "urlopen", raise_http)
    with pytest.raises(app.RoomError) as caught:
        client.request("GET", "/api/state")
    assert caught.value.status == 502 and "502" in str(caught.value) and caught.value.data == {}


def test_client_join_validation(client):
    with pytest.raises(ValueError, match="link"):
        client.join("https://example.com/x", "ABC123", "Bia")
    with pytest.raises(ValueError, match="código"):
        client.join(client.base, "--", "Bia")
    assert client.phase == "idle"


def test_client_full_flow(host, client, tmp_path):
    host_file = write(tmp_path / "host" / "musica.mp3", b"M" * 30)
    write(tmp_path / "host" / "Album" / "1.mp3", b"1" * 7)
    write(tmp_path / "host" / "Album" / "vazio.txt", b"")
    host.add_paths([str(host_file), str(tmp_path / "host" / "Album")])
    client.join(client.base + "/qualquer", "abc 123", "")
    assert wait_until(lambda: client.phase == "pending")
    host.approve(host.status()["people"][0]["id"])
    assert wait_until(lambda: client.phase == "open" and client.state.get("items"))
    assert client.host == "Kaique" and client.name == app.socket.gethostname()
    mine = write(tmp_path / "guest" / "foto.jpg", b"F" * 25)
    client.add_paths([str(mine)])
    assert client.status()["mine"][0]["local"] is True
    host.download("*", tmp_path / "no_host")
    assert wait_until(lambda: (tmp_path / "no_host" / "foto.jpg").exists())
    assert (tmp_path / "no_host" / "foto.jpg").read_bytes() == b"F" * 25
    assert client.download("*", tmp_path / "no_guest") == 2
    assert wait_until(lambda: all(i["progress"]["state"] == "done" for i in client.status()["theirs"]))
    assert (tmp_path / "no_guest" / "musica.mp3").read_bytes() == b"M" * 30
    assert (tmp_path / "no_guest" / "Album" / "vazio.txt").exists()
    assert client.download("*", tmp_path / "de_novo") == 2
    assert wait_until(lambda: (tmp_path / "de_novo" / "musica.mp3").exists())
    [item] = client.status()["mine"]
    assert client.remove_item(item["id"]) is True and client.status()["mine"] == []
    status = client.status()
    assert status["role"] == "guest" and status["host"] == "Kaique" and status["people"] == []
    client.close()
    assert wait_until(lambda: not host.sessions) and client.phase == "idle"
    client.close()


def test_client_denied_and_cancelled(host, client):
    client.join(client.base, "abc123", "Bia")
    assert wait_until(lambda: client.phase == "pending")
    host.kick(host.status()["people"][0]["id"])
    assert wait_until(lambda: client.phase == "error") and "não deixou" in client.error
    client.sid = ""
    client.join(client.base, "abc123", "Bia")
    assert wait_until(lambda: client.phase == "pending")
    client.close()
    assert client.phase == "idle"
    client.sid = ""
    client.join(client.base, "errado", "Bia")
    assert wait_until(lambda: client.phase == "error") and "Código errado" in client.error


def test_client_error_after_close(client, monkeypatch):
    def slow_fail(*args, **kwargs):
        client.phase = "idle"
        raise OSError("caiu")

    monkeypatch.setattr(client, "request", slow_fail)
    client._run("abc")
    assert client.phase == "idle" and client.error == ""


def test_client_sync_endings(client, monkeypatch):
    client.phase = "open"
    monkeypatch.setattr(client, "refresh", lambda: (_ for _ in ()).throw(app.RoomError(403, "fora")))
    client._sync()
    assert client.phase == "closed" and "tirou você" in client.reason and client.api.events[-1][0] == "closed"
    errors = iter([app.RoomError(530, "x"), OSError("y")] * 10)
    monkeypatch.setattr(client, "refresh", lambda: (_ for _ in ()).throw(next(errors)))
    client.phase = "open"
    client._sync()
    assert client.phase == "closed" and "não responde" in client.reason
    client._end("de novo")
    assert client.reason.startswith("A sala")
    calls = []

    def refresh_once():
        calls.append(1)
        client.phase = "idle"

    monkeypatch.setattr(client, "refresh", refresh_once)
    client.phase = "open"
    client._sync()
    assert calls == [1]


def test_client_upload_paths(client, tmp_path, monkeypatch, no_sleep):
    source = write(tmp_path / "x.bin", b"0123456789")
    client.local = {"i": [str(source)]}
    client.phase = "open"
    replies = iter(
        [
            app.RoomError(409, "x", {"received": 4}),
            {"received": 8},
            {"received": 10},
        ]
    )
    sent = []

    def fake_request(method, path, body=None, data=None, headers=None, raw=False):
        sent.append((path, data))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(client, "request", fake_request)
    client.state = {"chunk": 4}
    client._upload({"id": "t", "item": "i", "f": 0, "offset": 0, "size": 10})
    assert [p for p, _ in sent] == ["/api/upload?t=t&offset=0", "/api/upload?t=t&offset=4", "/api/upload?t=t&offset=8"]
    assert sent[1][1] == b"4567"
    monkeypatch.setattr(client, "request", lambda *a, **k: (_ for _ in ()).throw(app.RoomError(400, "não")))
    with pytest.raises(app.RoomError):
        client._upload({"id": "t", "item": "i", "f": 0, "offset": 0, "size": 10})
    with pytest.raises(RuntimeError, match="mudou"):
        client._upload({"id": "t", "item": "i", "f": 0, "offset": 10, "size": 20})
    done = []
    monkeypatch.setattr(client, "_upload", lambda req: done.append(req["id"]) or (_ for _ in ()).throw(OSError()))
    client.uploads.extend([{"id": "a"}, {"id": "b"}])
    client.sending.update({"a", "b"})
    worker = threading.Thread(target=client._uploader, daemon=True)
    worker.start()
    assert wait_until(lambda: done == ["a", "b"] and not client.sending)
    client.phase = "idle"
    worker.join(2)


class RawResponse:
    def __init__(self, status, data):
        self.status = status
        self.data = io.BytesIO(data)

    def read(self, size=-1):
        return self.data.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_client_fetch_paths(client, tmp_path, monkeypatch, no_sleep):
    client.phase = "open"
    item = {"id": "i", "owner": "host", "kind": "file", "name": "a.bin", "files": [{"rel": "a.bin", "size": 6}]}
    target = tmp_path / "a.bin"
    job = app.new_job(item, 0, target, target)
    write(job["part"], b"abc")
    responses = [RawResponse(200, b"ABCDEF")]
    asked = []
    monkeypatch.setattr(
        client, "request", lambda m, p, headers=None, raw=False: asked.append(headers) or responses.pop(0)
    )
    client._fetch(job)
    assert target.read_bytes() == b"ABCDEF" and asked == [{"Range": "bytes=3-"}]
    job = app.new_job(item, 0, target, target)
    write(job["part"], b"ab")
    responses.append(RawResponse(206, b"c"))
    with pytest.raises(RuntimeError, match="caiu"):
        client._fetch(job)
    assert job["part"].read_bytes() == b"abc"
    responses.append(RawResponse(206, b"def"))
    client.phase = "idle"
    client._fetch(job)
    assert job["received"] == 3 and job["state"] == "sending"
    client.phase = "open"
    job["state"] = "waiting"
    monkeypatch.setattr(client, "_fetch", lambda j: (_ for _ in ()).throw(OSError("rede")))
    client.jobs = {job["id"]: job}
    worker = threading.Thread(target=client._downloader, daemon=True)
    worker.start()
    assert wait_until(lambda: job["state"] == "error" and job["error"] == "rede")
    client.phase = "idle"
    worker.join(2)
    client._cleanup()
    assert not job["part"].exists()


def test_client_add_paths_batches(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ROOM_OFFER_BATCH", 1)
    files = [write(tmp_path / f"{n}.txt", b"x") for n in "ab"]
    posted = []

    def fake_request(method, path, body=None, **kwargs):
        if path == "/api/offer":
            posted.append(body)
            return {"ids": [f"id{len(posted)}"]}
        return {"host": "Kaique", "items": [], "requests": [{"id": "r", "item": "id1"}, {"id": "s", "item": "x"}]}

    monkeypatch.setattr(client, "request", fake_request)
    client.add_paths([str(f) for f in files])
    assert len(posted) == 2 and client.local == {"id1": [str(files[0])], "id2": [str(files[1])]}
    assert list(client.uploads) == [{"id": "r", "item": "id1"}]
    client.refresh()
    assert len(client.uploads) == 1


def test_client_download_restarts(client, tmp_path, monkeypatch):
    item = {"id": "i", "owner": "host", "kind": "file", "name": "a", "files": [{"rel": "a", "size": 2}]}
    job = app.new_job(item, 0, tmp_path / "a", tmp_path / "a")
    job["state"], job["error"] = "error", "caiu"
    client.jobs = {job["id"]: job}
    client.state = {"items": [dict(app.public_item(dict(item, size=2, count=1, risky=False)))]}
    monkeypatch.setattr(client, "request", lambda *a, **k: pytest.fail("não devia pedir"))
    assert client.download(["i"], tmp_path) == 1 and job["state"] == "waiting"


def test_api_room_basics(api, monkeypatch):
    monkeypatch.setenv("USERNAME", "kaiqu")
    assert api.room_status() == {"role": None, "phase": "idle", "name": "kaiqu"}
    monkeypatch.delenv("USERNAME")
    assert api.room_status()["name"] == ""
    api._remember_room_name("Kaique")
    api._remember_room_name("Kaique")
    api._remember_room_name("")
    assert app.load_config()["room_name"] == "Kaique" and api.room_status()["name"] == "Kaique"
    notes = []
    monkeypatch.setattr(api._tray, "notify", lambda title, msg: notes.append(title))
    api._room_event("join", "Ana")
    api._room_event("closed", "fim")
    assert notes == ["Alguém quer entrar na sala", "Sala de troca fechada"]
    api._window.fail.add("run_js")
    api._room_changed()
    api._window.fail.discard("run_js")
    api._room_changed()
    assert "roomChanged" in api._window.js[-1]
    assert api.room_close()["role"] is None


def test_api_room_create_join_close(api, monkeypatch):
    started = []
    monkeypatch.setattr(
        app.Room, "start", lambda self, name: started.append(name) or setattr(self, "phase", "starting")
    )
    status = api.room_create("Kaique")
    assert status["role"] == "host" and status["phase"] == "starting" and started == ["Kaique"]
    assert api._room_active()
    closed = []
    monkeypatch.setattr(app.Room, "close", lambda self, reason="": closed.append(self))
    first = api._room
    api.room_create("Kaique")
    assert closed == [first]
    status = api.room_join("https://nada.example", "ABC", "Bia")
    assert "link" in status["notice"] and status["role"] == "host"
    monkeypatch.setattr(app.RoomClient, "join", lambda self, link, code, name: setattr(self, "phase", "joining"))
    status = api.room_join("https://a-b.trycloudflare.com", "ABC123", "Bia")
    assert status["role"] == "guest" and status["phase"] == "joining" and len(closed) == 2
    api._room = None
    api.room_join("https://a-b.trycloudflare.com", "ABC123", "Bia")
    monkeypatch.setattr(app.RoomClient, "close", lambda self, reason="": None)
    assert api.room_close()["role"] is None and not api._room_active()


def test_api_room_actions(api, tmp_path, monkeypatch):
    calls = []

    class Fake(app.RoomBase):
        role = "host"

        def status(self):
            return {
                "role": "host",
                "phase": self.phase,
                "url": "https://x.trycloudflare.com",
                "code": "ABC 123",
                "name": "K",
            }

        def add_paths(self, paths):
            calls.append(("add", paths))

        def remove_item(self, item_id):
            calls.append(("remove", item_id))

        def download(self, ids, dest):
            calls.append(("download", ids, dest))

        def approve(self, person):
            calls.append(("approve", person))

        def kick(self, person):
            raise ValueError("não deu")

        def close(self, reason=""):
            pass

    assert api.room_add("files")["role"] is None and api.room_download("*")["role"] is None
    api._room = Fake(api)
    assert api.room_remove("x")["role"] == "host" and calls == []
    api._room.phase = "open"
    assert api.room_add("files")["role"] == "host" and calls == []
    api._window.dialog_result = str(tmp_path / "pasta")
    api.room_add("folder")
    api._window.dialog_result = [str(tmp_path / "a"), str(tmp_path / "b")]
    api.room_add("files")
    assert calls == [("add", [str(tmp_path / "pasta")]), ("add", [str(tmp_path / "a"), str(tmp_path / "b")])]
    assert api._window.calls[-1][3] is True and api._window.calls[-2][3] is False
    api.room_remove("i1")
    api.room_approve("p1")
    assert api.room_kick("p1")["notice"] == "não deu"
    api._window.dialog_result = None
    api.room_download(["i1"])
    api._window.dialog_result = [str(tmp_path)]
    api.room_download(["i1"])
    api._window.dialog_result = str(tmp_path)
    api.room_download("*")
    assert calls[2:] == [
        ("remove", "i1"),
        ("approve", "p1"),
        ("download", ["i1"], tmp_path),
        ("download", "*", tmp_path),
    ]
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(app.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(app, "whatsapp_installed", lambda: False)
    result = api.room_share_whatsapp()
    assert result == {"ok": True, "app": "web"} and "ABC%20123" in opened[-1]
    api._room.phase = "starting"
    assert api.room_share_whatsapp() == {"ok": False}
    folder = tmp_path / "Pasta"
    folder.mkdir()
    file = write(tmp_path / "f.txt", b"x")
    roots = {"d": folder, "f": file, "g": tmp_path / "sumiu"}
    api._room.item_root = roots.get
    count = len(opened)
    api.room_reveal("nada")
    api.room_reveal("g")
    assert len(opened) == count
    api.room_reveal("d")
    api.room_reveal("f")
    assert opened[-2] == folder and opened[-1][0] == "explorer"
    api._room = None
    api.room_reveal("d")


def test_api_room_drop(api, monkeypatch):
    elements = {}

    class Modal:
        def __init__(self):
            self.events = types.SimpleNamespace(drop=FakeEvent())

    api._window.dom = types.SimpleNamespace(get_element=elements.get)
    api._on_loaded()
    elements["#room-modal"] = modal = Modal()
    api._on_loaded()
    handler = modal.events.drop.handlers[0]
    assert handler.prevent_default and handler.callback == api._on_room_drop

    added = []

    def add_paths(paths):
        if "ruim" in paths[0]:
            raise ValueError("A sala já tem itens demais.")
        added.append(paths)

    api._room = types.SimpleNamespace(
        phase="open",
        add_paths=add_paths,
        status=lambda: {"role": "host", "phase": "open"},
        close=lambda reason="": None,
    )
    api._on_room_drop({"dataTransfer": {"files": [{"name": "a.mp4"}]}})
    api._on_room_drop({})
    assert added == [] and api._window.js == []
    files = [{"name": "a.mp4", "pywebviewFullPath": "C:/v/a.mp4"}, {"name": "Fotos", "pywebviewFullPath": "C:/Fotos"}]
    api._on_room_drop({"dataTransfer": {"files": files}})
    assert added == [["C:/v/a.mp4", "C:/Fotos"]]
    assert api._window.js[-1].endswith('app.roomDropped({"role": "host", "phase": "open"})')
    bad = {"dataTransfer": {"files": [{"name": "ruim", "pywebviewFullPath": "C:/ruim"}]}}
    api._window.fail.add("run_js")
    api._on_room_drop(bad)
    api._window.fail.clear()
    api._on_room_drop(bad)
    assert len(added) == 1 and "itens demais" in api._window.js[-1]


def test_api_closing_with_room(api, monkeypatch):
    api._tray.icon = object()
    api._room = types.SimpleNamespace(active=True, close=lambda reason="": None)
    hidden = []
    real_hide = api._hide_to_tray
    monkeypatch.setattr(api, "_hide_to_tray", lambda busy: hidden.append(busy))
    assert api._on_closing() is False and wait_until(lambda: hidden == [0])
    notes = []
    monkeypatch.setattr(api._tray, "notify", lambda title, msg: notes.append(msg))
    monkeypatch.setattr(api._tray, "refresh", lambda: None)
    real_hide(0)
    assert "sala de troca" in notes[-1]
    api._tray.icon = None
    api._on_main_closed()
    api._quit()
    assert api._room is None
    api._on_main_closed()


def test_api_room_end_to_end(api, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ROOM_SCHEME", "http")
    monkeypatch.setattr(app, "ensure_cloudflared", lambda progress: Path("c.exe"))
    monkeypatch.setattr(app, "wait_public", lambda url: True)

    class LocalTunnel:
        def start(self, port, exe):
            self.port = port
            return f"http://127.0.0.1:{port}"

        def alive(self):
            return True

        def stop(self):
            pass

    monkeypatch.setattr(app, "Tunnel", LocalTunnel)
    api.room_create("Kaique")
    assert wait_until(lambda: api.room_status()["phase"] == "open")
    room = api._room
    room.public_host = room.url.split("//")[1]
    api._window.dialog_result = [str(write(tmp_path / "x.txt", b"x"))]
    status = api.room_add("files")
    assert status["mine"][0]["name"] == "x.txt" and status["code"]
    api._window = FakeWindow()
    api.room_close()
    assert room.phase == "idle"


def picture(path: Path, size=(600, 400)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    app.Image.new("RGB", size, "red").save(path)
    return path


def png_bytes() -> bytes:
    out = io.BytesIO()
    app.Image.new("RGB", (32, 18), "blue").save(out, "PNG")
    return out.getvalue()


def test_thumb_helpers(tmp_path, monkeypatch):
    assert app.media_kind("A.JPG") == "image" and app.media_kind("b.mkv") == "video" and app.media_kind("c.txt") == ""
    photo = picture(tmp_path / "foto.png")
    thumb = app.make_thumb([{"rel": "x/leia.txt", "path": "nada"}, {"rel": "x/foto.png", "path": str(photo)}])
    assert app.clean_thumb(thumb) == thumb
    with app.Image.open(io.BytesIO(app.base64.b64decode(thumb.split(",")[1]))) as image:
        assert image.size == (240, 160) and image.format == "JPEG"
    assert app.make_thumb([{"rel": "a.txt", "path": "a.txt"}]) == ""
    assert app.make_thumb([{"rel": "ruim.png", "path": str(write(tmp_path / "ruim.png", b"x"))}]) == ""
    runs = []

    def fake_run(args, **kwargs):
        runs.append(args[args.index("-ss") + 1])
        return types.SimpleNamespace(stdout=b"" if len(runs) == 1 else png_bytes())

    monkeypatch.setattr(app, "ffmpeg_dir", lambda: "bin")
    monkeypatch.setattr(app.subprocess, "run", fake_run)
    assert app.make_thumb([{"rel": "v.mp4", "path": "v.mp4"}]).startswith("data:image/jpeg;base64,")
    assert runs == ["1", "0"]
    monkeypatch.setattr(app.subprocess, "run", lambda args, **kw: types.SimpleNamespace(stdout=b""))
    assert app.video_frame(Path("v.mp4")) == b"" and app.make_thumb([{"rel": "v.mp4", "path": "v.mp4"}]) == ""
    for bad in (
        None,
        "data:image/png;base64,AA==",
        "data:image/jpeg;base64,<x>",
        "data:image/jpeg;base64," + "A" * 70000,
    ):
        with pytest.raises(ValueError, match="Miniatura"):
            app.clean_thumb(bad)


def test_room_thumbs(host, client, tmp_path):
    photo = picture(tmp_path / "host" / "foto.jpg")
    host.add_paths([str(photo), str(write(tmp_path / "host" / "a.txt", b"a"))])
    assert wait_until(lambda: all("thumb" in i for i in host.items.values()))
    [shown, plain] = host.status()["mine"]
    assert shown["thumb"].startswith("data:image/jpeg") and plain["thumb"] == ""
    sid, person = join(host)
    status, headers, data = call(host, "GET", f"/api/thumb?item={shown['id']}", sid=sid)
    assert status == 200 and headers["Content-Type"] == "image/jpeg" and data[:2] == b"\xff\xd8"
    status, _, data = call(host, "GET", f"/api/thumb?item={plain['id']}", sid=sid)
    assert status == 400 and "miniatura" in json_body(data)["error"]
    state = json_body(call(host, "GET", "/api/state", sid=sid)[2])
    assert {i["name"]: i["thumb"] for i in state["items"]} == {"foto.jpg": True, "a.txt": False}
    [mine] = offer(host, sid, [{"kind": "file", "name": "v.jpg", "files": [{"rel": "v.jpg", "size": 1}]}])
    status, _, _ = call(host, "POST", "/api/thumb", {"id": mine, "thumb": shown["thumb"]}, sid)
    assert status == 200 and host.status()["theirs"][0]["thumb"] == shown["thumb"]
    status, _, data = call(host, "POST", "/api/thumb", {"id": shown["id"], "thumb": shown["thumb"]}, sid)
    assert status == 400 and "Não achei" in json_body(data)["error"]
    status, _, data = call(host, "POST", "/api/thumb", {"id": mine, "thumb": "x"}, sid)
    assert status == 400 and "Miniatura" in json_body(data)["error"]
    host.kick(person)
    client.join(client.base, "abc123", "Bia")
    assert wait_until(lambda: client.phase == "pending")
    host.approve(next(p["id"] for p in host.status()["people"] if p["state"] == "pending"))
    assert wait_until(lambda: client.phase == "open" and len(client.thumbs) == 1)
    theirs = {i["name"]: i["thumb"] for i in client.status()["theirs"]}
    assert theirs == {"foto.jpg": shown["thumb"], "a.txt": ""}
    client.thumbs.clear()
    host.items[plain["id"]]["thumb"] = shown["thumb"]
    host.items[shown["id"]]["thumb"] = ""
    assert client._thumb(shown["id"]) == ""
    client.add_paths([str(picture(tmp_path / "guest" / "eu.png")), str(write(tmp_path / "guest" / "b.txt", b"b"))])
    assert wait_until(lambda: any(i.get("thumb") for i in host.items.values() if i["owner"] != "host"))
    mine = {i["name"]: i["thumb"] for i in client.status()["mine"]}
    assert mine["eu.png"].startswith("data:image/jpeg") and mine["b.txt"] == ""


def test_client_send_thumbs_survives_errors(client, monkeypatch):
    monkeypatch.setattr(app, "make_thumb", lambda files: "data:image/jpeg;base64,AA==")
    monkeypatch.setattr(client, "request", lambda *a, **k: (_ for _ in ()).throw(app.RoomError(400, "não")))
    client._send_thumbs([("i", [])])
    assert client.thumbs == {"i": "data:image/jpeg;base64,AA=="} and client.api.changes == 1


def test_local_files(tmp_path, monkeypatch):
    files = app.LocalFiles()
    video = write(tmp_path / "vídeo 1.mp4", b"0123456789")
    url = files.share(video)
    assert url.endswith("/v%C3%ADdeo%201.mp4") and files.share(video) != url
    port = files.server.server_address[1]
    path = url.split(str(port), 1)[1]
    status, headers, data = http_request(port, "GET", path, headers={"Range": "bytes=2-4"})
    assert status == 206 and data == b"234" and headers["Cross-Origin-Resource-Policy"] == "cross-origin"
    status, headers, data = http_request(port, "HEAD", path)
    assert status == 200 and data == b"" and headers["Content-Length"] == "10"
    assert http_request(port, "GET", "/nada/x")[0] == 404
    assert http_request(port, "GET", path, headers={"Host": "evil.com"})[0] == 404
    monkeypatch.setattr(app, "send_file", lambda *a: (_ for _ in ()).throw(ConnectionResetError()))
    with pytest.raises(http.client.RemoteDisconnected):
        http_request(port, "GET", path)
    files.server.shutdown()


def test_api_room_preview(api, tmp_path, monkeypatch):
    photo = picture(tmp_path / "foto.png")
    clip = write(tmp_path / "clip.mp4", b"v")
    roots = {"p": photo, "v": clip, "t": write(tmp_path / "a.txt", b"t"), "d": tmp_path, "g": tmp_path / "sumiu"}
    assert api.room_preview("p") == {}
    api._room = types.SimpleNamespace(item_root=roots.get, close=lambda reason="": None)
    monkeypatch.setattr(api._viewer, "share", lambda path: f"http://127.0.0.1:1/{path.name}")
    assert api.room_preview("p") == {"kind": "image", "name": "foto.png", "url": "http://127.0.0.1:1/foto.png"}
    assert api.room_preview("v")["kind"] == "video"
    assert api.room_preview("t") == api.room_preview("d") == api.room_preview("g") == api.room_preview("x") == {}
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    api.room_open("v")
    api.room_open("g")
    assert opened == [clip]
