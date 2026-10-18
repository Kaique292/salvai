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


def phone_call(phone, method, path, headers=None, body=None, host=None, cookie=True):
    all_headers = {"Cookie": f"salvai={phone.token}"} if cookie else {}
    all_headers.update(headers or {})
    return http_request(phone.server.server_address[1], method, path, all_headers, body, host)


def test_phone_entry_and_page(phone):
    status, headers, _ = phone_call(phone, "GET", f"/?k={phone.token}", cookie=False)
    assert status == 303 and headers["Location"] == "/" and "HttpOnly" in headers["Set-Cookie"]
    status, headers, page = phone_call(phone, "GET", "/")
    assert status == 200 and b"Salva" in page and "Content-Security-Policy" in headers
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
    Path(api._out_dir, "musica.mp3").write_bytes(b"12345")
    Path(api._out_dir, "doc.pdf").write_bytes(b"segredo")
    status, _, data = phone_call(phone, "GET", "/api/files")
    assert [f["name"] for f in json_body(data)["files"]] == ["musica.mp3"]
    status, headers, data = phone_call(phone, "GET", "/api/file?path=musica.mp3&dl=1")
    assert status == 200 and data == b"12345" and "attachment" in headers["Content-Disposition"]
    assert phone_call(phone, "HEAD", "/api/file?path=musica.mp3")[2] == b""
    assert phone_call(phone, "GET", "/api/file?path=doc.pdf")[0] == 400
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
        server.devices["x"] = {"name": "iPhone", "seen": time.time()}
        assert server.status()["devices"] == ["iPhone"]
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
