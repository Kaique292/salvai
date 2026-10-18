import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = Path(tempfile.mkdtemp(prefix="salvai-tests-"))
for variable in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "USERPROFILE"):
    (SANDBOX / variable).mkdir(parents=True, exist_ok=True)
    os.environ[variable] = str(SANDBOX / variable)
os.environ.pop("YTD_FORCE_DENO", None)
sys.path.insert(0, str(ROOT / "src"))

import app

app._engine_ready.wait()
REAL_ENGINE = app.yt_dlp


def wait_until(condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        return [h(*args) for h in self.handlers]


class FakeWindow:
    def __init__(self):
        self.js = []
        self.calls = []
        self.events = types.SimpleNamespace(
            shown=FakeEvent(), closed=FakeEvent(), closing=FakeEvent(), loaded=FakeEvent()
        )
        self.cookies = []
        self.dialog_result = None
        self.fail = set()

    def _maybe_fail(self, name):
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError(f"{name} falhou")

    def run_js(self, code):
        self._maybe_fail("run_js")
        self.js.append(code)

    def show(self):
        self._maybe_fail("show")

    def hide(self):
        self._maybe_fail("hide")

    def restore(self):
        self._maybe_fail("restore")

    def destroy(self):
        self._maybe_fail("destroy")

    def clear_cookies(self):
        self._maybe_fail("clear_cookies")

    def get_cookies(self):
        self._maybe_fail("get_cookies")
        return self.cookies

    def create_file_dialog(self, kind, directory=None):
        self.calls.append(("dialog", kind, directory))
        return self.dialog_result


class FakeCookieJar:
    def __init__(self):
        self.cookies = []

    def set_cookie(self, cookie):
        self.cookies.append(cookie)


class FakeYDL:
    script = {}
    created = []

    def __init__(self, opts):
        self.opts = opts
        self.cookiejar = FakeCookieJar()
        FakeYDL.created.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _behavior(self, url):
        for key, value in FakeYDL.script.items():
            if key in url:
                return value
        return {"info": {"id": "x", "title": "Vídeo", "extractor_key": "Generic"}}

    def extract_info(self, url, download=True, process=True):
        behavior = self._behavior(url)
        if download and "download" in behavior:
            return behavior["download"](self, url)
        if "error" in behavior:
            raise behavior["error"]
        return dict(behavior["info"])

    def process_ie_result(self, info, download=True):
        behavior = self._behavior(info.get("webpage_url", info.get("url", "")))
        return behavior["download"](self, info.get("webpage_url", ""))

    def prepare_filename(self, info):
        return os.path.join(os.path.dirname(self.opts["outtmpl"]), f"{info.get('title', 'x')}.mp4")


def make_engine(version="2026.8.19", extractors=None, cookies=None, cookies_error=None):
    def extract_cookies_from_browser(browser, logger=None):
        if cookies_error:
            raise cookies_error
        return cookies or []

    return types.SimpleNamespace(
        YoutubeDL=FakeYDL,
        version=types.SimpleNamespace(__version__=version),
        extractor=types.SimpleNamespace(gen_extractor_classes=lambda: extractors or []),
        cookies=types.SimpleNamespace(extract_cookies_from_browser=extract_cookies_from_browser),
    )


@pytest.fixture
def fake_engine(monkeypatch):
    FakeYDL.script = {}
    FakeYDL.created = []
    engine = make_engine()
    monkeypatch.setattr(app, "yt_dlp", engine)
    return engine


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(app, "CONFIG_PATH", data / "config.json")
    monkeypatch.setattr(app, "BIN_DIR", data / "bin")
    monkeypatch.setattr(app, "CACHE_DIR", data / "cache")
    monkeypatch.setattr(app, "WEBVIEW_DIR", data / "webview")
    monkeypatch.setattr(app, "WEBVIEW_CLEAR_FLAG", data / "clear-webview-cache")
    monkeypatch.setattr(app, "SESSIONS_PATH", data / "sessions.dat")
    monkeypatch.setattr(app, "BRIDGE_PATH", data / "bridge.json")
    monkeypatch.setattr(app, "ENGINE_DIR", data / "engine")
    monkeypatch.setattr(app, "SAVED_PATH", data / "saved.json")
    monkeypatch.setattr(app, "MCP_DIR", data / "mcp")
    monkeypatch.setattr(app, "MCP_PATH", data / "mcp" / "salvai-mcp.exe")
    monkeypatch.setattr(app, "MCP_VERSION_PATH", data / "mcp" / "version.txt")
    monkeypatch.setattr(app, "_sessions_cache", None)
    return data


@pytest.fixture
def api(monkeypatch, tmp_path, isolated, fake_engine):
    monkeypatch.setattr(app, "ffmpeg_dir", lambda: "ffmpeg")
    monkeypatch.setattr(app, "ensure_js_runtime", lambda: {"node": {}})
    monkeypatch.setattr(app, "js_runtimes", lambda: {"node": {}})
    instance = app.Api()
    instance._window = FakeWindow()
    out = tmp_path / "Downloads"
    out.mkdir()
    instance._out_dir = str(out)
    yield instance
    instance._phone.stop()
    with instance._cv:
        instance._items.clear()
        instance._order.clear()


def zip_bytes(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, data=b"", headers=None):
        self._data = io.BytesIO(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def read(self, size=-1):
        return self._data.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_request(port, method, path, headers=None, body=None, host=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    all_headers = {"Host": host or f"127.0.0.1:{port}"}
    all_headers.update(headers or {})
    connection.request(method, path, body=body, headers=all_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), data


def json_body(data):
    return json.loads(data or b"{}")


@pytest.fixture
def no_sleep(monkeypatch):
    real_sleep = time.sleep
    monkeypatch.setattr(app.time, "sleep", lambda seconds: real_sleep(0))
    return real_sleep


@pytest.fixture
def instant_timer(monkeypatch):
    class Instant:
        def __init__(self, delay, function, args=None, kwargs=None):
            self.function, self.args, self.kwargs = function, args or (), kwargs or {}

        def start(self):
            threading.Thread(target=self.function, args=self.args, kwargs=self.kwargs, daemon=True).start()

    monkeypatch.setattr(app.threading, "Timer", Instant)
    return Instant
