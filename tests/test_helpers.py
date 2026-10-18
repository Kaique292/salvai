import ctypes
import email.utils
import hashlib
import importlib.metadata
import io
import ipaddress
import json
import os
import subprocess
import sys
import types
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from conftest import FakeResponse, FakeYDL, make_engine, zip_bytes

import app


class FakeSplash:
    def __init__(self, fail=False):
        self.texts, self.closed, self.fail = [], False, fail

    def update_text(self, text):
        if self.fail:
            raise RuntimeError("splash fechado")
        self.texts.append(text)

    def close(self):
        if self.fail:
            raise RuntimeError("splash fechado")
        self.closed = True


def test_splash_without_pyinstaller_does_nothing(monkeypatch):
    monkeypatch.setattr(app, "pyi_splash", None)
    app.splash_step(10, "x")
    app.splash_close()


def test_splash_sends_steps_and_closes(monkeypatch):
    splash = FakeSplash()
    monkeypatch.setattr(app, "pyi_splash", splash)
    app.splash_step(50, "Metade")
    app.splash_close()
    assert splash.texts == ["@50|Metade"] and splash.closed


def test_splash_errors_are_ignored(monkeypatch):
    monkeypatch.setattr(app, "pyi_splash", FakeSplash(fail=True))
    app.splash_step(1, "x")
    app.splash_close()


def test_version_key_orders_versions():
    assert app.version_key("2026.10.01") > app.version_key("2026.8.19")
    assert app.version_key("") == (0,)
    assert app.version_key(None) == (0,)


def test_bundled_engine_version(monkeypatch):
    assert app.bundled_engine_version() != "0"

    def broken(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(app.importlib.metadata, "version", broken)
    assert app.bundled_engine_version() == "0"


def test_activate_engine_update_picks_newer_zip(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "ENGINE_DIR", tmp_path)
    monkeypatch.setattr(app, "bundled_engine_version", lambda: "2026.8.19")
    (tmp_path / "yt-dlp-2026.1.1.zip").write_bytes(b"x")
    assert app.activate_engine_update() is None
    (tmp_path / "yt-dlp-2027.2.3.zip").write_bytes(b"x")
    before = list(sys.path)
    try:
        assert app.activate_engine_update() == "2027.2.3"
        assert sys.path[0].endswith("yt-dlp-2027.2.3.zip")
    finally:
        sys.path[:] = before


def test_engine_loader_sets_module(monkeypatch):
    monkeypatch.setattr(app, "yt_dlp", None)
    app._engine_ready.clear()
    app._load_engine()
    assert app.engine() is sys.modules["yt_dlp"]


def test_read_version(monkeypatch, tmp_path):
    assert app.read_version() == (app.BASE.parent / "version.txt").read_text().strip()
    monkeypatch.setattr(app, "BASE", tmp_path / "vazio" / "src")
    assert app.read_version() == "0.0.0"


def test_migrate_old_data(tmp_path):
    old, new = tmp_path / "YouTubeDownloader", tmp_path / "Salvai"
    app._migrate_old_data(old, new)
    assert not new.exists()
    old.mkdir()
    (old / "config.json").write_text("antigo-mais-novo")
    (old / "bin").mkdir()
    (old / "bin" / "ffmpeg.exe").write_text("x")
    (old / "sessions.dat").write_text("velho")
    new.mkdir()
    (new / "sessions.dat").write_text("novo")
    os.utime(new / "sessions.dat", (2_000_000_000, 2_000_000_000))
    (new / "config.json").write_text("novo-mais-velho")
    os.utime(new / "config.json", (1_000_000_000, 1_000_000_000))
    app._migrate_old_data(old, new)
    assert (new / "config.json").read_text() == "antigo-mais-novo"
    assert (new / "sessions.dat").read_text() == "novo"
    assert (new / "bin" / "ffmpeg.exe").exists()
    assert not old.exists()


def test_migrate_old_data_ignores_os_errors(monkeypatch, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "a.txt").write_text("x")

    def fail(*args):
        raise OSError("em uso")

    monkeypatch.setattr(app.shutil, "move", fail)
    app._migrate_old_data(old, tmp_path / "new")
    assert (old / "a.txt").exists()


def test_ffmpeg_from_packed_zip(monkeypatch, tmp_path, isolated):
    base = tmp_path / "bundle"
    base.mkdir()
    (base / "ffmpeg.zip").write_bytes(zip_bytes({"ffmpeg-v7.exe": b"binario"}))
    monkeypatch.setattr(app, "BASE", base)
    assert app.ffmpeg_dir() == str(app.BIN_DIR)
    assert (app.BIN_DIR / "ffmpeg.exe").read_bytes() == b"binario"
    assert (app.BIN_DIR / "ffmpeg.version").read_text() == "ffmpeg-v7.exe"
    (app.BIN_DIR / "ffmpeg.exe").write_bytes(b"mantido")
    app.ffmpeg_dir()
    assert (app.BIN_DIR / "ffmpeg.exe").read_bytes() == b"mantido"


def test_ffmpeg_from_imageio(monkeypatch, tmp_path, isolated):
    monkeypatch.setattr(app, "BASE", tmp_path / "sem-zip")
    package = tmp_path / "imageio_ffmpeg"
    (package / "binaries").mkdir(parents=True)
    (package / "binaries" / "ffmpeg-win.exe").write_bytes(b"do-pacote")
    fake = types.SimpleNamespace(__file__=str(package / "__init__.py"), get_ffmpeg_exe=lambda: "")
    monkeypatch.setattr(app, "imageio_ffmpeg", fake)
    app.ffmpeg_dir()
    assert (app.BIN_DIR / "ffmpeg.exe").read_bytes() == b"do-pacote"


def test_ffmpeg_from_imageio_fallback(monkeypatch, tmp_path, isolated):
    monkeypatch.setattr(app, "BASE", tmp_path / "sem-zip")
    exe = tmp_path / "outro" / "ffmpeg-sistema.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"sistema")
    fake = types.SimpleNamespace(__file__=str(tmp_path / "pkg" / "__init__.py"), get_ffmpeg_exe=lambda: str(exe))
    monkeypatch.setattr(app, "imageio_ffmpeg", fake)
    app.ffmpeg_dir()
    assert (app.BIN_DIR / "ffmpeg.exe").read_bytes() == b"sistema"


def test_js_runtimes(monkeypatch, isolated):
    monkeypatch.setattr(app, "system_runtimes", lambda: ("node",))
    assert app.js_runtimes() == {"node": {}}
    monkeypatch.setenv("YTD_FORCE_DENO", "1")
    assert app.js_runtimes() == {}
    app.BIN_DIR.mkdir(parents=True)
    (app.BIN_DIR / "deno.exe").write_bytes(b"x")
    assert app.js_runtimes() == {"deno": {"path": str(app.BIN_DIR / "deno.exe")}}


def test_system_runtimes_uses_which(monkeypatch):
    app.system_runtimes.cache_clear()
    monkeypatch.setattr(app.shutil, "which", lambda name: name == "deno" and "C:/deno.exe")
    try:
        assert app.system_runtimes() == ("deno",)
    finally:
        app.system_runtimes.cache_clear()


def test_ensure_js_runtime_already_available(monkeypatch):
    monkeypatch.setattr(app, "js_runtimes", lambda: {"node": {}})
    assert app.ensure_js_runtime() == {"node": {}}


def test_ensure_js_runtime_downloads_and_verifies(monkeypatch, isolated):
    monkeypatch.setenv("YTD_FORCE_DENO", "1")
    archive = zip_bytes({"deno.exe": b"deno-binario"})
    digest = hashlib.sha256(archive).hexdigest().upper()

    def urlopen(url, timeout=0):
        return FakeResponse(f"Hash : {digest}".encode() if url.endswith(".sha256sum") else archive)

    monkeypatch.setattr(app.urllib.request, "urlopen", urlopen)
    result = app.ensure_js_runtime()
    assert result == {"deno": {"path": str(app.BIN_DIR / "deno.exe")}}
    assert (app.BIN_DIR / "deno.exe").read_bytes() == b"deno-binario"
    assert not (app.BIN_DIR / "deno.zip.part").exists()


def test_ensure_js_runtime_rejects_bad_hash(monkeypatch, isolated):
    monkeypatch.setenv("YTD_FORCE_DENO", "1")

    def urlopen(url, timeout=0):
        return FakeResponse(b"Hash : " + b"0" * 64 if url.endswith(".sha256sum") else b"adulterado")

    monkeypatch.setattr(app.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="não confere"):
        app.ensure_js_runtime()
    assert not (app.BIN_DIR / "deno.exe").exists()


@pytest.mark.parametrize(
    ("url", "youtube", "vid"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", True, "jNQXAC9IVRw"),
        ("https://youtu.be/jNQXAC9IVRw?si=x", True, "jNQXAC9IVRw"),
        ("https://www.youtube.com/channel/abc", True, None),
        ("https://vimeo.com/watch?v=jNQXAC9IVRw", False, None),
        ("", False, None),
    ],
)
def test_youtube_detection(url, youtube, vid):
    assert app.is_youtube(url) is youtube
    assert app.youtube_id(url) == vid


def test_hosts_sites_and_labels():
    assert app.host_of("https://www.instagram.com/p/x") == "instagram.com"
    assert app.host_of("nada") == ""
    assert app.login_site_for("https://m.facebook.com/watch") == "facebook"
    assert app.login_site_for("https://twitter.com/a/status/1") == "x"
    assert app.login_site_for("https://vimeo.com/1") is None
    assert app.site_label({"extractor_key": "TwitterBroadcast"}, "https://x.com") == "X"
    assert app.site_label(None, "https://player.vimeo.com/1") == "Vimeo"
    assert app.site_label({}, "https://exemplo.org/v") == "exemplo.org"


def test_supported_site(monkeypatch):
    class Generic:
        @staticmethod
        def ie_key():
            return "Generic"

        @staticmethod
        def suitable(url):
            return True

    class Vimeo:
        @staticmethod
        def ie_key():
            return "Vimeo"

        @staticmethod
        def suitable(url):
            return "vimeo" in url

    monkeypatch.setattr(app, "yt_dlp", make_engine(extractors=[Generic, Vimeo]))
    app.supported_site.cache_clear()
    try:
        assert app.supported_site("https://vimeo.com/1")
        assert not app.supported_site("https://exemplo.org/v")
    finally:
        app.supported_site.cache_clear()


def test_dpapi_roundtrip_and_error():
    secret = app.dpapi(b'{"conta": 1}', protect=True)
    assert secret != b'{"conta": 1}'
    assert app.dpapi(secret, protect=False) == b'{"conta": 1}'
    with pytest.raises(OSError):
        app.dpapi(b"nao-e-um-blob", protect=False)


def test_sessions_are_encrypted_and_cached(isolated):
    assert app.load_sessions() == {}
    app.save_sessions({"x": {"cookies": [], "since": 1}})
    assert b"cookies" not in app.SESSIONS_PATH.read_bytes()
    app._sessions_cache = None
    assert app.load_sessions() == {"x": {"cookies": [], "since": 1}}
    app.save_sessions({})
    assert not app.SESSIONS_PATH.exists()


def test_make_ydl_loads_session_cookies(isolated, fake_engine):
    cookie = {"name": "sessionid", "value": "abc", "domain": ".instagram.com", "path": "", "secure": 1, "expires": None}
    app.save_sessions({"instagram": {"cookies": [cookie], "since": 1}})
    ydl = app.make_ydl({})
    assert isinstance(ydl, FakeYDL)
    assert ydl.cookiejar.cookies[0].name == "sessionid" and ydl.cookiejar.cookies[0].path == "/"


def test_cookies_from_webview():
    good = SimpleCookie()
    good["sessionid"] = "abc"
    good["sessionid"]["domain"] = ".instagram.com"
    good["sessionid"]["path"] = "/"
    good["sessionid"]["secure"] = True
    good["sessionid"]["expires"] = email.utils.formatdate(2_000_000_000, usegmt=True)
    old = SimpleCookie()
    old["velho"] = "1"
    old["velho"]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    broken = SimpleCookie()
    broken["quebrado"] = "1"
    broken["quebrado"]["expires"] = "data invalida"
    result = app.cookies_from_webview([good, old, broken])
    assert result[0] == {
        "name": "sessionid",
        "value": "abc",
        "domain": ".instagram.com",
        "path": "/",
        "secure": True,
        "expires": 2_000_000_000,
    }
    assert result[1]["expires"] is None and result[2]["expires"] is None
    assert result[2]["path"] == "/" and result[2]["domain"] == ""
    assert app.cookies_from_webview(None) == []


def test_quiet_logger_accepts_everything():
    logger = app._QuietLogger()
    logger.debug("a")
    logger.info("b")
    logger.warning("c", only_once=True)
    logger.error("d")


@pytest.mark.parametrize(
    ("message", "url", "kind"),
    [
        ("ERROR: Unsupported URL: https://x", "https://exemplo.org", "unsupported"),
        ("HTTP Error 429: Too Many Requests", "https://www.tiktok.com/a", "ratelimit"),
        ("This content is unreachable", "https://www.instagram.com/stories/a/1/", "login"),
        ("Requested content requires login. Use --cookies", "https://www.instagram.com/reel/a/", "login"),
        ("login required", "https://vimeo.com/1", "other"),
        ("There's no video in this tweet", "https://x.com/a/status/1", "novideo"),
        ("Video unavailable", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "unavailable"),
        ("not available in your country (geo restricted)", "https://exemplo.org", "geo"),
        ("Unexpected response; please report this issue", "https://www.tiktok.com/a", "blocked"),
        ("algo estranho", "https://exemplo.org", "other"),
    ],
)
def test_friendly_error(isolated, message, url, kind):
    assert app.friendly_error(Exception(message), url)[0] == kind


def test_friendly_error_when_account_connected(isolated):
    app.save_sessions({"instagram": {"cookies": [], "since": 1}})
    kind, message = app.friendly_error(Exception("login required"), "https://www.instagram.com/p/x")
    assert kind == "noaccess" and "reconecte" in message


def test_friendly_error_mentions_private_profiles(isolated):
    kind, message = app.friendly_error(Exception("private account, log in"), "https://www.tiktok.com/@a/video/1")
    assert kind == "login" and "privado" in message
    kind, message = app.friendly_error(Exception("log in"), "https://x.com/a/status/1")
    assert kind == "login" and "privado" not in message


@pytest.mark.parametrize(
    ("fmt", "quality", "expected"),
    [
        ("mp3", "320kbps", ("MP3", "320 kbps")),
        ("Áudio", "192 k", ("MP3", "192 kbps")),
        ("mp4", "1080p", ("MP4", "1080p")),
        ("mp4", "4k", ("MP4", "2160p (4K)")),
        ("mp4", "melhor", ("MP4", "Máxima")),
        ("mp4", None, ("MP4", "Máxima")),
        ("mp4", "8k", ("MP4", "Máxima")),
    ],
)
def test_normalize_request(fmt, quality, expected):
    assert app.normalize_request(fmt, quality) == expected


def test_safe_subfolder_never_escapes(tmp_path):
    base = tmp_path / "Downloads"
    base.mkdir()
    assert app.safe_subfolder(base, "Vestibular/Química") == base / "Vestibular" / "Química"
    assert app.safe_subfolder(base, "..\\..\\Windows") == base / "Windows"
    assert app.safe_subfolder(base, "a:b?c/..") == base / "abc"
    assert app.safe_subfolder(base, "") == base
    assert app.safe_subfolder(base, None) == base
    outside = tmp_path / "outside"
    outside.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(base / "fora"), str(outside)], capture_output=True, check=True)
    try:
        assert app.safe_subfolder(base, "fora") == base
    finally:
        os.rmdir(base / "fora")


def test_http_get_and_github_latest(monkeypatch):
    seen = {}

    def urlopen(request, timeout=0):
        seen["ua"] = request.get_header("User-agent")
        return FakeResponse(json.dumps({"tag_name": "v9"}).encode())

    monkeypatch.setattr(app.urllib.request, "urlopen", urlopen)
    assert app.github_latest("a/b") == {"tag_name": "v9"}
    assert seen["ua"].startswith("Salvai/")


class FakeHandler:
    def __init__(self, headers=None, body=b""):
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None
        self.sent = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.sent[name] = value

    def end_headers(self):
        pass


def test_read_json_body():
    assert app.read_json_body(FakeHandler({"Content-Length": "9"}, b'{"a": 1}')) == {"a": 1}
    assert app.read_json_body(FakeHandler({}, b"")) == {}
    with pytest.raises(ValueError, match="grande"):
        app.read_json_body(FakeHandler({"Content-Length": str(app.MAX_BODY + 1)}))
    with pytest.raises(ValueError, match="inválido"):
        app.read_json_body(FakeHandler({"Content-Length": "2"}, b"[]"))


@pytest.mark.parametrize(
    ("header", "host"),
    [
        ("127.0.0.1:47800", "127.0.0.1"),
        ("[::1]:47800", "::1"),
        ("[::1", ""),
        ("fe80::1", "fe80::1"),
        ("localhost", "localhost"),
        (None, ""),
    ],
)
def test_host_name(header, host):
    assert app.host_name(header) == host


def test_is_ip_literal():
    assert app.is_ip_literal("192.168.0.1") and app.is_ip_literal("fe80::1%14")
    assert not app.is_ip_literal("exemplo.com")


def test_internal_targets(monkeypatch):
    for url in (
        "http://localhost/x",
        "http://nas.local/",
        "http://10.0.0.1",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
    ):
        assert app.is_internal_target(url)
    monkeypatch.setattr(app.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", ("142.250.1.1", 0))])
    assert not app.is_internal_target("https://youtube.com/watch")
    monkeypatch.setattr(app.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", ("192.168.0.5", 0))])
    assert app.is_internal_target("https://rebind.exemplo.com")

    def fail(host, port):
        raise OSError("sem dns")

    monkeypatch.setattr(app.socket, "getaddrinfo", fail)
    assert not app.is_internal_target("https://nao-resolve.exemplo")


def test_validate_remote_url(monkeypatch):
    monkeypatch.setattr(app, "is_internal_target", lambda url: "interno" in url)
    app.validate_remote_url("https://youtube.com/watch?v=1")
    with pytest.raises(ValueError, match="link"):
        app.validate_remote_url("nada")
    with pytest.raises(ValueError, match="rede interna"):
        app.validate_remote_url("https://interno.com")


def test_lan_ip():
    ipaddress.ip_address(app.lan_ip())


def test_read_interfaces(monkeypatch):
    outputs = iter(['[{"alias":"A"}]', '{"alias":"B"}', ""])
    monkeypatch.setattr(app.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=next(outputs)))
    assert app.read_interfaces() == [{"alias": "A"}]
    assert app.read_interfaces() == [{"alias": "B"}]
    assert app.read_interfaces() == []


def test_is_private_v4():
    assert app.is_private_v4("192.168.1.2")
    assert not app.is_private_v4("8.8.8.8")
    assert not app.is_private_v4("169.254.1.1")
    assert not app.is_private_v4("fe80::1")
    assert not app.is_private_v4("lixo")


def test_home_network_wifi_and_cable(monkeypatch):
    monkeypatch.setattr(app, "lan_ip", lambda: "192.168.15.9")
    interfaces = [
        {"alias": "VPN", "media": "802.3", "network": "VPN", "category": "Public", "ipv4": ["26.1.1.1/8"], "ipv6": []},
        {
            "alias": "Wi-Fi",
            "media": "Native 802.11",
            "network": "Casa",
            "category": "Private",
            "ipv4": ["192.168.15.9/24"],
            "ipv6": ["2804:7f0::1", "fe80::1"],
        },
    ]
    monkeypatch.setattr(app, "read_interfaces", lambda: [dict(i) for i in interfaces])
    net = app.home_network()
    assert net["kind"] == "wifi" and net["name"] == "Casa" and not net["public"]
    assert net["v4_networks"] == ["192.168.15.0/24"] and net["ipv6"] == ["2804:7f0::1"]
    assert net["v6_networks"] == ["2804:7f0::/64"]
    monkeypatch.setattr(app, "read_interfaces", lambda: [dict(interfaces[0])])
    net = app.home_network()
    assert net["kind"] == "cabo" and net["public"] and net["ipv4"] == []


def test_home_network_without_interfaces(monkeypatch):
    monkeypatch.setattr(app, "lan_ip", lambda: "10.0.0.2")

    def fail():
        raise subprocess.TimeoutExpired("powershell", 20)

    monkeypatch.setattr(app, "read_interfaces", fail)
    assert app.home_network()["ipv4"] == ["10.0.0.2"]


def test_device_name():
    assert app.device_name("Mozilla (iPhone; CPU)") == "iPhone"
    assert app.device_name("iPad") == "iPad"
    assert app.device_name("Linux; Android 14") == "Android"
    assert app.device_name("Windows NT") == "Windows"
    assert app.device_name("Macintosh") == "Mac"
    assert app.device_name(None) == "Navegador"


def make_file(tmp_path, name="vídeo final.mp4", data=b"0123456789"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_send_file_full_and_head(tmp_path):
    path = make_file(tmp_path)
    handler = FakeHandler()
    app.send_file(handler, path, as_attachment=True)
    assert handler.status == 200 and handler.wfile.getvalue() == b"0123456789"
    assert "attachment" in handler.sent["Content-Disposition"] and "v%C3%ADdeo" in handler.sent["Content-Disposition"]
    head = FakeHandler()
    app.send_file(head, path, as_attachment=False, head=True)
    assert head.status == 200 and head.wfile.getvalue() == b"" and "inline" in head.sent["Content-Disposition"]


def test_send_file_conditional_and_ranges(tmp_path):
    path = make_file(tmp_path)
    first = FakeHandler()
    app.send_file(first, path, as_attachment=False)
    etag = first.sent["ETag"]
    cached = FakeHandler({"If-None-Match": etag})
    app.send_file(cached, path, as_attachment=False)
    assert cached.status == 304
    part = FakeHandler({"Range": "bytes=2-4", "If-Range": etag})
    app.send_file(part, path, as_attachment=False)
    assert part.status == 206 and part.wfile.getvalue() == b"234" and part.sent["Content-Range"] == "bytes 2-4/10"
    empty = FakeHandler({"Range": "bytes=-"})
    app.send_file(empty, path, as_attachment=False)
    assert empty.status == 206 and empty.wfile.getvalue() == b"0123456789"
    open_end = FakeHandler({"Range": "bytes=7-"})
    app.send_file(open_end, path, as_attachment=False)
    assert open_end.wfile.getvalue() == b"789"
    suffix = FakeHandler({"Range": "bytes=-3"})
    app.send_file(suffix, path, as_attachment=False)
    assert suffix.wfile.getvalue() == b"789"
    stale = FakeHandler({"Range": "bytes=2-4", "If-Range": '"velho"'})
    app.send_file(stale, path, as_attachment=False)
    assert stale.status == 200 and stale.wfile.getvalue() == b"0123456789"
    outside = FakeHandler({"Range": "bytes=50-"})
    app.send_file(outside, path, as_attachment=False)
    assert outside.status == 416


def test_send_file_stops_when_file_shrinks(tmp_path, monkeypatch):
    path = make_file(tmp_path)
    handler = FakeHandler()
    real_open = open

    def short_open(file, mode="r", *args, **kwargs):
        stream = real_open(file, mode, *args, **kwargs)
        stream.read = lambda size=-1: b""
        return stream

    monkeypatch.setattr("builtins.open", short_open)
    app.send_file(handler, path, as_attachment=False)
    assert handler.wfile.getvalue() == b""


def test_icon_path(monkeypatch, tmp_path):
    assert app.icon_path().name == "icon.ico"
    monkeypatch.setattr(app, "BASE", tmp_path / "x" / "y")
    with pytest.raises(FileNotFoundError):
        app.icon_path()


def test_dual_stack_server_tolerates_missing_option():
    class FakeSocket:
        def setsockopt(self, level, option, value):
            if option == app.socket.IPV6_V6ONLY:
                raise OSError("sem ipv6")

        def bind(self, address):
            self.address = address

        def getsockname(self):
            return ("::", 1234, 0, 0)

    server = app.DualStackServer(("::", 0), app.BaseHTTPRequestHandler, bind_and_activate=False)
    real = server.socket
    server.socket = FakeSocket()
    try:
        server.server_bind()
        assert server.server_port == 1234
    finally:
        real.close()


def test_parse_sums():
    assert app.parse_sums("ABC  Salvai.exe\ndef *x.exe\nlixo") == {"Salvai.exe": "abc", "x.exe": "def"}


def test_download_reports_progress(monkeypatch):
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda req, timeout=0: FakeResponse(b"x" * 600_000))
    steps = []
    assert len(app.download("https://a", steps.append)) == 600_000
    assert steps[-1] == 1.0
    monkeypatch.setattr(
        app.urllib.request, "urlopen", lambda req, timeout=0: FakeResponse(b"abc", headers={"X-Sem-Tamanho": "1"})
    )
    assert app.download("https://a", steps.append) == b"abc"
    assert app.download("https://a") == b"abc"


def test_swap_files_and_rollback(tmp_path):
    dest, new = tmp_path / "Salvai.exe", tmp_path / "novo.exe"
    dest.write_bytes(b"atual")
    (tmp_path / "Salvai.old.exe").write_bytes(b"muito-velho")
    new.write_bytes(b"novo")
    app.swap_files([(new, dest)])
    assert dest.read_bytes() == b"novo" and (tmp_path / "Salvai.old.exe").read_bytes() == b"atual"
    fresh = tmp_path / "fresh.exe"
    fresh.write_bytes(b"x")
    only_new = tmp_path / "nao-existia.exe"
    app.swap_files([(fresh, only_new)])
    assert only_new.read_bytes() == b"x"
    second, other = tmp_path / "b.exe", tmp_path / "c.exe"
    second.write_bytes(b"b")
    other.write_bytes(b"c-atual")
    (tmp_path / "d.exe").write_bytes(b"d")
    with pytest.raises(FileNotFoundError):
        app.swap_files([(tmp_path / "d.exe", other), (tmp_path / "nao-existe.exe", second)])
    assert other.read_bytes() == b"c-atual" and second.read_bytes() == b"b"


def test_swap_files_rollback_ignores_errors(tmp_path, monkeypatch):
    dest = tmp_path / "a.exe"
    dest.write_bytes(b"a")
    new = tmp_path / "novo.exe"
    new.write_bytes(b"n")
    real_replace = Path.replace
    calls = {"n": 0}

    def replace(self, target):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("travado")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(FileNotFoundError):
        app.swap_files([(new, dest), (tmp_path / "sumiu.exe", tmp_path / "b.exe")])


def release_for(tmp_path, files, sums=None, prefix="https://github.com/Kaique292/salvai/releases/download/v9/"):
    assets = [{"name": name, "browser_download_url": prefix + name} for name in files]
    content = {prefix + name: data for name, data in files.items()}
    if sums is not None:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": prefix + "SHA256SUMS.txt"})
        content[prefix + "SHA256SUMS.txt"] = sums.encode()
    return {"tag_name": "v9.0.0", "assets": assets}, content


def test_install_release(tmp_path, monkeypatch):
    files = {"Salvai.exe": b"novo-app", "salvai-mcp.exe": b"novo-mcp"}
    sums = "\n".join(f"{hashlib.sha256(d).hexdigest()}  {n}" for n, d in files.items())
    release, content = release_for(tmp_path, files, sums)
    monkeypatch.setattr(app, "download", lambda url, progress=None: (progress and progress(1.0), content[url])[1])
    current = tmp_path / "Salvai.exe"
    current.write_bytes(b"velho")
    (tmp_path / "salvai-mcp.exe").write_bytes(b"velho-mcp")
    progress = []
    assert app.install_release(release, current, tmp_path / "staging", progress.append) == "9.0.0"
    assert current.read_bytes() == b"novo-app" and (tmp_path / "salvai-mcp.exe").read_bytes() == b"velho-mcp"
    assert progress


def mcp_release(
    monkeypatch, data=b"conector", sums=None, prefix="https://github.com/Kaique292/salvai/releases/download/v9/"
):
    files = {"salvai-mcp.exe": data}
    sums = sums if sums is not None else f"{hashlib.sha256(data).hexdigest()}  salvai-mcp.exe"
    release, content = release_for(None, files, sums, prefix)
    asked = []
    monkeypatch.setattr(app, "http_get", lambda url, timeout=60: (asked.append(url), json.dumps(release).encode())[1])
    monkeypatch.setattr(app, "download", lambda url, progress=None: content[url])
    return asked


def test_ensure_mcp_downloads_verifies_and_skips(monkeypatch, isolated):
    asked = mcp_release(monkeypatch)
    assert app.ensure_mcp("9.0.0") is True
    assert app.MCP_PATH.read_bytes() == b"conector" and app.MCP_VERSION_PATH.read_text() == "9.0.0"
    assert asked == ["https://api.github.com/repos/Kaique292/salvai/releases/tags/v9.0.0"]
    assert app.ensure_mcp("9.0.0") is False and len(asked) == 1
    (app.MCP_DIR / "salvai-mcp.old.exe").write_bytes(b"x")
    mcp_release(monkeypatch, data=b"conector-novo")
    assert app.ensure_mcp("9.1.0") is True
    assert app.MCP_PATH.read_bytes() == b"conector-novo"
    assert (app.MCP_DIR / "salvai-mcp.old.exe").read_bytes() == b"conector"


def test_ensure_mcp_rejections(monkeypatch, isolated):
    mcp_release(monkeypatch, sums="0" * 64 + "  salvai-mcp.exe")
    with pytest.raises(RuntimeError, match="não confere"):
        app.ensure_mcp("9.0.0")
    mcp_release(monkeypatch, prefix="https://outro.site/")
    with pytest.raises(RuntimeError, match="fora do repositório"):
        app.ensure_mcp("9.0.0")
    assert not app.MCP_PATH.exists()


def test_ensure_mcp_old_file_in_use(monkeypatch, isolated):
    mcp_release(monkeypatch)
    app.MCP_DIR.mkdir()
    (app.MCP_DIR / "salvai-mcp.old.exe").mkdir()
    app.MCP_PATH.write_bytes(b"em-uso")
    with pytest.raises(OSError):
        app.ensure_mcp("9.0.0")
    assert app.MCP_PATH.read_bytes() == b"em-uso"
    (app.MCP_DIR / "salvai-mcp.old.exe").rmdir()
    assert app.ensure_mcp("9.0.0") is True and app.MCP_PATH.read_bytes() == b"conector"


def test_claude_config_paths(monkeypatch, tmp_path):
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert app.claude_config_paths() == []
    (roaming / "Claude").mkdir(parents=True)
    store = local / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    assert app.claude_config_paths() == [
        roaming / "Claude" / "claude_desktop_config.json",
        store / "claude_desktop_config.json",
    ]


def test_register_claude(monkeypatch, tmp_path, isolated):
    fresh = tmp_path / "a" / "claude_desktop_config.json"
    existing = tmp_path / "b" / "claude_desktop_config.json"
    broken = tmp_path / "c" / "claude_desktop_config.json"
    odd = tmp_path / "d" / "claude_desktop_config.json"
    done = tmp_path / "e" / "claude_desktop_config.json"
    for path in (fresh, existing, broken, odd, done):
        path.parent.mkdir()
    existing.write_text(json.dumps({"mcpServers": {"outro": {"command": "x"}}, "tema": "escuro"}), encoding="utf-8")
    broken.write_text("{ quebrado", encoding="utf-8")
    odd.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(app, "claude_config_paths", lambda: [fresh, existing, broken, odd, done])
    assert app.register_claude([str(done)]) == [str(fresh), str(existing)]
    assert json.loads(fresh.read_text(encoding="utf-8")) == {"mcpServers": {"salvai": {"command": str(app.MCP_PATH)}}}
    merged = json.loads(existing.read_text(encoding="utf-8"))
    assert merged["tema"] == "escuro" and set(merged["mcpServers"]) == {"outro", "salvai"}
    assert broken.read_text(encoding="utf-8") == "{ quebrado" and not done.exists()


def test_install_release_rejections(tmp_path, monkeypatch):
    current = tmp_path / "Salvai.exe"
    current.write_bytes(b"velho")
    release, content = release_for(tmp_path, {"Salvai.exe": b"x"}, "0" * 64 + "  Salvai.exe")
    monkeypatch.setattr(app, "download", lambda url, progress=None: content[url])
    with pytest.raises(RuntimeError, match="não confere"):
        app.install_release(release, current, tmp_path / "s")
    with pytest.raises(RuntimeError, match="fora do repositório"):
        app.install_release(release, current, tmp_path / "s", trusted_prefix="https://outro/")
    incomplete, _ = release_for(tmp_path, {"Salvai.exe": b"x"})
    with pytest.raises(RuntimeError, match="ainda não tem"):
        app.install_release(incomplete, current, tmp_path / "s")
    assert current.read_bytes() == b"velho"


def test_cleanup_old_versions(monkeypatch, tmp_path, isolated):
    app.cleanup_old_versions()
    exe = tmp_path / "Salvai.exe"
    exe.write_bytes(b"x")
    (tmp_path / "Salvai.old.exe").write_bytes(b"velho")
    (tmp_path / "travado.old.exe").mkdir()
    (app.CONFIG_PATH.parent / "update").mkdir()
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.sys, "executable", str(exe))
    app.cleanup_old_versions()
    assert not (tmp_path / "Salvai.old.exe").exists()
    assert not (app.CONFIG_PATH.parent / "update").exists()


def test_dir_size_and_remove_tree(tmp_path, monkeypatch):
    folder = tmp_path / "pasta"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.bin").write_bytes(b"12345")
    (folder / "sub" / "b.bin").write_bytes(b"123")
    assert app.dir_size(folder) == 8
    real_getsize = os.path.getsize
    monkeypatch.setattr(
        app.os.path, "getsize", lambda p: (_ for _ in ()).throw(OSError()) if p.endswith("a.bin") else real_getsize(p)
    )
    assert app.dir_size(folder) == 3
    monkeypatch.setattr(app.os.path, "getsize", real_getsize)
    real_rmdir = os.rmdir
    monkeypatch.setattr(
        app.os, "rmdir", lambda p: (_ for _ in ()).throw(OSError()) if str(p).endswith("sub") else real_rmdir(p)
    )
    assert app.remove_tree(folder) == 8
    monkeypatch.setattr(app.os, "rmdir", real_rmdir)
    real_remove = os.remove
    (folder / "sub" / "c.bin").write_bytes(b"1")
    monkeypatch.setattr(app.os, "remove", lambda p: (_ for _ in ()).throw(OSError()))
    assert app.remove_tree(folder) == 0
    monkeypatch.setattr(app.os, "remove", real_remove)
    assert app.remove_tree(folder) == 1 and not folder.exists()


def test_leftover_temp_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    ours = make_leftover(tmp_path / "_MEI1")
    (tmp_path / "_MEI2").mkdir()
    (tmp_path / "_MEI6.del").mkdir()
    (tmp_path / "_MEI3.txt").write_text("arquivo")
    current = tmp_path / "_MEI4"
    (current / "ui").mkdir(parents=True)
    (current / "ffmpeg.zip").write_bytes(b"x")
    (current / "ui" / "index.html").write_text("x")
    monkeypatch.setattr(app.sys, "_MEIPASS", str(current), raising=False)
    assert app.leftover_temp_dirs() == [ours]


def test_leftover_temp_dirs_ignores_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    (tmp_path / "_MEIx").mkdir()
    monkeypatch.setattr(Path, "is_dir", lambda self: (_ for _ in ()).throw(OSError()))
    assert app.leftover_temp_dirs() == []


def make_leftover(folder, mcp=False):
    if mcp:
        folder.mkdir(parents=True)
        (folder / "salvai-mcp.marker").write_text("x")
    else:
        (folder / "ui").mkdir(parents=True)
        (folder / "ffmpeg.zip").write_bytes(b"1234")
        (folder / "ui" / "index.html").write_text("x")
    return folder


def test_cleanup_leftovers(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    app_left = make_leftover(tmp_path / "_MEI1")
    mcp_left = make_leftover(tmp_path / "_MEI2", mcp=True)
    in_use = make_leftover(tmp_path / "_MEI3")
    partial = tmp_path / "_MEI4.del"
    partial.mkdir()
    (partial / "resto.bin").write_bytes(b"12")
    (tmp_path / "_MEI5").mkdir()
    real_rename = Path.rename
    monkeypatch.setattr(
        Path,
        "rename",
        lambda self, target: (_ for _ in ()).throw(PermissionError()) if self == in_use else real_rename(self, target),
    )
    assert app.cleanup_leftovers() == 4 + 1 + 1 + 2
    assert not app_left.exists() and not mcp_left.exists() and not partial.exists()
    assert in_use.exists() and (tmp_path / "_MEI5").exists()


def test_file_size(tmp_path):
    (tmp_path / "a").write_bytes(b"123")
    assert app.file_size(tmp_path / "a") == 3 and app.file_size(tmp_path / "nao") == 0


def test_exclusive_server_blocks_port_hijack():
    first = app.ExclusiveHTTPServer(("127.0.0.1", 0), app.BaseHTTPRequestHandler)
    try:
        with pytest.raises(OSError):
            app.ExclusiveHTTPServer(("127.0.0.1", first.server_address[1]), app.BaseHTTPRequestHandler)
    finally:
        first.server_close()


def test_exclusive_server_without_windows_option(monkeypatch):
    monkeypatch.delattr(app.socket, "SO_EXCLUSIVEADDRUSE", raising=False)
    server = app.ExclusiveHTTPServer(("127.0.0.1", 0), app.BaseHTTPRequestHandler)
    server.server_close()


def test_config_roundtrip(isolated, monkeypatch):
    assert app.load_config() == {}
    app.save_config({"theme": "light"})
    assert app.load_config() == {"theme": "light"}
    monkeypatch.setattr(app.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError()))
    app.save_config({"x": 1})


class Callable:
    def __init__(self, function):
        self.function = function
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.function(*args)


def fake_windll(text="copiado", open_ok=True, handle=1, pointer=True):
    buffer = ctypes.create_unicode_buffer(text)
    user32 = types.SimpleNamespace(
        GetClipboardData=Callable(lambda fmt: handle),
        OpenClipboard=Callable(lambda owner: open_ok),
        CloseClipboard=Callable(lambda: True),
    )
    kernel32 = types.SimpleNamespace(
        GlobalLock=Callable(lambda h: ctypes.addressof(buffer) if pointer else None),
        GlobalUnlock=Callable(lambda h: True),
    )
    return types.SimpleNamespace(user32=user32, kernel32=kernel32, _keep=buffer)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [({}, "copiado"), ({"open_ok": False}, ""), ({"handle": 0}, ""), ({"pointer": False}, "")],
)
def test_read_clipboard(monkeypatch, kwargs, expected):
    monkeypatch.setattr(app.ctypes, "windll", fake_windll(**kwargs))
    assert app.read_clipboard() == expected


@pytest.fixture
def tk_window():
    tkinter = pytest.importorskip("tkinter")
    root = tkinter.Tk()
    root.title("Salvaí teste janela")
    root.geometry("300x200")
    root.update()
    yield root
    root.destroy()


def test_window_helpers_with_real_window(tk_window):
    hwnd = app.find_own_window("Salvaí teste janela")
    assert hwnd
    assert app.find_own_window("não existe") == 0
    app.center_window(hwnd)
    app.center_window(0)
    app.style_titlebar(hwnd, "dark")
    app.style_titlebar(hwnd, "light")
    app.style_titlebar(0, "dark")


def test_center_window_without_monitor_info(monkeypatch):
    user32 = types.SimpleNamespace(
        GetCursorPos=lambda p: True,
        MonitorFromPoint=Callable(lambda p, f: 1),
        GetMonitorInfoW=lambda m, i: 0,
    )
    monkeypatch.setattr(app.ctypes, "windll", types.SimpleNamespace(user32=user32))
    app.center_window(123)


def test_build_options_variants(monkeypatch, isolated):
    monkeypatch.setattr(app, "js_runtimes", lambda: {"node": {}})
    mp4 = app.build_options("MP4", "Máxima", "C:/d", "ff", url="https://youtu.be/jNQXAC9IVRw")
    assert mp4["format_sort"][0] == "res" and mp4["outtmpl"].endswith("%(title)s.%(ext)s")
    hd = app.build_options("MP4", "720p", "C:/d", "ff", hook=print, url="https://vimeo.com/1")
    assert hd["format_sort"][0] == "res:720" and "[%(id)s]" in hd["outtmpl"] and hd["progress_hooks"] == [print]
    mp3 = app.build_options("MP3", "320 kbps", "C:/d", "ff")
    assert mp3["postprocessors"][0]["preferredquality"] == "320"
    best = app.build_options("MP3", "Máxima", "C:/d", "ff")
    assert best["postprocessors"][0]["preferredquality"] == "0"


def test_clean_error():
    error = Exception("\x1b[0;31mERROR:\x1b[0m [youtube] abc: Video unavailable. Use --cookies to fix")
    assert app.clean_error(error) == "Video unavailable."
    assert len(app.clean_error(Exception("x" * 500))) == 160


def test_selftest_writes_report(monkeypatch, tmp_path, fake_engine):
    monkeypatch.setattr(app, "ensure_js_runtime", lambda: {"node": {}})
    monkeypatch.setattr(app, "ffmpeg_dir", lambda: "ff")
    FakeYDL.script = {
        "jNQXAC9IVRw": {"download": lambda ydl, url: {"format_id": "251" if ydl.opts["format"] == "ba/b" else "18"}}
    }
    app.selftest(str(tmp_path))
    report = (tmp_path / "selftest.txt").read_text()
    assert "MP4 ok 18" in report and "MP3 ok 251" in report
    FakeYDL.script = {"jNQXAC9IVRw": {"download": lambda ydl, url: (_ for _ in ()).throw(RuntimeError("offline"))}}
    app.selftest(str(tmp_path))
    assert "MP4 FAIL offline" in (tmp_path / "selftest.txt").read_text()
