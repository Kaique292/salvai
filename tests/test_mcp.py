import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import salvai_mcp


class FakeApp(BaseHTTPRequestHandler):
    responses = {}
    requests = []

    def log_message(self, *args):
        pass

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        FakeApp.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        status, payload = FakeApp.responses.get(self.path.split("?")[0], (200, {"ok": True}))
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _answer
    do_POST = _answer


@pytest.fixture
def fake_app(monkeypatch, tmp_path):
    FakeApp.responses, FakeApp.requests = {}, []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bridge_file = tmp_path / "bridge.json"
    bridge_file.write_text(json.dumps({"port": server.server_address[1], "token": "segredo"}))
    monkeypatch.setattr(salvai_mcp, "BRIDGE_PATH", bridge_file)
    yield server
    server.shutdown()
    server.server_close()


def test_find_app(monkeypatch, tmp_path):
    monkeypatch.delenv("SALVAI_EXE", raising=False)
    monkeypatch.setattr(salvai_mcp, "CONFIG_PATH", tmp_path / "config.json")
    exe = tmp_path / "Salvai.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv("SALVAI_EXE", str(exe))
    assert salvai_mcp.find_app() == str(exe)
    monkeypatch.setenv("SALVAI_EXE", str(tmp_path / "nao.exe"))
    monkeypatch.setattr(salvai_mcp.sys, "frozen", True, raising=False)
    monkeypatch.setattr(salvai_mcp.sys, "executable", str(tmp_path / "salvai-mcp.exe"))
    assert salvai_mcp.find_app() == str(exe)
    exe.unlink()
    assert salvai_mcp.find_app() is None


def test_read_bridge(monkeypatch, tmp_path):
    monkeypatch.setattr(salvai_mcp, "BRIDGE_PATH", tmp_path / "nao.json")
    assert salvai_mcp.read_bridge() is None


def test_request_success_and_errors(fake_app):
    bridge = salvai_mcp.read_bridge()
    assert salvai_mcp.request(bridge, "POST", "/search", {"query": "x"}) == {"ok": True}
    assert FakeApp.requests[-1][2] == "Bearer segredo" and json.loads(FakeApp.requests[-1][3]) == {"query": "x"}
    FakeApp.responses["/files"] = (400, {"error": "arquivo não encontrado"})
    with pytest.raises(ToolError, match="arquivo não encontrado"):
        salvai_mcp.request(bridge, "GET", "/files")
    FakeApp.responses["/files"] = (500, b"nao-e-json")
    with pytest.raises(ToolError, match="500"):
        salvai_mcp.request(bridge, "GET", "/files")


def test_bridge_is_alive(fake_app):
    assert salvai_mcp.bridge_is_alive(None) is False
    assert salvai_mcp.bridge_is_alive(salvai_mcp.read_bridge()) is True
    FakeApp.responses["/status"] = (401, {"error": "token"})
    assert salvai_mcp.bridge_is_alive(salvai_mcp.read_bridge()) is False


def test_open_bridge_when_running(fake_app):
    assert salvai_mcp.open_bridge()["token"] == "segredo"


def test_open_bridge_starts_app(monkeypatch, tmp_path, fake_app):
    real = salvai_mcp.read_bridge()
    monkeypatch.setattr(salvai_mcp, "BRIDGE_PATH", tmp_path / "ainda-nao.json")
    launched = []

    def popen(args, **kwargs):
        launched.append(args)
        assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        (tmp_path / "ainda-nao.json").write_text(json.dumps(real))

    monkeypatch.setattr(salvai_mcp.subprocess, "Popen", popen)
    monkeypatch.setattr(salvai_mcp, "find_app", lambda: "C:/Salvai.exe")
    monkeypatch.setattr(salvai_mcp.time, "sleep", lambda s: None)
    assert salvai_mcp.open_bridge()["token"] == "segredo" and launched == [["C:/Salvai.exe"]]


def test_open_bridge_without_app(monkeypatch, tmp_path):
    monkeypatch.setattr(salvai_mcp, "BRIDGE_PATH", tmp_path / "nao.json")
    monkeypatch.setattr(salvai_mcp, "find_app", lambda: None)
    with pytest.raises(ToolError, match="não encontrei"):
        salvai_mcp.open_bridge()


def test_open_bridge_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(salvai_mcp, "BRIDGE_PATH", tmp_path / "nao.json")
    monkeypatch.setattr(salvai_mcp, "find_app", lambda: "C:/Salvai.exe")
    monkeypatch.setattr(salvai_mcp.subprocess, "Popen", lambda *a, **k: None)
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(salvai_mcp.time, "time", lambda: next(clock))
    monkeypatch.setattr(salvai_mcp.time, "sleep", lambda s: None)
    with pytest.raises(ToolError, match="não respondeu"):
        salvai_mcp.open_bridge()


def test_tools(fake_app, monkeypatch):
    FakeApp.responses["/status"] = (200, {"app": "Salvaí"})
    assert salvai_mcp.salvai_status() == {"app": "Salvaí"}
    salvai_mcp.search_media("aula", limit=3, site="soundcloud")
    assert json.loads(FakeApp.requests[-1][3]) == {"query": "aula", "limit": 3, "site": "soundcloud"}
    item = salvai_mcp.DownloadItem(url="https://youtu.be/x", format="mp3", quality="320", folder="Música")
    salvai_mcp.download_media([item])
    assert json.loads(FakeApp.requests[-1][3])["items"][0]["folder"] == "Música"
    salvai_mcp.list_files("Música", depth=2)
    assert FakeApp.requests[-1][1] == "/files?folder=M%C3%BAsica&depth=2"
    salvai_mcp.move_file("a.mp3", "B")
    assert json.loads(FakeApp.requests[-1][3]) == {"path": "a.mp3", "folder": "B"}


def test_list_downloads_waits(fake_app, monkeypatch):
    states = iter(
        [
            {"downloads": [{"id": "a", "status": "downloading"}]},
            {"downloads": [{"id": "a", "status": "done"}]},
        ]
    )
    monkeypatch.setattr(salvai_mcp, "call", lambda method, path: next(states))
    monkeypatch.setattr(salvai_mcp.time, "sleep", lambda s: None)
    result = salvai_mcp.list_downloads(["a"], wait_seconds=60)
    assert result["all_finished"] is True
    monkeypatch.setattr(salvai_mcp, "call", lambda method, path: {"downloads": [{"id": "a", "status": "queued"}]})
    assert salvai_mcp.list_downloads(None, wait_seconds=0)["all_finished"] is False


def test_cleanup_leftovers(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    ours = tmp_path / "_MEI1"
    ours.mkdir()
    (ours / "salvai-mcp.marker").write_text("x")
    other = tmp_path / "_MEI2"
    other.mkdir()
    busy = tmp_path / "_MEI3"
    busy.mkdir()
    (busy / "salvai-mcp.marker").write_text("x")
    current = tmp_path / "_MEI4"
    current.mkdir()
    (current / "salvai-mcp.marker").write_text("x")
    monkeypatch.setattr(salvai_mcp.sys, "_MEIPASS", str(current), raising=False)
    real_rename = Path.rename
    monkeypatch.setattr(
        Path,
        "rename",
        lambda self, t: (_ for _ in ()).throw(PermissionError()) if self == busy else real_rename(self, t),
    )
    salvai_mcp.cleanup_leftovers()
    assert not ours.exists() and other.exists() and busy.exists() and current.exists()


def test_main_runs_server(monkeypatch):
    ran = []
    monkeypatch.setattr(salvai_mcp, "cleanup_leftovers", lambda: ran.append("cleanup"))
    monkeypatch.setattr(salvai_mcp.mcp, "run", lambda: ran.append("run"))
    salvai_mcp.main()
    assert "run" in ran


def test_find_app_uses_path_saved_by_app(monkeypatch, tmp_path):
    monkeypatch.delenv("SALVAI_EXE", raising=False)
    exe = tmp_path / "Downloads" / "Salvai.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    config = tmp_path / "config.json"
    monkeypatch.setattr(salvai_mcp, "CONFIG_PATH", config)
    monkeypatch.setattr(salvai_mcp.sys, "frozen", True, raising=False)
    monkeypatch.setattr(salvai_mcp.sys, "executable", str(tmp_path / "mcp" / "salvai-mcp.exe"))
    assert salvai_mcp.saved_app_path() is None and salvai_mcp.find_app() is None
    config.write_text(json.dumps({"app_path": str(exe)}), encoding="utf-8")
    assert salvai_mcp.find_app() == str(exe)
