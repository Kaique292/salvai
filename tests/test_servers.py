import json
import socket
import time
import types
from pathlib import Path

import pystray
import pytest
from conftest import FakeYDL, http_request, json_body, wait_until

import app


@pytest.fixture
def bridge(api, monkeypatch):
    monkeypatch.setattr(api, "_meta_pool", types.SimpleNamespace(submit=lambda *a: None))
    instance = app.Bridge(api)
    instance.start()
    yield instance
    instance.server.shutdown()
    instance.server.server_close()


def call(bridge, method, path, body=None, token=None, host=None):
    headers = {"Authorization": f"Bearer {token or bridge.token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    return http_request(bridge.server.server_address[1], method, path, headers, data, host)


def test_bridge_writes_discovery_file(bridge):
    info = json.loads(app.BRIDGE_PATH.read_text(encoding="utf-8"))
    assert info["port"] == bridge.server.server_address[1] and info["token"] == bridge.token


def test_bridge_rejects_bad_host_and_token(bridge):
    assert call(bridge, "GET", "/status", host="evil.com")[0] == 421
    assert call(bridge, "GET", "/status", token="errado")[0] == 401


def test_bridge_routes(bridge, api, monkeypatch):
    status, _, data = call(bridge, "GET", "/status")
    assert status == 200 and json_body(data)["app"] == "Salvaí"
    monkeypatch.setattr(app, "is_internal_target", lambda url: "10.0.0.1" in url)
    status, _, data = call(
        bridge,
        "POST",
        "/downloads",
        {
            "items": [
                {
                    "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
                    "format": "mp3",
                    "quality": "320",
                    "folder": "Aulas",
                },
                {"url": "http://10.0.0.1/"},
            ]
        },
    )
    queued = json_body(data)["queued"]
    assert (
        queued[0]["folder"] == "Aulas" and queued[0]["quality"] == "320 kbps" and "rede interna" in queued[1]["error"]
    )
    status, _, data = call(bridge, "POST", "/downloads", {"items": [{"url": "https://exemplo.org/v"}]})
    assert json_body(data)["queued"][0]["folder"] == "(pasta principal)"
    first = queued[0]["id"]
    _, _, data = call(bridge, "GET", f"/downloads?ids={first}")
    assert [d["id"] for d in json_body(data)["downloads"]] == [first]
    _, _, data = call(bridge, "GET", "/downloads")
    assert len(json_body(data)["downloads"]) == 2
    Path(api._out_dir, "a.mp3").write_bytes(b"1")
    assert json_body(call(bridge, "GET", "/files?folder=&depth=2")[2])["files"][0]["path"] == "a.mp3"
    assert json_body(call(bridge, "POST", "/move", {"path": "a.mp3", "folder": "X"})[2]) == {"moved_to": "X\\a.mp3"}
    FakeYDL.script = {"ytsearch": {"info": {"entries": []}}}
    assert json_body(call(bridge, "POST", "/search", {"query": "aula"})[2])["results"] == []


def test_bridge_errors(bridge, api, monkeypatch):
    assert call(bridge, "GET", "/nada")[0] == 400
    assert call(bridge, "POST", "/move", {"path": "../fora.txt"})[0] == 400
    status, _, _ = http_request(
        bridge.server.server_address[1],
        "POST",
        "/search",
        {"Authorization": f"Bearer {bridge.token}", "Content-Length": str(app.MAX_BODY + 1)},
        b"",
    )
    assert status == 400
    monkeypatch.setattr(api, "_status", lambda: (_ for _ in ()).throw(RuntimeError("quebrou")))
    status, _, data = call(bridge, "GET", "/status")
    assert status == 500 and json_body(data)["error"] == "quebrou"


def test_bridge_stop(bridge, monkeypatch):
    bridge.stop()
    assert not app.BRIDGE_PATH.exists()
    bridge.stop()
    app.BRIDGE_PATH.write_text(json.dumps({"pid": -1}))
    bridge.stop()
    assert app.BRIDGE_PATH.exists()


@pytest.fixture
def phone(api, monkeypatch):
    monkeypatch.setattr(
        app,
        "home_network",
        lambda: {
            "kind": "cabo",
            "name": "Rede",
            "public": True,
            "ipv4": ["127.0.0.1"],
            "ipv6": [],
            "v4_networks": [],
            "v6_networks": [],
        },
    )
    monkeypatch.setattr(api, "_meta_pool", types.SimpleNamespace(submit=lambda *a: None))
    server = api._phone
    server.start()
    yield server
    server.stop()


def device_cookie(phone):
    if not phone.session_for(getattr(phone, "test_sid", "")):
        phone.test_sid = phone.open_session("127.0.0.1", "Mozilla/5.0 (iPhone)")
    return f"salvai={phone.test_sid}"


def phone_call(phone, method, path, headers=None, body=None, host=None, cookie=True):
    all_headers = {"Cookie": device_cookie(phone)} if cookie is True else {"Cookie": cookie} if cookie else {}
    if method in ("POST", "PUT"):
        all_headers["X-Salvai"] = "1"
    all_headers.update(headers or {})
    return http_request(phone.server.server_address[1], method, path, all_headers, body, host)


def test_phone_entry_and_page(phone):
    status, headers, page = phone_call(phone, "GET", f"/?k={phone.token}", cookie=False)
    assert status == 200 and b"Salva" in page and "Location" not in headers
    assert "HttpOnly" in headers["Set-Cookie"] and headers["Referrer-Policy"] == "no-referrer"
    sid = headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    assert sid != phone.token and phone.session_for(sid)["name"] == "Navegador"
    status, headers, page = phone_call(phone, "GET", f"/?k={phone.token}", cookie=f"salvai={sid}")
    assert status == 200 and "Set-Cookie" not in headers and len(phone.sessions) == 1
    status, headers, page = phone_call(phone, "GET", "/")
    assert status == 200 and b"Salva" in page and "Content-Security-Policy" in headers
    assert "Set-Cookie" not in headers
    assert phone_call(phone, "GET", "/?k=errado", cookie=False)[0] == 403
    assert phone_call(phone, "GET", f"/api/state?k={phone.token}", cookie=False)[0] == 403
    assert phone_call(phone, "GET", "/api/state", cookie=f"salvai={phone.token}")[0] == 403
    status, headers, body = phone_call(phone, "GET", "/mobile.css")
    assert status == 200 and headers["Content-Type"] == "text/css"
    assert phone_call(phone, "HEAD", "/mobile.js")[0] == 200


def test_phone_state_add_and_files(phone, api, monkeypatch):
    monkeypatch.setattr(app, "is_internal_target", lambda url: False)
    status, headers, data = phone_call(phone, "GET", "/api/state")
    assert status == 200 and json_body(data)["downloads"] == []
    assert phone_call(phone, "GET", "/api/state", {"If-None-Match": headers["ETag"]})[0] == 304
    assert phone_call(phone, "HEAD", "/api/state")[2] == b""
    status, _, data = phone_call(
        phone,
        "POST",
        "/api/add",
        {"Content-Type": "application/json"},
        json.dumps({"url": "https://exemplo.org/v", "format": "mp3"}).encode(),
    )
    assert status == 200 and json_body(data) == {"queued": 1}
    assert phone_call(phone, "POST", "/api/add", {}, b'{"url": "nada"}')[0] == 400
    music = Path(api._out_dir, "musica.mp3")
    music.write_bytes(b"12345")
    Path(api._out_dir, "nao-baixado.mp4").write_bytes(b"pessoal")
    Path(api._out_dir, "doc.pdf").write_bytes(b"segredo")
    assert json_body(phone_call(phone, "GET", "/api/files")[2])["files"] == []
    api._remember(str(music))
    status, _, data = phone_call(phone, "GET", "/api/files")
    files = json_body(data)["files"]
    assert [f["name"] for f in files] == ["musica.mp3"] and "path" not in files[0]
    key = files[0]["id"]
    status, headers, data = phone_call(phone, "GET", f"/api/file?id={key}&dl=1")
    assert status == 200 and data == b"12345" and "attachment" in headers["Content-Disposition"]
    assert phone_call(phone, "HEAD", f"/api/file?id={key}")[2] == b""
    other = app.file_key(Path(api._out_dir, "nao-baixado.mp4"))
    assert phone_call(phone, "GET", f"/api/file?id={other}")[0] == 400
    assert phone_call(phone, "GET", "/api/file?path=nao-baixado.mp4")[0] == 400
    assert phone_call(phone, "GET", "/api/file")[0] == 400
    assert phone_call(phone, "GET", "/naoexiste")[0] == 404


def test_phone_rate_limit(phone, monkeypatch):
    monkeypatch.setattr(app, "validate_remote_url", lambda url: (_ for _ in ()).throw(ValueError("bloqueado")))
    phone.adds.extend([time.time() - 120])
    codes = [phone_call(phone, "POST", "/api/add", {}, b'{"url": "x"}')[0] for _ in range(21)]
    assert codes[:20] == [400] * 20 and codes[20] == 429


def test_phone_security_checks(phone):
    assert phone_call(phone, "GET", "/api/state", host="evil.com")[0] == 403
    assert phone_call(phone, "POST", "/api/add", {"Origin": "http://evil.com"}, b"{}")[0] == 403
    assert (
        phone_call(
            phone,
            "POST",
            "/api/add",
            {"Origin": f"http://127.0.0.1:{phone.server.server_address[1]}"},
            b'{"url": "http://localhost/"}',
        )[0]
        == 400
    )
    for _ in range(20):
        assert phone_call(phone, "GET", "/api/state", cookie=False)[0] == 403
    assert phone_call(phone, "GET", "/api/state")[0] == 429
    phone.failures.clear()
    phone.network = {"v4_networks": ["10.0.0.0/8"]}
    assert phone_call(phone, "GET", "/api/state")[0] == 200


def test_phone_route_errors(phone, api, monkeypatch):
    monkeypatch.setattr(api, "_phone_files", lambda: (_ for _ in ()).throw(RuntimeError("caminho C:/segredo")))
    status, _, data = phone_call(phone, "GET", "/api/files")
    assert status == 500 and "segredo" not in data.decode()
    monkeypatch.setattr(api, "_phone_files", lambda: (_ for _ in ()).throw(BrokenPipeError()))
    with pytest.raises((ConnectionError, OSError, Exception)):
        phone_call(phone, "GET", "/api/files")


def test_client_allowed_rules(api):
    server = app.PhoneServer(api)
    assert server.client_allowed("127.0.0.1") and server.client_allowed("fe80::1%3")
    assert server.client_allowed("192.168.0.9") and not server.client_allowed("8.8.8.8")
    assert not server.client_allowed("lixo")
    server.network = {"v4_networks": ["192.168.15.0/24"], "v6_networks": ["2804:7f0::/64"]}
    assert server.client_allowed("::ffff:192.168.15.4") and not server.client_allowed("192.168.99.1")
    assert server.client_allowed("2804:7f0::9") and not server.client_allowed("fdfd::1")


def test_phone_status_and_addresses(api, monkeypatch):
    server = app.PhoneServer(api)
    assert server.status() == {"on": False}
    monkeypatch.setattr(
        app,
        "home_network",
        lambda: {"kind": "wifi", "name": "Casa", "public": False, "ipv4": ["192.168.0.2"], "ipv6": ["2804::2"]},
    )
    server.start()
    try:
        server.network = None
        status = server.status()
        assert status["on"] and "<svg" in status["qr"]
        assert wait_until(lambda: server.network is not None)
        status = server.status()
        assert status["url"].startswith("http://192.168.0.2:") and status["others"][0].startswith("http://[2804::2]")
        assert server.status()["qr"] is status["qr"] or server.qr[0] == status["url"]
        sid = server.open_session("192.168.0.9", "Mozilla/5.0 (iPhone)")
        server.session_for(sid)["seen"] = time.time() - 60
        device = server.status()["devices"][0]
        assert device["name"] == "iPhone" and device["ip"] == "192.168.0.9" and device["online"] is False
        assert server.status()["history"] == []
        server.network = {"ipv4": [], "ipv6": []}
        monkeypatch.setattr(app, "lan_ip", lambda: "10.1.1.1")
        assert server.addresses()[0].startswith("http://10.1.1.1:")
        server.start()
    finally:
        server.stop()
        server.stop()


def test_refresh_network_respects_ttl(api, monkeypatch):
    server = app.PhoneServer(api)
    calls = []
    monkeypatch.setattr(app, "home_network", lambda: calls.append(1) or {"x": 1})
    server.refresh_network()
    server.refresh_network()
    assert calls == [1]


def test_watch_idle_turns_off(api, monkeypatch, no_sleep):
    server = app.PhoneServer(api)
    off = []
    monkeypatch.setattr(api, "_phone_auto_off", lambda: off.append(1))
    sentinel = object()
    server.server = sentinel
    server.last_activity = time.time()
    monkeypatch.setattr(app, "PHONE_IDLE_LIMIT", -1)
    stopped = []
    monkeypatch.setattr(server, "stop", lambda: (stopped.append(1), setattr(server, "server", None)))
    server.watch_idle(sentinel)
    assert stopped == [1] and off == [1]
    monkeypatch.setattr(app, "PHONE_IDLE_LIMIT", 3600)
    naps = []
    monkeypatch.setattr(
        app.time, "sleep", lambda s: naps.append(s) if len(naps) < 1 else setattr(server, "server", None)
    )
    server.server = sentinel
    server.watch_idle(sentinel)
    assert naps == [30] and stopped == [1]
    server.watch_idle(object())


def test_phone_start_fallbacks(api, monkeypatch):
    busy = socket.socket(socket.AF_INET6)
    busy.bind(("::", 0))
    busy.listen()
    monkeypatch.setattr(app, "PHONE_PORT", busy.getsockname()[1])
    monkeypatch.setattr(app, "home_network", lambda: {"ipv4": ["127.0.0.1"], "ipv6": []})
    server = app.PhoneServer(api)
    try:
        server.start()
        assert server.server.server_address[1] != app.PHONE_PORT
    finally:
        server.stop()
        busy.close()

    class Failing:
        def __init__(self, *a, **k):
            raise OSError("ocupado")

    monkeypatch.setattr(app, "DualStackServer", Failing)
    server.start()
    assert server.server.address_family == socket.AF_INET
    server.stop()
    monkeypatch.setattr(app, "ExclusiveHTTPServer", Failing)
    with pytest.raises(RuntimeError):
        server.start()


class FakeIcon:
    instances = []

    def __init__(self, name, image, title, menu):
        self.name, self.image, self.title, self.menu = name, image, title, menu
        self.notified, self.updated, self.stopped, self.fail = [], 0, False, False
        FakeIcon.instances.append(self)

    def run_detached(self):
        pass

    def notify(self, message, title):
        if self.fail:
            raise RuntimeError("sem notificação")
        self.notified.append((title, message))

    def update_menu(self):
        if self.fail:
            raise RuntimeError("sem menu")
        self.updated += 1

    def stop(self):
        if self.fail:
            raise RuntimeError("já parado")
        self.stopped = True


def test_tray_menu_and_lifecycle(api, monkeypatch):
    monkeypatch.setattr(app.pystray, "Icon", FakeIcon)
    actions = []
    monkeypatch.setattr(api, "_show_from_tray", lambda: actions.append("show"))
    monkeypatch.setattr(api, "_toggle_phone_from_tray", lambda: actions.append("phone"))
    monkeypatch.setattr(api, "_quit", lambda: actions.append("quit"))
    monkeypatch.setattr(app.os, "startfile", lambda path: actions.append(path), raising=False)
    tray = app.Tray(api)
    tray.notify("a", "b")
    tray.refresh()
    tray.stop()
    tray.start()
    icon = tray.icon
    items = [i for i in icon.menu.items if i is not pystray.Menu.SEPARATOR]
    for item in items:
        str(item.text)
        assert item.checked in (True, False, None)
        if item.enabled:
            item(icon)
    assert actions == ["show", "phone", api._out_dir, "quit"]
    tray.notify("Título", "Mensagem")
    tray.refresh()
    assert icon.notified == [("Título", "Mensagem")] and icon.updated == 1 and "Nenhum download" in icon.title
    icon.fail = True
    tray.notify("x", "y")
    tray.refresh()
    tray.stop()
    assert tray.icon is None


def test_phone_file_actions(phone, api, monkeypatch):
    base = Path(api._out_dir)
    for name in ("a.mp4", "b.mp4"):
        (base / name).write_bytes(b"1")
        api._remember(str(base / name))
    post = lambda path, body: phone_call(
        phone, "POST", path, {"Content-Type": "application/json"}, json.dumps(body).encode()
    )
    status, _, data = post("/api/files/forget", {"id": app.file_key(base / "a.mp4")})
    assert status == 200 and json_body(data) == {"ok": True} and (base / "a.mp4").exists()
    assert json_body(post("/api/files/forget", {"id": "x"})[2]) == {"ok": False}
    monkeypatch.setattr(app, "send_to_trash", lambda path: path.unlink())
    status, _, data = post("/api/files/trash", {"id": app.file_key(base / "b.mp4")})
    assert status == 200 and json_body(data) == {"trashed": "b.mp4"} and not (base / "b.mp4").exists()
    status, _, data = post("/api/files/trash", {"id": app.file_key(base / "a.mp4")})
    assert status == 400 and "não encontrado" in json_body(data)["error"]
    api._remember(str(base / "a.mp4"))
    assert json_body(post("/api/files/clear", {})[2]) == {"ok": True} and api._saved == []
    assert phone_call(phone, "POST", "/api/files/trash", {"Origin": "http://evil.com"}, b"{}")[0] == 403


def test_phone_revoke_keeps_others_connected(phone, api):
    first = phone.open_session("192.168.0.5", "Mozilla/5.0 (iPhone)")
    second = phone.open_session("192.168.0.6", "Mozilla/5.0 (Linux; Android 14)")
    old_token = phone.token
    status = phone.status()
    old_qr = status["qr"]
    names = [d["name"] for d in status["devices"]]
    assert names == ["iPhone", "Android"]
    first_id = phone.session_for(first)["id"]
    assert phone.revoke(first_id) is True and phone.revoke("nao-existe") is False
    assert phone.token != old_token and phone.status()["qr"] != old_qr
    status, _, data = phone_call(phone, "GET", "/api/state", cookie=f"salvai={first}")
    assert status == 403 and json_body(data)["revoked"] is True and "desconectado" in json_body(data)["error"]
    assert phone_call(phone, "GET", f"/?k={old_token}", cookie=f"salvai={first}")[0] == 403
    assert phone_call(phone, "GET", "/api/state", cookie=f"salvai={second}")[0] == 200
    assert phone_call(phone, "GET", f"/?k={old_token}", cookie=f"salvai={second}")[0] == 200
    history = phone.status()["history"]
    assert history[0]["id"] == first_id and history[0]["revoked"] is True
    assert app.load_config()["phone_history"][0]["revoked"] is True
    status, headers, _ = phone_call(phone, "GET", f"/?k={phone.token}", cookie=False)
    assert status == 200 and "Set-Cookie" in headers


def test_phone_revoke_all_and_history(phone, api, monkeypatch):
    monkeypatch.setattr(app, "PHONE_HISTORY_LIMIT", 3)
    sids = [phone.open_session(f"192.168.0.{n}", "Mozilla/5.0 (Windows NT 10.0)") for n in range(5)]
    assert len(app.load_config()["phone_history"]) == 3
    token = phone.token
    phone.revoke_all()
    assert phone.sessions == {} and phone.token != token
    assert all(h["revoked"] for h in phone.status()["history"])
    for sid in sids[-2:]:
        assert json_body(phone_call(phone, "GET", "/api/state", cookie=f"salvai={sid}")[2])["revoked"] is True


def test_phone_stop_saves_last_seen(api, monkeypatch):
    monkeypatch.setattr(
        app, "home_network", lambda: {"ipv4": ["127.0.0.1"], "ipv6": [], "v4_networks": [], "v6_networks": []}
    )
    server = app.PhoneServer(api)
    server.start()
    sid = server.open_session("192.168.0.7", "Mozilla/5.0 (iPad)")
    server.session_for(sid)["seen"] = 1234.0
    server.stop()
    entry = app.load_config()["phone_history"][0]
    assert entry["name"] == "iPad" and entry["last"] == 1234.0 and "revoked" not in entry
    assert server.sessions == {}


def test_api_phone_device_controls(api, monkeypatch):
    monkeypatch.setattr(
        app, "home_network", lambda: {"ipv4": ["127.0.0.1"], "ipv6": [], "v4_networks": [], "v6_networks": []}
    )
    api.phone_start()
    try:
        sid = api._phone.open_session("192.168.0.8", "Mozilla/5.0 (iPhone)")
        device_id = api._phone.session_for(sid)["id"]
        assert api.phone_revoke(device_id)["devices"] == []
        api._phone.open_session("192.168.0.9", "Mozilla/5.0 (iPhone)")
        assert api.phone_revoke_all()["devices"] == []
        assert len(api.phone_status()["history"]) == 2
        assert api.phone_clear_history()["history"] == [] and app.load_config()["phone_history"] == []
    finally:
        api.phone_stop()


def send_plan(phone, files):
    status, _, data = phone_call(
        phone, "POST", "/api/send", {"Content-Type": "application/json"}, json.dumps({"files": files}).encode()
    )
    return status, json_body(data)


def upload(phone, job_id, offset, chunk):
    status, _, data = phone_call(phone, "PUT", f"/api/upload?t={job_id}&offset={offset}", {}, chunk)
    return status, json_body(data)


def test_phone_send_to_pc(phone, api, monkeypatch):
    notes = []
    monkeypatch.setattr(api._tray, "notify", lambda title, msg: notes.append(msg))
    status, reply = send_plan(phone, [{"name": "foto.jpg", "size": 6}, {"name": "vazio.txt", "size": 0}])
    assert status == 200 and reply["chunk"] == app.PHONE_CHUNK
    photo, empty = reply["uploads"]
    assert photo["offset"] == 0 and empty["offset"] == 0
    inbox = Path(api._out_dir, app.PHONE_INBOX)
    assert (inbox / "vazio.txt").read_bytes() == b"" and notes == []
    assert phone.incoming() is None
    assert upload(phone, photo["id"], 0, b"abc") == (200, {"received": 3, "done": False})
    assert phone.status()["incoming"] == {"files": 1, "done": 3, "total": 6}
    assert upload(phone, photo["id"], 0, b"abc") == (409, {"received": 3})
    assert upload(phone, photo["id"], 3, b"defgh") == (409, {"received": 3})
    status, again = send_plan(phone, [{"name": "foto.jpg", "size": 6}])
    assert again["uploads"] == [{"id": photo["id"], "offset": 3}]
    assert upload(phone, photo["id"], 3, b"def") == (200, {"received": 6, "done": True})
    assert (inbox / "foto.jpg").read_bytes() == b"abcdef"
    assert notes == ["foto.jpg chegou de iPhone."]
    assert not list(inbox.glob("*.salvai-part"))
    received = phone.status()["received"]
    assert [r["name"] for r in received] == ["foto.jpg", "vazio.txt"]
    assert set(received[0]) == {"id", "name", "size", "device", "at"} and received[0]["device"] == "iPhone"
    assert phone.received_file(received[0]["id"]) == inbox / "foto.jpg"
    (inbox / "vazio.txt").unlink()
    assert phone.received_file(received[1]["id"]) is None and phone.received_file("x") is None
    status, reply = send_plan(phone, [{"name": "foto.jpg", "size": 1}, {"name": "foto.jpg", "size": 1}])
    first, second = reply["uploads"]
    assert first["id"] != second["id"]
    assert upload(phone, first["id"], 0, b"1")[1]["done"] is True
    assert upload(phone, second["id"], 0, b"2")[1]["done"] is True
    assert notes[-1] == "2 arquivos chegaram de iPhone."
    assert sorted(p.name for p in inbox.iterdir()) == ["foto (2).jpg", "foto (3).jpg", "foto.jpg"]


def test_phone_send_rejects_bad_requests(phone, api, monkeypatch):
    assert send_plan(phone, [])[0] == 400
    assert send_plan(phone, "x")[0] == 400
    assert send_plan(phone, [{"name": "a"}] * (app.PHONE_SEND_BATCH + 1))[0] == 400
    for bad in ("x", {"name": "a"}, {"name": "a", "size": -1}, {"name": "a", "size": True}, {"size": 1 << 42}):
        assert send_plan(phone, [bad]) == (400, {"error": "Arquivo inválido."})
    status, reply = send_plan(phone, [{"name": "../../x:y?.bin", "size": 2}])
    job = phone.uploads[reply["uploads"][0]["id"]]
    assert job["dest"] == Path(api._out_dir, app.PHONE_INBOX, ".._.._x_y_.bin")
    disk_usage = app.shutil.disk_usage
    monkeypatch.setattr(app.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=1))
    assert "espaço" in send_plan(phone, [{"name": "b", "size": 5}])[1]["error"]
    monkeypatch.setattr(app.shutil, "disk_usage", disk_usage)
    monkeypatch.setattr(app, "PHONE_MAX_UPLOADS", 1)
    assert "demais" in send_plan(phone, [{"name": "c", "size": 5}])[1]["error"]
    assert upload(phone, "nao-existe", 0, b"1")[0] == 400
    other = phone.open_session("127.0.0.1", "Mozilla/5.0 (Linux; Android 14)")
    status, _, data = phone_call(
        phone, "PUT", f"/api/upload?t={job['id']}&offset=0", {}, b"1", cookie=f"salvai={other}"
    )
    assert status == 400 and "não existe" in json_body(data)["error"]
    big = app.PHONE_MAX_CHUNK + 1
    status, _, data = phone_call(phone, "PUT", f"/api/upload?t={job['id']}&offset=0", {"Content-Length": str(big)}, b"")
    assert status == 400 and "grande" in json_body(data)["error"]
    assert upload(phone, job["id"], 0, b"") == (200, {"received": 0, "done": False})
    with pytest.raises(ValueError):
        phone.receive(types.SimpleNamespace(headers={}), phone.session_for(device_cookie(phone)[7:]), {})
    job["writing"] = True
    assert upload(phone, job["id"], 0, b"1") == (409, {"received": 0})
    job["writing"] = False
    monkeypatch.setattr(app, "write_part", lambda *a: (_ for _ in ()).throw(PermissionError("negado")))
    status, reply = upload(phone, job["id"], 0, b"1")
    assert status == 400 and "gravar" in reply["error"] and job["writing"] is False


def test_phone_send_needs_csrf_header(phone):
    port = phone.server.server_address[1]
    cookie = {"Cookie": device_cookie(phone)}
    for method, path in (("POST", "/api/send"), ("PUT", "/api/upload?t=x&offset=0"), ("POST", "/api/add")):
        status, _, data = app_request(port, method, path, cookie)
        assert status == 403 and json_body(data)["error"] == "origem inválida"
    status, _, _ = app_request(
        port, "POST", "/api/send", {**cookie, "X-Salvai": "1", "Origin": "http://evil.com"}, b"{}"
    )
    assert status == 403


def app_request(port, method, path, headers, body=b"{}"):
    return http_request(port, method, path, headers, body)


def test_drain_body_reads_only_what_is_safe():
    reads = []

    def handler(length, data):
        source = types.SimpleNamespace(read=lambda n: reads.append(n) or (data.pop(0) if data else b""))
        return types.SimpleNamespace(headers={"Content-Length": length}, rfile=source)

    app.drain_body(handler("5", [b"abc", b"de"]))
    assert reads == [5, 2]
    reads.clear()
    app.drain_body(handler("9", [b"abc"]))
    assert reads == [9, 6]
    reads.clear()
    for length in ("", "-1", "x", str(app.PHONE_MAX_CHUNK + 1)):
        app.drain_body(handler(length, [b"a"]))
    assert reads == []
    app.drain_body(types.SimpleNamespace(headers={}))


def test_phone_partial_upload_and_stop_drops_parts(phone, api):
    session = phone.session_for(phone.open_session("127.0.0.1", "Mozilla/5.0 (iPhone)"))
    reply = phone.plan_uploads(session, [{"name": "video.mp4", "size": 10}])
    job = phone.uploads[reply["uploads"][0]["id"]]
    sent = []
    handler = types.SimpleNamespace(
        headers={"Content-Length": "10"},
        rfile=types.SimpleNamespace(read=lambda n: b"" if sent else sent.append(1) or b"1234"),
        _json=lambda code, payload: sent.append((code, payload)),
    )
    phone.receive(handler, session, {"t": job["id"], "offset": "0"})
    assert sent[-1] == (200, {"received": 4, "done": False}) and job["part"].read_bytes() == b"1234"
    job["touched"] = 0.0
    assert phone.incoming() is None
    phone.stop()
    assert phone.uploads == {} and not job["part"].exists()


def test_api_phone_received_and_open(api, monkeypatch):
    notes, opened = [], []
    monkeypatch.setattr(api._tray, "notify", lambda title, msg: notes.append(title))
    monkeypatch.setattr(app.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    api._phone_received(None)
    assert notes == [] and api._window.js[-1].endswith("app.phoneChanged()")
    api._window.fail.add("run_js")
    api._phone_received({"device": "iPhone", "count": 1, "dest": Path("a.jpg")})
    assert notes == ["Arquivo recebido do celular"]
    assert api.phone_open_received("x") is False and opened == []
    target = Path(api._out_dir, app.PHONE_INBOX, "a.jpg")
    target.parent.mkdir()
    target.write_bytes(b"1")
    api._phone.received.append({"id": "r1", "path": target})
    assert api.phone_open_received("r1") is True and opened[-1][-1] == str(target)
    api.phone_open_inbox()
    assert opened[-1] == target.parent


FFMPEG_INFO = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'a.mp4':
  Duration: 00:02:24.71, start: 0.000000, bitrate: 9000 kb/s
  Stream #0:0[0x1](und): Video: vp9 (Profile 0) (vp09 / 0x39307076), yuv420p(tv), 3840x2160, 30 fps (default)
  Stream #0:1[0x2](eng): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s (default)
  Stream #0:2: Video: mjpeg (Baseline), yuvj420p, 600x600 (attached pic)
"""


def test_probe_media_and_phone_support(monkeypatch):
    seen = []
    monkeypatch.setattr(
        app.subprocess, "run", lambda args, **kw: seen.append(args) or types.SimpleNamespace(stderr=FFMPEG_INFO)
    )
    info = app.probe_media("ffmpeg.exe", Path("a.mp4"))
    assert info == {"duration": 144.71, "video": [("vp9", info["video"][0][1])], "audio": ["aac"]}
    assert seen[0][:4] == ["ffmpeg.exe", "-hide_banner", "-nostdin", "-i"]
    monkeypatch.setattr(app.subprocess, "run", lambda args, **kw: types.SimpleNamespace(stderr="nada"))
    assert app.probe_media("ffmpeg.exe", Path("a.mp4")) == {"duration": 0.0, "video": [], "audio": []}
    h264 = {"video": [("h264", " (High) (avc1), yuv420p")], "audio": ["aac"]}
    supported = lambda name, info: app.plays_on_phone(Path(name), info)
    assert supported("foto.jpg", {"video": [("mjpeg", "")], "audio": []})
    assert supported("a.mp4", h264) and supported("a.MOV", h264)
    assert not supported("a.mkv", h264)
    assert not supported("a.mp4", {"video": [("h264", " (High 10), yuv420p10le")], "audio": ["aac"]})
    assert not supported("a.mp4", {"video": [("vp9", "")], "audio": ["aac"]})
    assert not supported("a.mp4", {"video": [("h264", "")], "audio": ["opus"]})
    assert supported("a.mp3", {"video": [], "audio": ["mp3"]})
    assert not supported("a.m4a", {"video": [], "audio": ["alac"]})


class FakeFfmpeg:
    calls: list = []
    made = 3
    code = None

    def __init__(self, args, **kw):
        FakeFfmpeg.calls.append(args)
        first = int(args[args.index("-start_number") + 1])
        pattern = args[args.index("-hls_segment_filename") + 1]
        for n in range(first, first + FakeFfmpeg.made):
            Path(pattern % n).write_bytes(b"ts%d" % n)
        self.returncode = FakeFfmpeg.code

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def fake_ffmpeg(monkeypatch, no_sleep):
    FakeFfmpeg.calls, FakeFfmpeg.made, FakeFfmpeg.code = [], 3, None
    monkeypatch.setattr(app.subprocess, "Popen", FakeFfmpeg)
    return FakeFfmpeg


def test_media_stream_converts_on_demand(tmp_path, monkeypatch, fake_ffmpeg):
    info = {"duration": 200.5, "video": [("vp9", "")], "audio": ["aac"]}
    stream = app.MediaStream("ffmpeg.exe", tmp_path / "a.mkv", info, tmp_path / "s")
    lines = stream.playlist().decode().splitlines()
    assert stream.count == 51 and lines[-1] == "#EXT-X-ENDLIST" and lines[-3] == "#EXTINF:0.500,"
    assert f"/api/stream/seg?t={stream.token}&n=0" in lines
    assert stream.segment(-1) is None and stream.segment(51) is None
    assert stream.segment(0).read_bytes() == b"ts0"
    assert stream.segment(2).read_bytes() == b"ts2" and len(fake_ffmpeg.calls) == 1
    args = fake_ffmpeg.calls[0]
    assert "libx264" in args and args[args.index("-ss") + 1] == "0" and args[args.index("-start_number") + 1] == "0"
    monkeypatch.setattr(app, "STREAM_WAIT", 0)
    assert stream.segment(5) is None and len(fake_ffmpeg.calls) == 1
    assert stream.segment(30).read_bytes() == b"ts30" and len(fake_ffmpeg.calls) == 2
    assert fake_ffmpeg.calls[1][fake_ffmpeg.calls[1].index("-ss") + 1] == "120"
    assert stream.segment(1).read_bytes() == b"ts1" and len(stream.runs) == 2
    monkeypatch.setattr(app, "STREAM_AHEAD", 1)
    assert stream.segment(30) and stream.proc is None
    assert stream.segment(33).read_bytes() == b"ts33" and len(fake_ffmpeg.calls) == 3
    monkeypatch.setattr(app, "STREAM_WAIT", 5)
    fake_ffmpeg.made, fake_ffmpeg.code = 0, 0
    assert stream.segment(45) is None and len(fake_ffmpeg.calls) == 4
    stream.close()
    stream.close()
    assert not (tmp_path / "s").exists()
    music = app.MediaStream(
        "ffmpeg.exe", tmp_path / "a.opus", {"duration": 4, "video": [], "audio": ["opus"]}, tmp_path
    )
    assert music.count == 1 and "-vn" in music.command(0, tmp_path) and "libx264" not in music.command(0, tmp_path)


def test_phone_play_streams_unsupported_files(phone, api, monkeypatch, fake_ffmpeg):
    movie = Path(api._out_dir, "filme.mkv")
    movie.write_bytes(b"1")
    api._remember(str(movie))
    key = app.file_key(movie)
    play = lambda: phone_call(phone, "GET", f"/api/play?id={key}")
    assert phone_call(phone, "GET", "/api/play?id=x")[0] == 400
    monkeypatch.setattr(app, "probe_media", lambda ff, path: (_ for _ in ()).throw(OSError("sem ffmpeg")))
    assert json_body(play()[2]) == {"direct": True}
    info = {"duration": 0.0, "video": [("vp9", "")], "audio": ["aac"]}
    monkeypatch.setattr(app, "probe_media", lambda ff, path: info)
    assert json_body(play()[2]) == {"direct": True}
    info.update(duration=10.0)
    status, _, data = play()
    url = json_body(data)["stream"]
    token = phone.stream.token
    assert status == 200 and url == f"/api/stream/index.m3u8?t={token}"
    first = phone.stream
    status, headers, data = phone_call(phone, "GET", url, cookie=False)
    assert status == 200 and headers["Content-Type"] == "application/vnd.apple.mpegurl"
    assert f"/api/stream/seg?t={token}&n=2" in data.decode()
    assert phone_call(phone, "HEAD", url, cookie=False)[2] == b""
    status, headers, data = phone_call(phone, "GET", f"/api/stream/seg?t={token}&n=0", cookie=False)
    assert status == 200 and headers["Content-Type"] == "video/mp2t" and data == b"ts0"
    assert phone_call(phone, "GET", f"/api/stream/seg?t={token}&n=9")[0] == 404
    assert phone_call(phone, "GET", f"/api/stream/outra?t={token}")[0] == 404
    assert phone_call(phone, "GET", "/api/stream/index.m3u8?t=errado", cookie=False)[0] == 403
    status, _, data = phone_call(phone, "GET", "/api/stream/index.m3u8?t=errado")
    assert status == 404 and "não está mais aberto" in json_body(data)["error"]
    play()
    assert phone.stream is not first and phone.stream.token != token
    phone.end_stream(first)
    assert phone.stream
    token = phone.stream.token
    phone.revoke(phone.stream_session["id"])
    assert phone_call(phone, "GET", f"/api/stream/index.m3u8?t={token}", cookie=False)[0] == 403
    phone.end_stream()
    phone.end_stream()
    assert phone.stream is None and phone.stream_owner(token) is None


def test_phone_stop_and_idle_end_the_stream(phone, api, monkeypatch, fake_ffmpeg):
    info = {"duration": 8.0, "video": [], "audio": ["opus"]}
    folder = Path(api._out_dir, "stream")
    phone.stream = app.MediaStream("ffmpeg.exe", Path("a.opus"), info, folder)
    phone.stream.touched = 0
    sentinel = object()
    monkeypatch.setattr(app.time, "sleep", lambda s: setattr(phone, "server", None))
    server, phone.server = phone.server, sentinel
    phone.watch_idle(sentinel)
    assert phone.stream is None and not folder.exists()
    phone.server = server
    phone.stream = app.MediaStream("ffmpeg.exe", Path("a.opus"), info, folder)
    phone.stop()
    assert phone.stream is None and not folder.exists()
