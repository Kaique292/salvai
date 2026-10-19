import copy
import ctypes
import email.utils
import functools
import hashlib
import http.cookiejar
import importlib.metadata
import io
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import winreg
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import pyi_splash
except ImportError:
    pyi_splash = None


def splash_step(pct: int, text: str) -> None:
    if pyi_splash:
        try:
            pyi_splash.update_text(f"@{pct}|{text}")
        except Exception:
            pass


def splash_close() -> None:
    if pyi_splash:
        try:
            pyi_splash.close()
        except Exception:
            pass


splash_step(64, "Iniciando…")
import imageio_ffmpeg
import pystray
import segno
from PIL import Image

splash_step(68, "Carregando a interface…")
import webview
from webview.dom import DOMEventHandler

splash_step(76, "Carregando o motor de download…")

ENGINE_DIR = Path(os.getenv("APPDATA", Path.home())) / "Salvai" / "engine"


def version_key(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version or "0"))


def bundled_engine_version() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return "0"


def activate_engine_update() -> str | None:
    bundled = version_key(bundled_engine_version())
    candidates = sorted(
        ((version_key(p.stem.removeprefix("yt-dlp-")), p) for p in ENGINE_DIR.glob("yt-dlp-*.zip")), reverse=True
    )
    for key, path in candidates:
        if key > bundled:
            sys.path.insert(0, str(path))
            return path.stem.removeprefix("yt-dlp-")
    return None


ENGINE_OVERRIDE = activate_engine_update()
_engine_ready = threading.Event()
yt_dlp = None


def _load_engine():
    global yt_dlp
    import yt_dlp as module

    yt_dlp = module
    _engine_ready.set()


def engine():
    _engine_ready.wait()
    return yt_dlp


threading.Thread(target=_load_engine, daemon=True).start()

APP_NAME = "Salvaí"
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def read_version() -> str:
    for candidate in (BASE / "version.txt", BASE.parent / "version.txt"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "0.0.0"


APP_VERSION = read_version()
_APPDATA = Path(os.getenv("APPDATA", Path.home()))
CONFIG_PATH = _APPDATA / "Salvai" / "config.json"


def _migrate_old_data(old: Path, new: Path) -> None:
    if not old.is_dir():
        return
    try:
        new.mkdir(parents=True, exist_ok=True)
        for item in old.iterdir():
            target = new / item.name
            newer = item.is_file() and target.is_file() and item.stat().st_mtime > target.stat().st_mtime
            if not target.exists() or (newer and item.name in ("config.json", "sessions.dat")):
                if target.is_file():
                    target.unlink()
                shutil.move(str(item), str(target))
        shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


_migrate_old_data(_APPDATA / "YouTubeDownloader", CONFIG_PATH.parent)
BIN_DIR = CONFIG_PATH.parent / "bin"
SAVED_PATH = CONFIG_PATH.parent / "saved.json"
SAVED_LIMIT = 300
MCP_DIR = CONFIG_PATH.parent / "mcp"
MCP_PATH = MCP_DIR / "salvai-mcp.exe"
MCP_VERSION_PATH = MCP_DIR / "version.txt"
CACHE_DIR = CONFIG_PATH.parent / "cache"
WEBVIEW_DIR = CONFIG_PATH.parent / "webview"
WEBVIEW_CLEAR_FLAG = CONFIG_PATH.parent / "clear-webview-cache"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
_runtime_lock = threading.Lock()

THEMES = {"dark": 0x110E0E, "light": 0xF6F4F4}
TITLE_TEXT = {"dark": 0xF0EDED, "light": 0x1A1616}

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
YT_HOST_RE = re.compile(r"^https?://(?:[\w-]+\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)/", re.I)
ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})")
SESSIONS_PATH = CONFIG_PATH.parent / "sessions.dat"

LOGIN_SITES = {
    "instagram": {
        "name": "Instagram",
        "login": "https://www.instagram.com/accounts/login/",
        "domains": ("instagram.com",),
        "auth": "sessionid",
    },
    "tiktok": {
        "name": "TikTok",
        "login": "https://www.tiktok.com/login",
        "domains": ("tiktok.com",),
        "auth": "sessionid",
    },
    "x": {
        "name": "X (Twitter)",
        "login": "https://x.com/i/flow/login",
        "domains": ("x.com", "twitter.com"),
        "auth": "auth_token",
    },
    "facebook": {
        "name": "Facebook",
        "login": "https://www.facebook.com/login",
        "domains": ("facebook.com", "fb.watch"),
        "auth": "c_user",
    },
}
SITE_NAMES = {
    "Youtube": "YouTube",
    "Twitter": "X",
    "Instagram": "Instagram",
    "TikTok": "TikTok",
    "Facebook": "Facebook",
    "Vimeo": "Vimeo",
    "Twitch": "Twitch",
    "Reddit": "Reddit",
    "Dailymotion": "Dailymotion",
    "Kwai": "Kwai",
    "Pinterest": "Pinterest",
    "Threads": "Threads",
}
PENDING = ("queued", "paused")
INFO_TTL = 3 * 3600


class Paused(Exception):
    pass


def ffmpeg_dir() -> str:
    target, stamp = BIN_DIR / "ffmpeg.exe", BIN_DIR / "ffmpeg.version"
    packed = BASE / "ffmpeg.zip"
    if packed.exists():
        zf = zipfile.ZipFile(packed)
        name = zf.namelist()[0]
        open_src = lambda: zf.open(name)
    else:
        bundled = sorted((Path(imageio_ffmpeg.__file__).parent / "binaries").glob("ffmpeg*.exe"))
        src = bundled[0] if bundled else Path(imageio_ffmpeg.get_ffmpeg_exe())
        name = src.name
        open_src = lambda: src.open("rb")
    if not (target.exists() and stamp.exists() and stamp.read_text() == name):
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = BIN_DIR / "ffmpeg.exe.part"
        with open_src() as s, open(tmp, "wb") as d:
            shutil.copyfileobj(s, d, 1 << 20)
        tmp.replace(target)
        stamp.write_text(name)
    return str(BIN_DIR)


@functools.lru_cache(maxsize=1)
def system_runtimes() -> tuple[str, ...]:
    return tuple(n for n in ("deno", "node", "bun") if shutil.which(n))


def js_runtimes() -> dict:
    found = {} if os.getenv("YTD_FORCE_DENO") else {n: {} for n in system_runtimes()}
    local = BIN_DIR / "deno.exe"
    if not found and local.exists():
        found["deno"] = {"path": str(local)}
    return found


def ensure_js_runtime() -> dict:
    with _runtime_lock:
        if runtimes := js_runtimes():
            return runtimes
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        tmp_zip, tmp_exe = BIN_DIR / "deno.zip.part", BIN_DIR / "deno.exe.part"
        try:
            sums = urllib.request.urlopen(DENO_URL + ".sha256sum", timeout=30).read().decode("utf-8", "replace")
            expected = re.search(r"\b[0-9a-fA-F]{64}\b", sums)
            data = urllib.request.urlopen(DENO_URL, timeout=180).read()
            if not expected or hashlib.sha256(data).hexdigest() != expected.group(0).lower():
                raise RuntimeError("o Deno baixado não confere com o hash oficial")
            tmp_zip.write_bytes(data)
            with zipfile.ZipFile(tmp_zip) as z:
                tmp_exe.write_bytes(z.read("deno.exe"))
            tmp_exe.replace(BIN_DIR / "deno.exe")
        finally:
            tmp_zip.unlink(missing_ok=True)
            tmp_exe.unlink(missing_ok=True)
        return js_runtimes()


def is_youtube(url: str) -> bool:
    return bool(YT_HOST_RE.match(url or ""))


def youtube_id(url: str):
    m = ID_RE.search(url) if is_youtube(url) else None
    return m.group(1) if m else None


def host_of(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    return re.sub(r"^(www|m|mobile|vm|vt)\.", "", host)


def login_site_for(url: str):
    host = host_of(url)
    return next(
        (k for k, s in LOGIN_SITES.items() if any(host == d or host.endswith("." + d) for d in s["domains"])), None
    )


HOST_NAMES = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "x.com": "X",
    "twitter.com": "X",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "vimeo.com": "Vimeo",
    "twitch.tv": "Twitch",
    "reddit.com": "Reddit",
    "kwai.com": "Kwai",
    "pinterest.com": "Pinterest",
    "threads.net": "Threads",
    "dailymotion.com": "Dailymotion",
}


def site_label(info: dict | None, url: str) -> str:
    key = (info or {}).get("extractor_key") or ""
    for prefix, name in SITE_NAMES.items():
        if key.startswith(prefix):
            return name
    host = host_of(url)
    return next((n for h, n in HOST_NAMES.items() if host == h or host.endswith("." + h)), host)


@functools.lru_cache(maxsize=512)
def supported_site(url: str) -> bool:
    for ie in engine().extractor.gen_extractor_classes():
        if ie.ie_key() != "Generic" and ie.suitable(url):
            return True
    return False


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), "Salvai", None, None, None, 0x1, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


_sessions_lock = threading.Lock()
_sessions_cache = None


def load_sessions() -> dict:
    global _sessions_cache
    with _sessions_lock:
        if _sessions_cache is None:
            try:
                _sessions_cache = json.loads(dpapi(SESSIONS_PATH.read_bytes(), protect=False))
            except Exception:
                _sessions_cache = {}
        return dict(_sessions_cache)


def save_sessions(sessions: dict) -> None:
    global _sessions_cache
    with _sessions_lock:
        _sessions_cache = dict(sessions)
        SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if sessions:
            SESSIONS_PATH.write_bytes(dpapi(json.dumps(sessions).encode(), protect=True))
        else:
            SESSIONS_PATH.unlink(missing_ok=True)


def make_ydl(opts: dict) -> "yt_dlp.YoutubeDL":
    ydl = engine().YoutubeDL(opts)
    for session in load_sessions().values():
        for c in session["cookies"]:
            domain = c["domain"]
            ydl.cookiejar.set_cookie(
                http.cookiejar.Cookie(
                    0,
                    c["name"],
                    c["value"],
                    None,
                    False,
                    domain,
                    True,
                    domain.startswith("."),
                    c.get("path") or "/",
                    True,
                    bool(c.get("secure")),
                    c.get("expires"),
                    False,
                    None,
                    None,
                    {},
                )
            )
    return ydl


def cookies_from_webview(raw: list) -> list[dict]:
    out = []
    for sc in raw or []:
        for name, m in sc.items():
            expires = None
            try:
                if m["expires"]:
                    expires = int(email.utils.parsedate_to_datetime(m["expires"]).timestamp())
            except Exception:
                pass
            if expires is not None and expires <= 0:
                expires = None
            out.append(
                {
                    "name": name,
                    "value": m.value,
                    "domain": m["domain"] or "",
                    "path": m["path"] or "/",
                    "secure": bool(m["secure"]),
                    "expires": expires,
                }
            )
    return out


BROWSERS = {
    "firefox": ("Firefox", Path(os.getenv("APPDATA", "")) / "Mozilla/Firefox/Profiles"),
    "chrome": ("Google Chrome", Path(os.getenv("LOCALAPPDATA", "")) / "Google/Chrome/User Data"),
    "edge": ("Microsoft Edge", Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data"),
    "brave": ("Brave", Path(os.getenv("LOCALAPPDATA", "")) / "BraveSoftware/Brave-Browser/User Data"),
    "opera": ("Opera", Path(os.getenv("APPDATA", "")) / "Opera Software/Opera Stable"),
    "vivaldi": ("Vivaldi", Path(os.getenv("LOCALAPPDATA", "")) / "Vivaldi/User Data"),
}


class _QuietLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg, only_once=False):
        pass

    def error(self, msg):
        pass


def friendly_error(e, url: str) -> tuple[str, str]:
    raw = clean_error(e)
    low = raw.lower()
    full = str(e).lower()
    site = login_site_for(url)
    name = LOGIN_SITES[site]["name"] if site else site_label(None, url)
    if "unsupported url" in low:
        return "unsupported", "Esse site não é suportado ou o link não tem vídeo."
    if "429" in low or "too many requests" in low:
        return "ratelimit", f"O {name} limitou os acessos por enquanto. Espere alguns minutos e tente de novo."
    login_markers = (
        "login",
        "log in",
        "logged",
        "sign in",
        "authenticat",
        "cookies",
        "private",
        "not available to you",
        "age-restricted",
        "confirm your age",
        "nsfw",
        "sensitive",
    )
    if any(m in full for m in login_markers) or "unreachable" in low:
        connected = site in load_sessions()
        if site == "instagram" and "/stories/" in url and not connected:
            return "login", (
                "Stories do Instagram só podem ser vistos com login, mesmo de perfis públicos. "
                "Conecte sua conta em Contas e tente de novo."
            )
        if connected:
            return "noaccess", (
                f"Sua conta do {name} não tem acesso a esse conteúdo. Se o perfil for privado, "
                "você precisa segui-lo. Se já segue, a sessão pode ter expirado: reconecte em Contas."
            )
        msg = f"Esse conteúdo só aparece para quem está logado no {name}."
        if site:
            msg += " Conecte sua conta em Contas e tente de novo."
            if site in ("instagram", "facebook", "tiktok"):
                msg += " Se o perfil for privado, a conta conectada precisa segui-lo."
        return ("login" if site else "other"), msg
    if "no video" in low or "no media" in low or "there's no video" in low:
        return "novideo", "Não encontrei vídeo nesse link — pode ser só foto ou texto."
    if any(m in low for m in ("unavailable", "removed", "404", "does not exist", "not found", "deleted")):
        return "unavailable", "Conteúdo indisponível: foi removido ou o link está errado."
    if "geo" in low or "your country" in low:
        return "geo", "Esse conteúdo está bloqueado na sua região."
    if "please report this issue" in full or "unexpected response" in full or "unable to extract" in full:
        return "blocked", (
            f"O {name} recusou o acesso agora (às vezes ele bloqueia downloads por um tempo). "
            "Tente de novo em alguns minutos."
        )
    return "other", raw


BRIDGE_PATH = CONFIG_PATH.parent / "bridge.json"
VIDEO_QUALITY = {
    "max": "Máxima",
    "2160": "2160p (4K)",
    "4k": "2160p (4K)",
    "1440": "1440p",
    "2k": "1440p",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "360": "360p",
}
AUDIO_QUALITY = {"max": "Máxima", "320": "320 kbps", "256": "256 kbps", "192": "192 kbps", "128": "128 kbps"}


def normalize_request(fmt: str, quality: str) -> tuple[str, str]:
    fmt = "MP3" if str(fmt).strip().lower() in ("mp3", "audio", "áudio", "music", "música") else "MP4"
    table = AUDIO_QUALITY if fmt == "MP3" else VIDEO_QUALITY
    raw = str(quality or "max").strip().lower().replace(" ", "")
    if raw in table:
        return fmt, table[raw]
    key = re.sub(r"(p|kbps|k)$", "", raw)
    key = "max" if key in ("", "máxima", "maxima", "best", "melhor") else key
    return fmt, table.get(key, "Máxima")


def safe_subfolder(base: Path, folder: str | None) -> Path:
    parts = []
    for part in re.split(r"[\\/]+", folder or ""):
        part = re.sub(r'[<>:"|?*\x00-\x1f]', "", part).strip(" .")
        if part and part != "..":
            parts.append(part[:80])
    target = base.joinpath(*parts) if parts else base
    base_r, target_r = base.resolve(), target.resolve()
    if target_r != base_r and base_r not in target_r.parents:
        return base
    return target


class Bridge:
    def __init__(self, api: "Api"):
        self.api, self.server, self.token = api, None, secrets.token_urlsafe(24)

    def start(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 60

            def log_message(self, *args):
                pass

            def _reply(self, code: int, payload):
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method: str):
                if host_name(self.headers.get("Host")) not in ("127.0.0.1", "localhost"):
                    return self._reply(421, {"error": "host inválido"})
                auth = self.headers.get("Authorization", "")
                if not secrets.compare_digest(auth, f"Bearer {bridge.token}"):
                    return self._reply(401, {"error": "token inválido"})
                url = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                try:
                    body = read_json_body(self) if method == "POST" else {}
                    result = bridge.route(method, url.path, query, body)
                    self._reply(200, result)
                except (KeyError, ValueError) as e:
                    self._reply(400, {"error": str(e)})
                except Exception as e:
                    self._reply(500, {"error": clean_error(e)})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.server = ExclusiveHTTPServer(("127.0.0.1", 0), Handler)
        BRIDGE_PATH.write_text(
            json.dumps(
                {"port": self.server.server_address[1], "token": self.token, "pid": os.getpid(), "version": APP_VERSION}
            ),
            encoding="utf-8",
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        try:
            if json.loads(BRIDGE_PATH.read_text(encoding="utf-8")).get("pid") == os.getpid():
                BRIDGE_PATH.unlink()
        except Exception:
            pass

    def route(self, method: str, path: str, query: dict, body: dict):
        api = self.api
        if (method, path) == ("GET", "/status"):
            return api._status()
        if (method, path) == ("POST", "/search"):
            return api._search(body["query"], int(body.get("limit", 5)), body.get("site", "youtube"))
        if (method, path) == ("POST", "/downloads"):
            created = []
            for it in body["items"][:50]:
                try:
                    validate_remote_url(str(it.get("url", "")).strip())
                except ValueError as e:
                    created.append({"url": it.get("url"), "error": str(e)})
                    continue
                fmt, quality = normalize_request(it.get("format", "mp4"), it.get("quality", "max"))
                items = api._enqueue(it["url"], fmt, quality, it.get("folder", ""), source="claude")
                created += [
                    {
                        "id": i["id"],
                        "url": i["url"],
                        "format": fmt,
                        "quality": quality,
                        "folder": i["folder"] or "(pasta principal)",
                    }
                    for i in items
                ]
            return {"queued": created}
        if (method, path) == ("GET", "/downloads"):
            ids = set(filter(None, query.get("ids", "").split(",")))
            return {"downloads": [api._report(i) for i in api._ordered() if not ids or i["id"] in ids]}
        if (method, path) == ("GET", "/files"):
            return api._files(query.get("folder", ""), int(query.get("depth", 3)))
        if (method, path) == ("POST", "/move"):
            return api._move(body["path"], body.get("folder", ""))
        raise KeyError(f"rota desconhecida: {method} {path}")


APP_REPO = "Kaique292/salvai"
ENGINE_RELEASES = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"


def http_get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Salvai/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


HIDDEN_NOTE_SECTIONS = ("Documentação", "Automação", "Manutenção", "Testes", "Estilo", "Build", "internas")


def parse_release_notes(body: str) -> list[dict]:
    sections, current = [], None
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("### "):
            title = line[4:].strip()
            current = None if any(h in title for h in HIDDEN_NOTE_SECTIONS) else {"title": title, "items": []}
            if current:
                sections.append(current)
        elif current is not None and line[:2] in ("* ", "- "):
            text = re.sub(r"\s*\(\[[0-9a-f]{7,40}\]\([^)]*\)\)", "", line[2:])
            text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text).replace("**", "").strip()
            if text:
                current["items"].append(text[0].upper() + text[1:])
    return [s for s in sections if s["items"]]


def github_latest(repo: str) -> dict:
    return json.loads(http_get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10))


PHONE_PORT = 47800
PEEK_TTL = 15 * 60
NETWORK_TTL = 5 * 60
MEDIA_EXTENSIONS = {".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".mov", ".opus", ".ogg", ".wav", ".flac", ".jpg", ".png"}
CREATE_NO_WINDOW = 0x08000000


MAX_BODY = 64 * 1024
PHONE_IDLE_LIMIT = 30 * 60
PHONE_HISTORY_LIMIT = 20
PHONE_INBOX = "Do celular"
PHONE_CHUNK = 4 << 20
PHONE_MAX_CHUNK = 16 << 20
PHONE_SEND_BATCH = 50
PHONE_MAX_UPLOADS = 500
PHONE_RECEIVED_LIMIT = 30
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}
MOBILE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
    "media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)


def read_json_body(handler: BaseHTTPRequestHandler, limit: int = MAX_BODY) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > limit:
        raise ValueError("pedido grande demais")
    data = json.loads(handler.rfile.read(length) or b"{}")
    if not isinstance(data, dict):
        raise ValueError("pedido inválido")
    return data


def host_name(host_header: str) -> str:
    host = (host_header or "").strip()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else ""
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%")[0])
        return True
    except ValueError:
        return False


def is_internal_target(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".lan", ".home", ".internal")):
        return True
    addresses = []
    if is_ip_literal(host):
        addresses = [host]
    else:
        try:
            addresses = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except OSError:
            return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return True
    return False


def validate_remote_url(url: str) -> None:
    if not URL_RE.fullmatch(url or ""):
        raise ValueError("isso não parece um link")
    if is_internal_target(url):
        raise ValueError("links para a rede interna ou para este computador não são permitidos")


def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]


NETWORK_SCRIPT = (
    "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -or $_.IPv6DefaultGateway } | ForEach-Object { "
    "[pscustomobject]@{ alias = $_.InterfaceAlias; media = $_.NetAdapter.PhysicalMediaType; "
    "network = $_.NetProfile.Name; category = [string]$_.NetProfile.NetworkCategory; "
    "ipv4 = @($_.IPv4Address | ForEach-Object { $_.IPAddress + '/' + $_.PrefixLength }); "
    "ipv6 = @($_.IPv6Address | ForEach-Object { $_.IPAddress }) } } | ConvertTo-Json -Depth 3 -Compress"
)


def read_interfaces() -> list[dict]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", NETWORK_SCRIPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=20,
    ).stdout.strip()
    data = json.loads(out) if out else []
    return data if isinstance(data, list) else [data]


def is_private_v4(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_link_local and not ip.is_loopback


def home_network() -> dict:
    primary = lan_ip()
    try:
        interfaces = read_interfaces()
    except Exception:
        interfaces = []
    for interface in interfaces:
        interface["cidr"] = list(interface.get("ipv4") or [])
        interface["ipv4"] = [c.split("/")[0] for c in interface["cidr"]]
    candidates = [i for i in interfaces if any(is_private_v4(a) for a in i["ipv4"])]
    chosen = next((i for i in candidates if primary in i["ipv4"]), candidates[0] if candidates else None)
    if not chosen:
        chosen = next(iter(interfaces), None)
    if not chosen:
        return {
            "kind": None,
            "name": None,
            "public": False,
            "ipv4": [primary],
            "ipv6": [],
            "v4_networks": [],
            "v6_networks": [],
        }
    media = (chosen.get("media") or "").lower()
    ipv6 = [a for a in chosen.get("ipv6") or [] if not a.lower().startswith("fe80")]
    return {
        "kind": "wifi" if "802.11" in media or "wireless" in media else "cabo",
        "name": chosen.get("network"),
        "public": (chosen.get("category") or "").lower() == "public",
        "ipv4": [a for a in chosen.get("ipv4") or [] if is_private_v4(a)],
        "v4_networks": [
            str(ipaddress.ip_network(c, strict=False))
            for c in chosen.get("cidr") or []
            if is_private_v4(c.split("/")[0])
        ],
        "ipv6": ipv6,
        "v6_networks": [str(ipaddress.ip_network(f"{a}/64", strict=False)) for a in ipv6],
    }


def device_name(user_agent: str) -> str:
    ua = user_agent or ""
    for marker, name in (
        ("Salvai", "Salvaí"),
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Android", "Android"),
        ("Windows", "Windows"),
        ("Mac", "Mac"),
    ):
        if marker in ua:
            return name
    return "Navegador"


def send_file(handler: BaseHTTPRequestHandler, path: Path, as_attachment: bool, head: bool = False) -> None:
    stat = path.stat()
    size = stat.st_size
    etag = f'"{size:x}-{int(stat.st_mtime):x}"'
    start, end, status = 0, size - 1, 200
    if not handler.headers.get("Range") and handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "private, no-cache")
        handler.end_headers()
        return
    match = re.match(r"bytes=(\d*)-(\d*)$", (handler.headers.get("Range") or "").strip())
    if_range = handler.headers.get("If-Range")
    if match and size and (not if_range or if_range == etag):
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        elif match.group(2):
            start = max(0, size - int(match.group(2)))
        end = min(end, size - 1)
        if start > end:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        status = 206
    handler.send_response(status)
    handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    handler.send_header("Content-Length", str(end - start + 1))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("ETag", etag)
    handler.send_header("Cache-Control", "private, no-cache")
    for name, value in SECURITY_HEADERS.items():
        handler.send_header(name, value)
    handler.send_header("Last-Modified", email.utils.formatdate(stat.st_mtime, usegmt=True))
    fallback = re.sub(r"[^ -~]", "_", path.name).replace('"', "")
    disposition = "attachment" if as_attachment else "inline"
    handler.send_header(
        "Content-Disposition",
        f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{urllib.parse.quote(path.name)}",
    )
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()
    if head:
        return
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(1 << 20, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


ACTIVE_STATUSES = ("setup", "queued", "fetching", "downloading", "processing", "paused")


def icon_path() -> Path:
    for candidate in (BASE / "icon.ico", BASE.parent / "assets" / "icon.ico"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("icon.ico")


class Tray:
    def __init__(self, api: "Api"):
        self.api, self.icon = api, None

    def start(self):
        api = self.api
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Salvaí", lambda: api._show_from_tray(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: api._downloads_label(), None, enabled=False),
            pystray.MenuItem(
                "Modo celular", lambda: api._toggle_phone_from_tray(), checked=lambda item: api._phone.running
            ),
            pystray.MenuItem("Abrir pasta de downloads", lambda: os.startfile(api._out_dir)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair do Salvaí", lambda: api._quit()),
        )
        self.icon = pystray.Icon("salvai", Image.open(icon_path()), APP_NAME, menu)
        self.icon.run_detached()

    def notify(self, title: str, message: str):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def refresh(self):
        if self.icon:
            try:
                self.icon.title = f"{APP_NAME} · {self.api._downloads_label()}"
                self.icon.update_menu()
            except Exception:
                pass

    def stop(self):
        if self.icon:
            icon, self.icon = self.icon, None
            try:
                icon.stop()
            except Exception:
                pass


class ExclusiveHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class DualStackServer(ExclusiveHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


def drain_body(h) -> None:
    length = h.headers.get("Content-Length") or ""
    remaining = int(length) if length.isdigit() and int(length) <= PHONE_MAX_CHUNK else 0
    while remaining > 0:
        chunk = h.rfile.read(min(1 << 20, remaining))
        if not chunk:
            break
        remaining -= len(chunk)


class PhoneServer:
    def __init__(self, api: "Api"):
        self.api, self.server, self.token = api, None, ""
        self.sessions: dict[str, dict] = {}
        self.revoked: set[str] = set()
        self.session_lock = threading.Lock()
        self.network, self.network_at, self.network_lock = None, 0.0, threading.Lock()
        self.failures: dict[str, list[float]] = {}
        self.qr: tuple[str, str] | None = None
        self.adds: deque = deque()
        self.last_activity = 0.0
        self.uploads: dict[str, dict] = {}
        self.received: deque = deque(maxlen=PHONE_RECEIVED_LIMIT)
        self.upload_lock = threading.Lock()

    def session_for(self, sid: str) -> dict | None:
        return self.sessions.get(sid) if sid else None

    def open_session(self, ip: str, user_agent: str) -> str:
        sid = secrets.token_urlsafe(24)
        now = time.time()
        session = {"id": secrets.token_hex(6), "name": device_name(user_agent), "ip": ip, "since": now, "seen": now}
        with self.session_lock:
            self.sessions[sid] = session
        self.remember(session)
        return sid

    def remember(self, session: dict, **changes):
        cfg = self.api._cfg
        history = [h for h in cfg.get("phone_history", []) if h["id"] != session["id"]]
        entry = {
            "id": session["id"],
            "name": session["name"],
            "ip": session["ip"],
            "since": session["since"],
            "last": session["seen"],
        }
        cfg["phone_history"] = [{**entry, **changes}, *history][:PHONE_HISTORY_LIMIT]
        save_config(cfg)

    def rotate_token(self):
        self.token = secrets.token_urlsafe(16)
        self.qr = None

    def revoke(self, device_id: str) -> bool:
        with self.session_lock:
            found = [(sid, s) for sid, s in self.sessions.items() if s["id"] == device_id]
            for sid, _ in found:
                del self.sessions[sid]
                self.revoked.add(sid)
        for _, session in found:
            self.remember(session, revoked=True)
        if found:
            self.rotate_token()
        return bool(found)

    def revoke_all(self):
        with self.session_lock:
            found = list(self.sessions.items())
            self.sessions.clear()
            self.revoked.update(sid for sid, _ in found)
        for _, session in found:
            self.remember(session, revoked=True)
        self.rotate_token()

    def blocked(self, ip: str) -> bool:
        now = time.time()
        recent = [t for t in self.failures.get(ip, []) if now - t < 600]
        self.failures[ip] = recent
        return len(recent) >= 20

    def watch_idle(self, server):
        while self.server is server:
            time.sleep(30)
            if self.server is server and time.time() - self.last_activity > PHONE_IDLE_LIMIT:
                self.stop()
                self.api._phone_auto_off()

    def refresh_network(self):
        with self.network_lock:
            if self.network and time.time() - self.network_at < NETWORK_TTL:
                return
            self.network, self.network_at = home_network(), time.time()

    def client_allowed(self, address: str) -> bool:
        try:
            ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_loopback or ip.is_link_local:
            return True
        if ip.version == 4:
            v4_networks = (self.network or {}).get("v4_networks") or []
            if v4_networks:
                return any(ip in ipaddress.ip_network(n) for n in v4_networks)
            return ip.is_private
        networks = (self.network or {}).get("v6_networks") or []
        return any(ip in ipaddress.ip_network(n) for n in networks)

    def addresses(self) -> list[str]:
        port = self.server.server_address[1]
        net = self.network or {}
        ipv4 = net.get("ipv4") or [lan_ip()]
        urls = [f"http://{a}:{port}/?k={self.token}" for a in ipv4]
        urls += [f"http://[{a}]:{port}/?k={self.token}" for a in net.get("ipv6") or []]
        return urls

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self):
        if self.server:
            return
        phone = self
        self.rotate_token()
        self.sessions, self.revoked, self.failures, self.adds = {}, set(), {}, deque()
        self.last_activity = time.time()

        class Handler(BaseHTTPRequestHandler):
            timeout = 60

            def log_message(self, *args):
                pass

            def _json(self, code: int, payload, revalidate: bool = False):
                if self.command == "PUT" and not getattr(self, "body_read", False):
                    drain_body(self)
                body = json.dumps(payload, ensure_ascii=False).encode()
                etag = f'"{hashlib.sha1(body).hexdigest()[:20]}"'
                if revalidate and code == 200 and self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "private, no-cache")
                    self.end_headers()
                    return
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                if revalidate:
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "private, no-cache")
                else:
                    self.send_header("Cache-Control", "no-store")
                for name, value in SECURITY_HEADERS.items():
                    self.send_header(name, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _session(self, method: str, path: str, query: dict) -> dict | None:
                self.new_session, self.revoked_session = None, False
                cookie = re.search(r"salvai=([\w-]+)", self.headers.get("Cookie") or "")
                sid = cookie.group(1) if cookie else ""
                session = phone.session_for(sid)
                if session:
                    return session
                if method == "GET" and path == "/" and secrets.compare_digest(query.get("k", ""), phone.token):
                    self.new_session = phone.open_session(self.client_address[0], self.headers.get("User-Agent"))
                    return phone.session_for(self.new_session)
                self.revoked_session = sid in phone.revoked
                return None

            def _same_origin(self) -> bool:
                if self.headers.get("X-Salvai") != "1":
                    return False
                origin = self.headers.get("Origin")
                if not origin:
                    return True
                return urllib.parse.urlparse(origin).netloc == (self.headers.get("Host") or "")

            def _handle(self, method: str):
                ip = self.client_address[0]
                if not phone.client_allowed(ip) or not is_ip_literal(host_name(self.headers.get("Host"))):
                    return self._json(403, {"error": "Acesso permitido só pela rede local, abrindo o QR code."})
                if phone.blocked(ip):
                    return self._json(429, {"error": "Muitas tentativas. Espere alguns minutos."})
                url = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                session = self._session(method, url.path, query)
                if not session:
                    if self.revoked_session:
                        return self._json(
                            403,
                            {
                                "error": "Este aparelho foi desconectado no computador. Peça um QR code novo.",
                                "revoked": True,
                            },
                        )
                    phone.failures.setdefault(ip, []).append(time.time())
                    return self._json(403, {"error": "Abra pelo QR code que aparece no Salvaí do computador."})
                if method in ("POST", "PUT") and not self._same_origin():
                    return self._json(403, {"error": "origem inválida"})
                phone.last_activity = time.time()
                session.update(ip=ip, seen=time.time())
                self.session = session
                try:
                    phone.route(self, method, url.path, query)
                except (ConnectionError, BrokenPipeError):
                    pass
                except (KeyError, ValueError) as e:
                    self._json(400, {"error": str(e)})
                except Exception:
                    self._json(500, {"error": "Algo deu errado no computador. Tente de novo."})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_HEAD(self):
                self._handle("HEAD")

            def do_PUT(self):
                self._handle("PUT")

        self.server = None
        for server_class, host in ((DualStackServer, "::"), (ExclusiveHTTPServer, "0.0.0.0")):
            for port in (PHONE_PORT, 0):
                try:
                    self.server = server_class((host, port), Handler)
                    break
                except OSError:
                    continue
            if self.server:
                break
        if not self.server:
            raise RuntimeError("não foi possível abrir o acesso na rede")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self.refresh_network, daemon=True).start()
        threading.Thread(target=self.watch_idle, args=(self.server,), daemon=True).start()

    def stop(self):
        if self.server:
            server, self.server = self.server, None
            server.shutdown()
            server.server_close()
            with self.session_lock:
                active, self.sessions = list(self.sessions.values()), {}
            for session in active:
                self.remember(session)
            with self.upload_lock:
                pending, self.uploads = list(self.uploads.values()), {}
            drop_parts(pending)

    def inbox(self) -> Path:
        return Path(self.api._out_dir) / PHONE_INBOX

    def plan_uploads(self, session: dict, entries) -> dict:
        if not isinstance(entries, list) or not 1 <= len(entries) <= PHONE_SEND_BATCH:
            raise ValueError("Escolha o que enviar.")
        parsed = []
        for entry in entries:
            size = entry.get("size") if isinstance(entry, dict) else None
            if type(size) is not int or not 0 <= size < 1 << 42:
                raise ValueError("Arquivo inválido.")
            parsed.append((clean_name(entry.get("name")), size))
        inbox = self.inbox()
        inbox.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(inbox).free < sum(size for _, size in parsed):
            raise ValueError("Falta espaço no computador para receber esses arquivos.")
        batch, replies, finished = secrets.token_hex(6), [], []
        with self.upload_lock:
            for name, size in parsed:
                key = (session["id"], name, size)
                same = (j for j in self.uploads.values() if (j["owner"], j["name"], j["size"]) == key)
                job = next((j for j in same if j["batch"] != batch), None)
                if not job:
                    if len(self.uploads) >= PHONE_MAX_UPLOADS:
                        raise ValueError("Envios demais de uma vez. Espere os outros terminarem.")
                    job_id = secrets.token_hex(8)
                    job = {
                        "id": job_id,
                        "owner": session["id"],
                        "name": name,
                        "size": size,
                        "received": 0,
                        "dest": inbox / name,
                        "root": None,
                        "part": inbox / f"{name}.{job_id}.salvai-part",
                        "state": "waiting",
                        "writing": False,
                        "touched": 0.0,
                    }
                    self.uploads[job_id] = job
                job.update(batch=batch, count=len(parsed), device=session["name"])
                replies.append({"id": job["id"], "offset": job["received"]})
                if size == 0:
                    finished.append(self.complete(job))
        for job in finished:
            self.announce(job)
        return {"uploads": replies, "chunk": PHONE_CHUNK}

    def complete(self, job: dict) -> dict:
        finish_job(job)
        del self.uploads[job["id"]]
        self.received.appendleft(
            {
                "id": job["id"],
                "name": job["dest"].name,
                "path": job["dest"],
                "size": job["size"],
                "device": job["device"],
                "at": time.time(),
            }
        )
        return job

    def announce(self, job: dict):
        last = not any(j["batch"] == job["batch"] for j in self.uploads.values())
        self.api._phone_received(job if last else None)

    def receive(self, h, session: dict, query: dict):
        length = int(h.headers.get("Content-Length") or -1)
        if not 0 <= length <= PHONE_MAX_CHUNK:
            raise ValueError("Pedaço de arquivo grande demais.")
        offset = int(query.get("offset", "-1"))
        with self.upload_lock:
            job = self.uploads.get(query.get("t", ""))
            if not job or job["owner"] != session["id"]:
                raise ValueError("Esse envio não existe mais. Escolha o arquivo de novo.")
            if job["writing"] or offset != job["received"] or offset + length > job["size"]:
                return h._json(409, {"received": job["received"]})
            job.update(writing=True, state="sending", touched=time.time())
        h.body_read = True
        try:
            written = write_part(job["part"], offset, h.rfile, length)
        except OSError as e:
            raise ValueError("Não deu para gravar o arquivo no computador.") from e
        finally:
            job["writing"] = False
        with self.upload_lock:
            job["received"], job["touched"] = offset + written, time.time()
            done = job["received"] == job["size"]
            if done:
                self.complete(job)
        if done:
            self.announce(job)
        h._json(200, {"received": job["received"], "done": done})

    def incoming(self) -> dict | None:
        now = time.time()
        with self.upload_lock:
            live = [j for j in self.uploads.values() if now - j["touched"] < 20]
        if not live:
            return None
        return {
            "files": len(live),
            "done": sum(j["received"] for j in live),
            "total": sum(j["size"] for j in live),
        }

    def received_file(self, entry_id: str) -> Path | None:
        entry = next((r for r in list(self.received) if r["id"] == entry_id), None)
        return entry["path"] if entry and entry["path"].is_file() else None

    def route(self, h, method: str, path: str, query: dict):
        api = self.api
        if method == "GET" and path == "/":
            page = (BASE / "ui" / "mobile" / "index.html").read_bytes()
            h.send_response(200)
            if getattr(h, "new_session", None):
                h.send_header("Set-Cookie", f"salvai={h.new_session}; Path=/; SameSite=Strict; HttpOnly")
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(page)))
            h.send_header("Cache-Control", "no-store")
            h.send_header("Content-Security-Policy", MOBILE_CSP)
            for name, value in SECURITY_HEADERS.items():
                h.send_header(name, value)
            h.end_headers()
            h.wfile.write(page)
            return
        if method in ("GET", "HEAD") and path in ("/mobile.css", "/mobile.js"):
            return send_file(h, BASE / "ui" / "mobile" / path.lstrip("/"), as_attachment=False, head=method == "HEAD")
        if method == "GET" and path == "/api/state":
            downloads = [dict(api._report(i), thumb=i.get("thumb")) for i in api._ordered()]
            payload = {"version": APP_VERSION, "computer": socket.gethostname(), "downloads": downloads}
            return h._json(200, payload, revalidate=True)
        if method == "POST" and path == "/api/add":
            body = read_json_body(h)
            now = time.time()
            while self.adds and now - self.adds[0] > 60:
                self.adds.popleft()
            if len(self.adds) >= 20:
                return h._json(429, {"error": "Muitos pedidos em pouco tempo. Espere um minuto."})
            self.adds.append(now)
            url = str(body.get("url", "")).strip()
            validate_remote_url(url)
            fmt, quality = normalize_request(body.get("format", "mp4"), body.get("quality", "max"))
            items = api._enqueue(url, fmt, quality, source="phone")
            return h._json(200, {"queued": len(items)})
        if method == "POST" and path == "/api/files/forget":
            return h._json(200, {"ok": api._forget(str(read_json_body(h).get("id", "")))})
        if method == "POST" and path == "/api/files/clear":
            api._clear_saved()
            return h._json(200, {"ok": True})
        if method == "POST" and path == "/api/files/trash":
            return h._json(200, {"trashed": api._trash(str(read_json_body(h).get("id", "")))})
        if method == "GET" and path == "/api/files":
            return h._json(200, {"files": api._phone_files()}, revalidate=True)
        if method == "POST" and path == "/api/send":
            return h._json(200, self.plan_uploads(h.session, read_json_body(h).get("files")))
        if method == "PUT" and path == "/api/upload":
            return self.receive(h, h.session, query)
        if method in ("GET", "HEAD") and path == "/api/file":
            target = api._saved_file(query.get("id", ""))
            if not target:
                raise ValueError("Arquivo não encontrado.")
            return send_file(h, target, as_attachment=query.get("dl") == "1", head=method == "HEAD")
        h._json(404, {"error": "não encontrado"})

    def status(self) -> dict:
        if not self.server:
            return {"on": False}
        if not self.network or time.time() - self.network_at > NETWORK_TTL:
            threading.Thread(target=self.refresh_network, daemon=True).start()
        urls = self.addresses()
        now = time.time()
        with self.session_lock:
            live = sorted(self.sessions.values(), key=lambda d: d["since"])
        devices = [
            {
                "id": d["id"],
                "name": d["name"],
                "ip": d["ip"],
                "since": d["since"],
                "seen": d["seen"],
                "online": now - d["seen"] < 20,
            }
            for d in live
        ]
        live_ids = {d["id"] for d in live}
        history = [h for h in self.api._cfg.get("phone_history", []) if h["id"] not in live_ids]
        if not self.qr or self.qr[0] != urls[0]:
            svg = segno.make(urls[0], error="m").svg_inline(border=2, dark="#111114", light="#ffffff", omitsize=True)
            self.qr = (urls[0], svg)
        qr = self.qr[1]
        net = self.network or {}
        return {
            "on": True,
            "url": urls[0],
            "others": urls[1:],
            "qr": qr,
            "network": {
                "ready": self.network is not None,
                "kind": net.get("kind"),
                "name": net.get("name"),
                "public": net.get("public", False),
            },
            "port": self.server.server_address[1],
            "devices": devices,
            "history": history,
            "incoming": self.incoming(),
            "received": [{key: r[key] for key in ("id", "name", "size", "device", "at")} for r in list(self.received)],
        }


ROOM_IDLE_LIMIT = 30 * 60
ROOM_TICK = 15
ROOM_POLL = 1.5
ROOM_CHUNK = 8 << 20
ROOM_MAX_CHUNK = 16 << 20
ROOM_MAX_FILES = 5000
ROOM_MAX_ITEMS = 200
ROOM_MAX_PENDING = 8
ROOM_OFFER_BATCH = 50
ROOM_OFFER_BODY = 4 << 20
ROOM_RISKY = {
    ".exe",
    ".bat",
    ".cmd",
    ".msi",
    ".msix",
    ".ps1",
    ".vbs",
    ".js",
    ".jse",
    ".wsf",
    ".scr",
    ".com",
    ".cpl",
    ".lnk",
    ".reg",
    ".jar",
    ".hta",
}
ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_LINK_RE = re.compile(r"(https://[a-z0-9-]+\.trycloudflare\.com)(?:/\S*)?", re.I)
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
CLOUDFLARED_REPO = "cloudflare/cloudflared"
CLOUDFLARED_ASSET = "cloudflared-windows-amd64.exe"
CLOUDFLARED_PREFIX = "https://github.com/cloudflare/cloudflared/releases/download/"
CLOUDFLARED_PATH = BIN_DIR / "cloudflared.exe"
CLOUDFLARED_MAX_AGE = 60 * 86400
ROOM_SCHEME = "https"
ROOM_JOIN_RETRY = 45
DOH_URL = "https://cloudflare-dns.com/dns-query?type=A&name="
ROOM_PAGES = {"/": "index.html", "/room.css": "room.css", "/room.js": "room.js"}
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_cloudflared_lock = threading.Lock()


def release_checksums(body: str) -> dict[str, str]:
    found = re.findall(r"^\s*([\w.-]+):\s*([0-9a-fA-F]{64})\s*$", body or "", re.M)
    return {name: digest.lower() for name, digest in found}


def ensure_cloudflared(progress=None) -> Path:
    with _cloudflared_lock:
        if CLOUDFLARED_PATH.exists() and time.time() - CLOUDFLARED_PATH.stat().st_mtime < CLOUDFLARED_MAX_AGE:
            return CLOUDFLARED_PATH
        tmp = CLOUDFLARED_PATH.with_name("cloudflared.exe.part")
        try:
            release = github_latest(CLOUDFLARED_REPO)
            assets = {a["name"]: a["browser_download_url"] for a in release.get("assets") or []}
            url = assets.get(CLOUDFLARED_ASSET, "")
            expected = release_checksums(release.get("body") or "").get(CLOUDFLARED_ASSET)
            if not url.startswith(CLOUDFLARED_PREFIX) or not expected:
                raise RuntimeError("não achei o conector oficial da Cloudflare")
            data = download(url, progress)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError("o conector baixado não confere com o hash oficial")
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            tmp.replace(CLOUDFLARED_PATH)
        except Exception:
            tmp.unlink(missing_ok=True)
            if CLOUDFLARED_PATH.exists():
                return CLOUDFLARED_PATH
            raise
        return CLOUDFLARED_PATH


class Tunnel:
    def __init__(self):
        self.proc, self.url, self.found = None, "", ""
        self.ready = threading.Event()

    def start(self, port: int, exe: Path, timeout: float = 60) -> str:
        self.proc = subprocess.Popen(
            [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        if not self.ready.wait(timeout) or not self.url:
            self.stop()
            raise RuntimeError("a Cloudflare não abriu o link agora. Tente de novo em instantes")
        return self.url

    def _read(self, proc):
        for line in proc.stderr:
            match = TUNNEL_URL_RE.search(line)
            if match and match.group(0).lower() != "https://api.trycloudflare.com":
                self.found = match.group(0).lower()
            if self.found and "Registered tunnel connection" in line:
                self.url = self.found
                self.ready.set()
        self.ready.set()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


def dns_published(host: str) -> bool:
    req = urllib.request.Request(DOH_URL + urllib.parse.quote(host), headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read() or b"{}")
    return data.get("Status") == 0 and bool(data.get("Answer"))


def wait_public(url: str, timeout: float = 30) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if dns_published(host):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def new_room_code() -> str:
    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(6))


def normalize_code(code) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def format_code(code: str) -> str:
    return f"{code[:3]} {code[3:]}" if code else ""


def clean_label(text, fallback: str = "") -> str:
    label = re.sub(r"[\x00-\x1f<>]", "", str(text or "")).strip()[:40]
    return label or fallback


def clean_name(name) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip().rstrip(". ")
    if text.split(".")[0].upper() in RESERVED_NAMES:
        text = "_" + text
    return text[:180] or "arquivo"


def clean_rel(rel) -> list[str]:
    parts = [p for p in re.split(r"[\\/]+", str(rel or "")) if p not in ("", ".", "..")]
    return [clean_name(p) for p in parts] or ["arquivo"]


def unique_path(path: Path) -> Path:
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def is_risky(name: str) -> bool:
    return Path(name).suffix.lower() in ROOM_RISKY


def scan_local(path: Path) -> dict:
    path = Path(path)
    if path.is_file():
        return {
            "kind": "file",
            "name": path.name,
            "files": [{"rel": path.name, "size": file_size(path), "path": str(path)}],
        }
    if not path.is_dir():
        raise ValueError("Não achei esse arquivo.")
    files = []
    for root, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not Path(root, d).is_symlink())
        for name in sorted(names):
            full = Path(root, name)
            if full.is_symlink() or not full.is_file():
                continue
            files.append({"rel": full.relative_to(path.parent).as_posix(), "size": file_size(full), "path": str(full)})
            if len(files) > ROOM_MAX_FILES:
                raise ValueError(f"Essa pasta tem arquivos demais (o máximo é {ROOM_MAX_FILES}).")
    if not files:
        raise ValueError("Essa pasta está vazia.")
    return {"kind": "folder", "name": path.name, "files": files}


def make_item(owner: str, kind: str, name: str, files: list[dict]) -> dict:
    return {
        "id": secrets.token_hex(6),
        "owner": owner,
        "kind": kind,
        "name": clean_name(name),
        "files": files,
        "size": sum(f["size"] for f in files),
        "count": len(files),
        "risky": any(is_risky(f["rel"]) for f in files),
        "fetched": [],
    }


def item_signature(item: dict) -> tuple:
    return (item["kind"], item["name"], tuple((f["rel"], f["size"]) for f in item["files"]))


def public_item(item: dict) -> dict:
    return {key: item[key] for key in ("id", "kind", "name", "size", "count", "risky")}


def parse_offer(entry) -> dict:
    if not isinstance(entry, dict) or entry.get("kind") not in ("file", "folder"):
        raise ValueError("Item inválido.")
    files = entry.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= ROOM_MAX_FILES:
        raise ValueError("Lista de arquivos inválida.")
    if entry["kind"] == "file" and len(files) != 1:
        raise ValueError("Lista de arquivos inválida.")
    clean = []
    for f in files:
        size = f.get("size") if isinstance(f, dict) else None
        if type(size) is not int or not 0 <= size < 1 << 42 or not isinstance(f.get("rel"), str):
            raise ValueError("Arquivo inválido.")
        clean.append({"rel": "/".join(clean_rel(f["rel"])), "size": size})
    return {"kind": entry["kind"], "name": str(entry.get("name") or clean[0]["rel"]), "files": clean}


def plan_targets(item: dict, dest: Path) -> list[tuple[Path, Path]]:
    if item["kind"] == "file":
        target = dest / clean_name(item["name"])
        return [(target, target)]
    root = unique_path(dest / clean_name(item["name"]))
    plan = []
    for f in item["files"]:
        parts = clean_rel(f["rel"])
        plan.append((root.joinpath(*parts[1:]) if len(parts) > 1 else root / parts[0], root))
    return plan


def new_job(item: dict, index: int, target: Path, root: Path) -> dict:
    return {
        "id": secrets.token_hex(8),
        "item": item["id"],
        "owner": item["owner"],
        "f": index,
        "size": item["files"][index]["size"],
        "received": 0,
        "dest": target,
        "root": root,
        "part": target.with_name(target.name + ".salvai-part"),
        "state": "waiting",
        "error": "",
    }


def finish_job(job: dict) -> None:
    job["dest"].parent.mkdir(parents=True, exist_ok=True)
    if not job["part"].exists():
        job["part"].write_bytes(b"")
    final = unique_path(job["dest"])
    job["part"].replace(final)
    if job["root"] == job["dest"]:
        job["root"] = final
    job["dest"], job["state"] = final, "done"


def restart_jobs(jobs: list[dict]) -> bool:
    if not jobs or all(j["state"] == "done" for j in jobs):
        return False
    for job in jobs:
        if job["state"] == "error":
            job["state"], job["error"] = "waiting", ""
    return True


def job_progress(jobs: list[dict]) -> dict | None:
    if not jobs:
        return None
    states = {j["state"] for j in jobs}
    if states == {"done"}:
        state = "done"
    elif "error" in states:
        state = "error"
    else:
        state = "sending" if "sending" in states else "waiting"
    return {
        "state": state,
        "done": sum(j["received"] for j in jobs),
        "total": sum(j["size"] for j in jobs),
        "files": len(jobs),
        "finished": sum(1 for j in jobs if j["state"] == "done"),
        "error": next((j["error"] for j in jobs if j["error"]), ""),
    }


def drop_parts(jobs: list[dict]) -> None:
    for job in jobs:
        if job["state"] != "done":
            try:
                job["part"].unlink(missing_ok=True)
            except OSError:
                pass


def write_part(part: Path, offset: int, source, length: int) -> int:
    part.parent.mkdir(parents=True, exist_ok=True)
    remaining = length
    with open(part, "r+b" if part.exists() else "wb") as f:
        f.seek(offset)
        f.truncate()
        while remaining > 0:
            try:
                chunk = source.read(min(1 << 20, remaining))
            except (ConnectionError, TimeoutError):
                break
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)
    return length - remaining


def zip_entries(items: list[dict]) -> list[tuple[str, str]]:
    seen, entries = set(), []
    for item in items:
        for f in item["files"]:
            if not Path(f["path"]).is_file():
                continue
            head, _, leaf = f["rel"].rpartition("/")
            stem, ext = os.path.splitext(leaf)
            name, n = f["rel"], 2
            while name.lower() in seen:
                name = f"{head}/{stem} ({n}){ext}" if head else f"{stem} ({n}){ext}"
                n += 1
            seen.add(name.lower())
            entries.append((name, f["path"]))
    return entries


class StreamSink:
    def __init__(self, out):
        self.out = out

    def write(self, data) -> int:
        self.out.write(data)
        return len(data)

    def flush(self):
        self.out.flush()


def room_whatsapp_message(url: str, code: str, host: str) -> str:
    return (
        "🔁 *Sala de troca do Salvaí*\n\n"
        f"{host} abriu uma sala para vocês trocarem arquivos e pastas.\n\n"
        f"1. Abra: {url}\n"
        f"2. Digite o código: *{code}*\n\n"
        "Funciona no navegador do celular ou do PC, sem instalar nada. "
        "Se você tem o Salvaí, também dá para entrar pelo botão Sala de troca.\n"
        "⚠️ O link para de funcionar quando a sala fecha."
    )


class RoomBase:
    role = ""

    def __init__(self, api: "Api"):
        self.api = api
        self.lock = threading.RLock()
        self.phase, self.error, self.reason = "idle", "", ""
        self.name = ""
        self.jobs: dict[str, dict] = {}

    @property
    def active(self) -> bool:
        return self.phase in ("starting", "joining", "pending", "open")

    def item_jobs(self, item_id: str) -> list[dict]:
        return [j for j in self.jobs.values() if j["item"] == item_id]

    def item_root(self, item_id: str) -> Path | None:
        jobs = self.item_jobs(item_id)
        return jobs[0]["root"] if jobs else None


class Room(RoomBase):
    role = "host"

    def __init__(self, api: "Api"):
        super().__init__(api)
        self.server, self.tunnel = None, None
        self.step, self.progress = "", None
        self.url = self.public_host = self.code = ""
        self.sessions: dict[str, dict] = {}
        self.revoked: set[str] = set()
        self.failures: dict[str, list[float]] = {}
        self.join_failures: deque = deque()
        self.items: dict[str, dict] = {}
        self.busy, self.last_activity = 0, 0.0

    def start(self, name: str):
        with self.lock:
            if self.active:
                return
            self.name = clean_label(name, socket.gethostname())
            self.phase, self.step, self.error, self.reason = "starting", "Preparando a sala…", "", ""
        threading.Thread(target=self._open, daemon=True).start()

    def _progress(self, fraction: float):
        self.progress = round(fraction * 100)
        self.api._room_changed()

    def _set_step(self, text: str):
        self.step, self.progress = text, None
        self.api._room_changed()

    def _open(self):
        try:
            self._set_step("Baixando o conector da Cloudflare (só na primeira vez)…")
            exe = ensure_cloudflared(self._progress)
            self._set_step("Abrindo o link público…")
            self._serve()
            self.tunnel = Tunnel()
            url = self.tunnel.start(self.server.server_address[1], exe)
            self.public_host = urllib.parse.urlparse(url).netloc
            self._set_step("Testando o link…")
            wait_public(url)
            with self.lock:
                cancelled = self.phase != "starting"
                if not cancelled:
                    self.url, self.code = url, new_room_code()
                    self.phase, self.last_activity = "open", time.time()
            if cancelled:
                return self._shutdown()
            threading.Thread(target=self._watch, daemon=True).start()
        except Exception as e:
            self._shutdown()
            if self.phase == "starting":
                self.phase, self.error = "error", clean_error(e)
        self.api._room_changed()

    def _serve(self):
        room = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 120

            def log_message(self, *args):
                pass

            def _json(self, code: int, payload, cookie: str = ""):
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if cookie:
                    self.send_header("Set-Cookie", f"sala={cookie}; Path=/; Secure; HttpOnly; SameSite=Strict")
                for name, value in SECURITY_HEADERS.items():
                    self.send_header(name, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _trusted(self) -> bool:
                origin = self.headers.get("Origin")
                if origin and origin != f"{ROOM_SCHEME}://{room.public_host}":
                    return False
                return self.headers.get("X-Sala") == "1"

            def _handle(self, method: str):
                ip = (self.headers.get("Cf-Connecting-Ip") or self.client_address[0]).strip()
                host = (self.headers.get("Host") or "").lower()
                if not room.public_host or host != room.public_host:
                    return self._json(403, {"error": "Endereço inválido."})
                if room.blocked(ip):
                    return self._json(429, {"error": "Muitas tentativas. Espere alguns minutos."})
                if method in ("POST", "PUT") and not self._trusted():
                    return self._json(403, {"error": "Abra a sala pelo link que te mandaram."})
                url = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                try:
                    room.route(self, method, url.path, query, ip)
                except (ConnectionError, TimeoutError):
                    pass
                except PermissionError as e:
                    self._json(403, {"error": str(e)})
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                except Exception:
                    self._json(500, {"error": "Algo deu errado no computador de quem criou a sala."})

            def do_GET(self):
                self._handle("GET")

            def do_HEAD(self):
                self._handle("HEAD")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

        self.server = ExclusiveHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def blocked(self, ip: str) -> bool:
        now = time.time()
        recent = [t for t in self.failures.get(ip, []) if now - t < 600]
        self.failures[ip] = recent
        return len(recent) >= 10

    def fail(self, ip: str):
        self.failures.setdefault(ip, []).append(time.time())

    def touch(self):
        self.last_activity = time.time()

    def route(self, h, method: str, path: str, query: dict, ip: str):
        if method in ("GET", "HEAD") and path in ROOM_PAGES:
            return self.page(h, ROOM_PAGES[path], method == "HEAD")
        if method == "GET" and path == "/api/ping":
            return h._json(200, {"ok": True})
        match = re.search(r"(?:^|;\s*)sala=([\w-]+)", h.headers.get("Cookie") or "")
        sid = match.group(1) if match else ""
        session = self.sessions.get(sid)
        if method == "GET" and path == "/api/me":
            state = session["state"] if session else "revoked" if sid in self.revoked else "none"
            return h._json(200, {"state": state, "host": self.name, "name": session["name"] if session else ""})
        if method == "POST" and path == "/api/join":
            return self.join(h, ip, session)
        if not session or session["state"] != "approved":
            self.fail(ip)
            if sid in self.revoked:
                raise PermissionError("Quem criou a sala tirou você dela.")
            raise PermissionError("Entre na sala com o código para continuar.")
        session["seen"] = time.time()
        if method == "GET" and path == "/api/state":
            return h._json(200, self.guest_state(session))
        self.touch()
        if method == "GET" and path == "/api/files":
            item = self.host_item(query.get("item", ""))
            return h._json(200, {"files": [{"rel": f["rel"], "size": f["size"]} for f in item["files"]]})
        if method == "POST" and path == "/api/offer":
            return h._json(200, {"ids": self.offer(session, read_json_body(h, ROOM_OFFER_BODY).get("items"))})
        if method == "POST" and path == "/api/unoffer":
            self.remove_item(str(read_json_body(h).get("id", "")), session["id"])
            return h._json(200, {"ok": True})
        if method == "PUT" and path == "/api/upload":
            return h._json(*self.receive(h, session, query))
        if method in ("GET", "HEAD") and path == "/api/file":
            item = self.host_item(query.get("item", ""))
            index = int(query.get("f", "0"))
            if not 0 <= index < len(item["files"]):
                raise ValueError("Não achei esse arquivo.")
            target = Path(item["files"][index]["path"])
            if not target.is_file():
                raise ValueError("Esse arquivo não está mais no computador de quem criou a sala.")
            self.mark_fetched(item, session)
            return self.serving(lambda: send_file(h, target, query.get("dl") == "1", method == "HEAD"))
        if method == "GET" and path == "/api/zip":
            items = [self.host_item(i) for i in query.get("items", "").split(",") if i]
            if not items:
                raise ValueError("Escolha o que baixar.")
            for item in items:
                self.mark_fetched(item, session)
            return self.serving(lambda: self.send_zip(h, items))
        if method == "POST" and path == "/api/leave":
            self.kick(session["id"], revoke=False)
            return h._json(200, {"ok": True})
        h._json(404, {"error": "não encontrado"})

    def page(self, h, name: str, head: bool):
        target = BASE / "ui" / "room" / name
        if name != "index.html":
            return send_file(h, target, as_attachment=False, head=head)
        page = target.read_bytes()
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(page)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("Content-Security-Policy", MOBILE_CSP)
        for key, value in SECURITY_HEADERS.items():
            h.send_header(key, value)
        h.end_headers()
        if not head:
            h.wfile.write(page)

    def join(self, h, ip: str, session: dict | None):
        body = read_json_body(h)
        if session:
            return h._json(200, {"state": session["state"]})
        now = time.time()
        with self.lock:
            while self.join_failures and now - self.join_failures[0] > 600:
                self.join_failures.popleft()
            if len(self.join_failures) >= 60:
                return h._json(429, {"error": "A sala recebeu tentativas erradas demais. Peça um link novo."})
            if not secrets.compare_digest(normalize_code(body.get("code")), self.code):
                self.fail(ip)
                self.join_failures.append(now)
                return h._json(403, {"error": "Código errado. Confira com quem te mandou o link."})
            if sum(1 for s in self.sessions.values() if s["state"] == "pending") >= ROOM_MAX_PENDING:
                return h._json(429, {"error": "Tem muita gente esperando para entrar. Tente daqui a pouco."})
            sid = secrets.token_urlsafe(24)
            agent = h.headers.get("User-Agent") or ""
            session = {
                "id": secrets.token_hex(6),
                "name": clean_label(body.get("name"), device_name(agent)),
                "device": device_name(agent),
                "state": "pending",
                "since": now,
                "seen": now,
            }
            self.sessions[sid] = session
        self.touch()
        self.api._room_event("join", session["name"])
        h._json(200, {"state": "pending"}, cookie=sid)

    def approve(self, person_id: str):
        with self.lock:
            for session in self.sessions.values():
                if session["id"] == person_id and session["state"] == "pending":
                    session["state"], session["seen"] = "approved", time.time()
        self.touch()
        self.api._room_changed()

    def kick(self, person_id: str, revoke: bool = True):
        with self.lock:
            found = [sid for sid, s in self.sessions.items() if s["id"] == person_id]
            for sid in found:
                del self.sessions[sid]
                if revoke:
                    self.revoked.add(sid)
            gone = [item_id for item_id, item in self.items.items() if item["owner"] == person_id]
        for item_id in gone:
            self.remove_item(item_id, person_id)
        self.api._room_changed()

    def host_item(self, item_id: str) -> dict:
        item = self.items.get(item_id)
        if not item or item["owner"] != "host":
            raise ValueError("Não achei esse arquivo.")
        return item

    def mark_fetched(self, item: dict, session: dict):
        if session["name"] not in item["fetched"]:
            item["fetched"].append(session["name"])
            self.api._room_changed()

    def serving(self, action):
        with self.lock:
            self.busy += 1
        try:
            action()
        finally:
            with self.lock:
                self.busy -= 1
            self.touch()

    def send_zip(self, h, items: list[dict]):
        name = clean_name(items[0]["name"] if len(items) == 1 else f"Sala de {self.name}")
        fallback = re.sub(r"[^ -~]", "_", name).replace('"', "")
        h.send_response(200)
        h.send_header("Content-Type", "application/zip")
        h.send_header("Cache-Control", "no-store")
        h.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{fallback}.zip\"; filename*=UTF-8''{urllib.parse.quote(name)}.zip",
        )
        for key, value in SECURITY_HEADERS.items():
            h.send_header(key, value)
        h.end_headers()
        with zipfile.ZipFile(StreamSink(h.wfile), "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for arcname, source in zip_entries(items):
                archive.write(source, arcname)

    def offer(self, session: dict, entries) -> list[str]:
        if not isinstance(entries, list) or not 1 <= len(entries) <= ROOM_OFFER_BATCH:
            raise ValueError("Nada para adicionar.")
        parsed = [parse_offer(e) for e in entries]
        ids = []
        with self.lock:
            mine = [i for i in self.items.values() if i["owner"] == session["id"]]
            for entry in parsed:
                item = make_item(session["id"], entry["kind"], entry["name"], entry["files"])
                same = next((i for i in mine if item_signature(i) == item_signature(item)), None)
                if same:
                    ids.append(same["id"])
                    continue
                if len(mine) >= ROOM_MAX_ITEMS:
                    raise ValueError("A sala já tem itens demais.")
                self.items[item["id"]] = item
                mine.append(item)
                ids.append(item["id"])
        self.api._room_changed()
        return ids

    def add_paths(self, paths: list[str]):
        for path in paths:
            entry = scan_local(Path(path))
            item = make_item("host", entry["kind"], entry["name"], entry["files"])
            with self.lock:
                if sum(1 for i in self.items.values() if i["owner"] == "host") >= ROOM_MAX_ITEMS:
                    raise ValueError("A sala já tem itens demais.")
                self.items[item["id"]] = item
        self.touch()
        self.api._room_changed()

    def remove_item(self, item_id: str, owner: str = "host") -> bool:
        with self.lock:
            item = self.items.get(item_id)
            if not item or item["owner"] != owner:
                return False
            del self.items[item_id]
            jobs = self.item_jobs(item_id)
            for job in jobs:
                del self.jobs[job["id"]]
        drop_parts(jobs)
        self.api._room_changed()
        return True

    def download(self, ids, dest: Path) -> int:
        count = 0
        with self.lock:
            chosen = [i for i in self.items.values() if i["owner"] != "host" and (ids == "*" or i["id"] in ids)]
            for item in chosen:
                count += 1
                old = self.item_jobs(item["id"])
                if restart_jobs(old):
                    continue
                for job in old:
                    del self.jobs[job["id"]]
                for index, (target, root) in enumerate(plan_targets(item, dest)):
                    job = new_job(item, index, target, root)
                    self.jobs[job["id"]] = job
                    if not job["size"]:
                        finish_job(job)
        self.touch()
        self.api._room_changed()
        return count

    def receive(self, h, session: dict, query: dict) -> tuple[int, dict]:
        length = int(h.headers.get("Content-Length") or -1)
        if not 0 <= length <= ROOM_MAX_CHUNK:
            raise ValueError("Pedaço de arquivo grande demais.")
        offset = int(query.get("offset", "-1"))
        with self.lock:
            job = self.jobs.get(query.get("t", ""))
            if not job or job["owner"] != session["id"] or job["state"] not in ("waiting", "sending"):
                raise ValueError("Esse envio não existe mais.")
            if job.get("writing") or offset != job["received"] or offset + length > job["size"]:
                return 409, {"received": job["received"]}
            job["writing"], job["state"] = True, "sending"
        try:
            written = write_part(job["part"], offset, h.rfile, length)
        except OSError:
            job["state"], job["error"] = "error", "Não deu para gravar no disco."
            raise
        finally:
            job["writing"] = False
        with self.lock:
            job["received"] = offset + written
            if job["received"] == job["size"]:
                finish_job(job)
        self.api._room_changed()
        return 200, {"received": job["received"]}

    def guest_state(self, session: dict) -> dict:
        with self.lock:
            items = [public_item(i) for i in self.items.values() if i["owner"] == "host"]
            mine = [
                dict(public_item(i), progress=job_progress(self.item_jobs(i["id"])))
                for i in self.items.values()
                if i["owner"] == session["id"]
            ]
            requests = [
                {"id": j["id"], "item": j["item"], "f": j["f"], "offset": j["received"], "size": j["size"]}
                for j in self.jobs.values()
                if j["owner"] == session["id"] and j["state"] in ("waiting", "sending")
            ]
        return {
            "host": self.name,
            "me": {"id": session["id"], "name": session["name"]},
            "items": items,
            "mine": mine,
            "requests": requests,
            "chunk": ROOM_CHUNK,
        }

    def status(self) -> dict:
        now = time.time()
        with self.lock:
            people = [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "device": s["device"],
                    "state": s["state"],
                    "since": s["since"],
                    "online": now - s["seen"] < 20,
                }
                for s in sorted(self.sessions.values(), key=lambda s: s["since"])
            ]
            names = {s["id"]: s["name"] for s in self.sessions.values()}
            mine = [
                dict(public_item(i), fetched=list(i["fetched"])) for i in self.items.values() if i["owner"] == "host"
            ]
            theirs = [
                dict(public_item(i), owner=names.get(i["owner"], ""), progress=job_progress(self.item_jobs(i["id"])))
                for i in self.items.values()
                if i["owner"] != "host"
            ]
        return {
            "role": "host",
            "phase": self.phase,
            "step": self.step,
            "progress": self.progress,
            "error": self.error,
            "reason": self.reason,
            "name": self.name,
            "host": self.name,
            "url": self.url,
            "code": format_code(self.code),
            "people": people,
            "mine": mine,
            "theirs": theirs,
        }

    def _watch(self):
        while True:
            time.sleep(ROOM_TICK)
            if self.phase != "open":
                return
            if not self.tunnel.alive():
                return self.close("A conexão com a Cloudflare caiu e a sala fechou. Crie uma nova para continuar.")
            if not self.busy and time.time() - self.last_activity > ROOM_IDLE_LIMIT:
                return self.close("A sala fechou sozinha depois de 30 minutos sem uso.")

    def close(self, reason: str = ""):
        with self.lock:
            if self.phase in ("idle", "closed"):
                return
            self.phase, self.reason = ("closed" if reason else "idle"), reason
            jobs = list(self.jobs.values())
            self.sessions.clear()
            self.items.clear()
            self.jobs.clear()
        self._shutdown()
        drop_parts(jobs)
        if reason:
            self.api._room_event("closed", reason)
        self.api._room_changed()

    def _shutdown(self):
        tunnel, self.tunnel = self.tunnel, None
        server, self.server = self.server, None
        if tunnel:
            tunnel.stop()
        if server:
            server.shutdown()
            server.server_close()


class RoomError(Exception):
    def __init__(self, status: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.status, self.data = status, data or {}


class RoomClient(RoomBase):
    role = "guest"

    def __init__(self, api: "Api"):
        super().__init__(api)
        self.base = self.sid = self.host = ""
        self.state: dict = {}
        self.local: dict[str, list[str]] = {}
        self.sending: set[str] = set()
        self.uploads: deque = deque()

    def request(self, method: str, path: str, body=None, data: bytes | None = None, headers=None, raw=False):
        head = {"User-Agent": f"Salvai/{APP_VERSION}", "X-Sala": "1"}
        if self.sid:
            head["Cookie"] = f"sala={self.sid}"
        if body is not None:
            data = json.dumps(body).encode()
            head["Content-Type"] = "application/json"
        head.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=head)
        try:
            response = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            try:
                info = json.loads(e.read() or b"{}")
            except ValueError:
                info = {}
            raise RoomError(e.code, info.get("error") or f"a sala respondeu {e.code}", info) from None
        if raw:
            return response
        with response:
            cookie = re.search(r"sala=([\w-]+)", response.headers.get("Set-Cookie") or "")
            if cookie:
                self.sid = cookie.group(1)
            return json.loads(response.read() or b"{}")

    def join(self, link: str, code: str, name: str):
        match = ROOM_LINK_RE.fullmatch((link or "").strip())
        if not match:
            raise ValueError("Cole o link da sala que te mandaram (ele termina em trycloudflare.com).")
        if not normalize_code(code):
            raise ValueError("Digite o código da sala.")
        with self.lock:
            self.base = match.group(1)
            self.name = clean_label(name, socket.gethostname())
            self.phase, self.error, self.reason = "joining", "", ""
        threading.Thread(target=self._run, args=(code,), daemon=True).start()

    def _run(self, code: str):
        try:
            me = self._knock(code)
            self.phase = "pending"
            self.api._room_changed()
            while me["state"] == "pending" and self.phase == "pending":
                time.sleep(ROOM_POLL)
                me = self.request("GET", "/api/me")
            if self.phase != "pending":
                return
            if me["state"] != "approved":
                raise RuntimeError("Quem criou a sala não deixou você entrar.")
            self.host, self.phase = me.get("host", ""), "open"
            self.refresh()
            self.api._room_changed()
            threading.Thread(target=self._uploader, daemon=True).start()
            threading.Thread(target=self._downloader, daemon=True).start()
            self._sync()
        except Exception as e:
            if self.active:
                self.phase, self.error = "error", clean_error(e)
                self._cleanup()
                self.api._room_changed()

    def _knock(self, code: str) -> dict:
        deadline = time.time() + ROOM_JOIN_RETRY
        while True:
            try:
                return self.request("POST", "/api/join", {"name": self.name, "code": code})
            except OSError:
                if time.time() > deadline or self.phase != "joining":
                    raise
                time.sleep(2)

    def refresh(self):
        state = self.request("GET", "/api/state")
        with self.lock:
            self.state, self.host = state, state["host"]
            for req in state["requests"]:
                if req["id"] not in self.sending and req["item"] in self.local:
                    self.sending.add(req["id"])
                    self.uploads.append(req)

    def _sync(self):
        misses = 0
        while self.phase == "open":
            try:
                self.refresh()
                misses = 0
            except RoomError as e:
                if e.status == 403:
                    return self._end("Quem criou a sala tirou você dela.")
                misses += 1
            except OSError:
                misses += 1
            if misses >= 8:
                return self._end("A sala não responde mais. Ela pode ter sido fechada.")
            time.sleep(ROOM_POLL)

    def _uploader(self):
        while self.phase == "open":
            try:
                req = self.uploads.popleft()
            except IndexError:
                time.sleep(0.3)
                continue
            try:
                self._upload(req)
            except Exception:
                pass
            finally:
                self.sending.discard(req["id"])

    def _upload(self, req: dict):
        path = self.local[req["item"]][req["f"]]
        offset, chunk = req["offset"], self.state.get("chunk", ROOM_CHUNK)
        with open(path, "rb") as f:
            while offset < req["size"] and self.phase == "open":
                f.seek(offset)
                data = f.read(min(chunk, req["size"] - offset))
                if not data:
                    raise RuntimeError("o arquivo mudou enquanto era enviado")
                try:
                    reply = self.request(
                        "PUT",
                        f"/api/upload?t={req['id']}&offset={offset}",
                        data=data,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    offset = reply["received"]
                except RoomError as e:
                    if e.status != 409:
                        raise
                    offset = e.data["received"]

    def _downloader(self):
        while self.phase == "open":
            job = next((j for j in list(self.jobs.values()) if j["state"] == "waiting"), None)
            if not job:
                time.sleep(0.3)
                continue
            try:
                self._fetch(job)
            except Exception as e:
                job["state"], job["error"] = "error", clean_error(e)
            self.api._room_changed()

    def _fetch(self, job: dict):
        job["state"] = "sending"
        offset = job["part"].stat().st_size if job["part"].exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else None
        response = self.request("GET", f"/api/file?item={job['item']}&f={job['f']}", headers=headers, raw=True)
        with response:
            if response.status != 206:
                offset = 0
            job["part"].parent.mkdir(parents=True, exist_ok=True)
            with open(job["part"], "r+b" if offset else "wb") as out:
                out.seek(offset)
                out.truncate()
                job["received"] = offset
                while self.phase == "open" and (chunk := response.read(1 << 20)):
                    out.write(chunk)
                    job["received"] += len(chunk)
        if job["received"] >= job["size"]:
            finish_job(job)
        elif self.phase == "open":
            raise RuntimeError("A conexão caiu no meio. Clique em baixar de novo para continuar.")

    def add_paths(self, paths: list[str]):
        entries = [scan_local(Path(p)) for p in paths]
        for start in range(0, len(entries), ROOM_OFFER_BATCH):
            batch = entries[start : start + ROOM_OFFER_BATCH]
            offers = [
                {
                    "kind": e["kind"],
                    "name": e["name"],
                    "files": [{"rel": f["rel"], "size": f["size"]} for f in e["files"]],
                }
                for e in batch
            ]
            ids = self.request("POST", "/api/offer", {"items": offers})["ids"]
            with self.lock:
                for item_id, entry in zip(ids, batch, strict=True):
                    self.local[item_id] = [f["path"] for f in entry["files"]]
        self.refresh()

    def remove_item(self, item_id: str, owner: str = "") -> bool:
        self.request("POST", "/api/unoffer", {"id": item_id})
        with self.lock:
            self.local.pop(item_id, None)
        self.refresh()
        return True

    def download(self, ids, dest: Path) -> int:
        count = 0
        for item in [i for i in self.state.get("items", []) if ids == "*" or i["id"] in ids]:
            count += 1
            with self.lock:
                if restart_jobs(self.item_jobs(item["id"])):
                    continue
            files = self.request("GET", f"/api/files?item={item['id']}")["files"]
            full = dict(item, owner="host", files=files)
            with self.lock:
                for job in self.item_jobs(item["id"]):
                    del self.jobs[job["id"]]
                for index, (target, root) in enumerate(plan_targets(full, dest)):
                    job = new_job(full, index, target, root)
                    self.jobs[job["id"]] = job
                    if not job["size"]:
                        finish_job(job)
        return count

    def status(self) -> dict:
        state = self.state
        with self.lock:
            theirs = [
                dict(i, owner=self.host, progress=job_progress(self.item_jobs(i["id"]))) for i in state.get("items", [])
            ]
            mine = [dict(i, local=i["id"] in self.local) for i in state.get("mine", [])]
        return {
            "role": "guest",
            "phase": self.phase,
            "step": "",
            "progress": None,
            "error": self.error,
            "reason": self.reason,
            "name": self.name,
            "host": self.host,
            "url": self.base,
            "code": "",
            "people": [],
            "mine": mine,
            "theirs": theirs,
        }

    def _cleanup(self):
        with self.lock:
            jobs = [j for j in self.jobs.values() if j["state"] != "done"]
            for job in jobs:
                job["state"], job["error"] = "error", "interrompido"
        drop_parts(jobs)

    def _end(self, reason: str):
        with self.lock:
            if not self.active:
                return
            self.phase, self.reason = "closed", reason
        self._cleanup()
        self.api._room_event("closed", reason)

    def close(self, reason: str = ""):
        with self.lock:
            was = self.phase in ("pending", "open")
            self.phase = "idle"
        if was:
            try:
                self.request("POST", "/api/leave", {})
            except Exception:
                pass
        self._cleanup()
        self.api._room_changed()


def fresh_env() -> dict:
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def stale_bundle() -> bool:
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return False
    try:
        built = Path(sys.executable).stat().st_mtime
        bundle = Path(sys._MEIPASS).stat()
    except OSError:
        return False
    return built > getattr(bundle, "st_birthtime", bundle.st_ctime) + 2


def whatsapp_installed() -> bool:
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "whatsapp"))
        return True
    except OSError:
        return False


def whatsapp_message(url: str, network: dict) -> str:
    if network.get("kind") == "wifi" and network.get("name"):
        where = f"no Wi-Fi *{network['name']}*"
    elif network.get("kind") == "cabo":
        where = "no Wi-Fi do mesmo roteador do computador"
    else:
        where = "no mesmo Wi-Fi do computador"
    return (
        "📲 *Salvaí no celular*\n\n"
        "Abra este link para mandar vídeos e músicas para o computador baixar e assistir direto no celular:\n"
        f"{url}\n\n"
        f"⚠️ Só funciona com o celular conectado {where}.\n"
        "O link deixa de funcionar quando o modo celular é desligado no computador."
    )


def file_key(path) -> str:
    return hashlib.sha256(str(Path(path).resolve()).lower().encode()).hexdigest()[:20]


class _FileOp(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def send_to_trash(path: Path) -> None:
    op = _FileOp(wFunc=3, pFrom=str(path) + "\0", fFlags=0x0040 | 0x0010 | 0x0004 | 0x0400)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) or op.fAnyOperationsAborted or path.exists():
        raise OSError("não foi possível mandar o arquivo para a Lixeira")


def load_saved() -> list[str]:
    try:
        data = json.loads(SAVED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sums[parts[-1].lstrip("*")] = parts[0].lower()
    return sums


def download(url: str, progress=None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Salvai/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        chunks, received = [], 0
        while chunk := r.read(1 << 18):
            chunks.append(chunk)
            received += len(chunk)
            if progress and total:
                progress(received / total)
    return b"".join(chunks)


def swap_files(staged: list[tuple[Path, Path]]) -> None:
    done = []
    try:
        for new_file, dest in staged:
            old = dest.with_name(f"{dest.stem}.old{dest.suffix}")
            if old.exists():
                old.unlink()
            backup = None
            if dest.exists():
                dest.replace(old)
                backup = old
            done.append((dest, backup))
            shutil.move(str(new_file), str(dest))
    except Exception:
        for dest, backup in reversed(done):
            try:
                if dest.exists():
                    dest.unlink()
                if backup:
                    backup.replace(dest)
            except OSError:
                pass
        raise


def release_assets(release: dict, name: str, trusted_prefix: str) -> tuple[dict, dict]:
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets") or []}
    if any(not url.startswith(trusted_prefix) for url in assets.values()):
        raise RuntimeError("a release tem arquivos fora do repositório oficial")
    if name not in assets or "SHA256SUMS.txt" not in assets:
        raise RuntimeError("essa versão ainda não tem os arquivos publicados")
    return assets, parse_sums(download(assets["SHA256SUMS.txt"]).decode())


def fetch_verified(assets: dict, sums: dict, name: str, progress=None) -> bytes:
    data = download(assets[name], progress)
    if hashlib.sha256(data).hexdigest() != sums.get(name):
        raise RuntimeError(f"o arquivo {name} baixado não confere com o oficial")
    return data


def install_release(release: dict, current_exe: Path, staging: Path, progress=None, trusted_prefix: str = "") -> str:
    assets, sums = release_assets(release, "Salvai.exe", trusted_prefix)
    data = fetch_verified(assets, sums, "Salvai.exe", progress)
    staging.mkdir(parents=True, exist_ok=True)
    file = staging / "Salvai.exe"
    file.write_bytes(data)
    swap_files([(file, current_exe)])
    return release["tag_name"].lstrip("v")


def ensure_mcp(version: str = APP_VERSION) -> bool:
    try:
        (MCP_DIR / "salvai-mcp.old.exe").unlink(missing_ok=True)
    except OSError:
        pass
    if MCP_PATH.exists() and MCP_VERSION_PATH.exists() and MCP_VERSION_PATH.read_text().strip() == version:
        return False
    release = json.loads(http_get(f"https://api.github.com/repos/{APP_REPO}/releases/tags/v{version}", timeout=10))
    assets, sums = release_assets(release, "salvai-mcp.exe", f"https://github.com/{APP_REPO}/releases/download/")
    data = fetch_verified(assets, sums, "salvai-mcp.exe")
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    staged = MCP_DIR / "salvai-mcp.new.exe"
    staged.write_bytes(data)
    swap_files([(staged, MCP_PATH)])
    MCP_VERSION_PATH.write_text(version)
    return True


def claude_config_paths() -> list[Path]:
    roots = [Path(os.getenv("APPDATA", Path.home())) / "Claude"]
    roots += sorted(Path(os.getenv("LOCALAPPDATA", Path.home())).glob("Packages/*Claude*/LocalCache/Roaming/Claude"))
    return [root / "claude_desktop_config.json" for root in roots if root.is_dir()]


def register_claude(done: list[str]) -> list[str]:
    added = []
    for path in claude_config_paths():
        if str(path) in done:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            servers = data.setdefault("mcpServers", {}) if isinstance(data, dict) else None
            if not isinstance(servers, dict):
                raise ValueError("configuração do Claude em formato inesperado")
            servers["salvai"] = {"command": str(MCP_PATH)}
            temp = path.with_name(path.name + ".salvai")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        except (OSError, ValueError):
            continue
        added.append(str(path))
    return added


def cleanup_old_versions() -> None:
    if not getattr(sys, "frozen", False):
        return
    folder = Path(sys.executable).resolve().parent
    for old in folder.glob("*.old.exe"):
        try:
            old.unlink()
        except OSError:
            pass
    shutil.rmtree(CONFIG_PATH.parent / "update", ignore_errors=True)


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def remove_tree(path: Path) -> int:
    freed = 0
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                size = os.path.getsize(fp)
                os.remove(fp)
                freed += size
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass
    return freed


def is_salvai_temp_dir(d: Path) -> bool:
    if (d / "salvai-mcp.marker").exists():
        return True
    return (d / "ffmpeg.zip").exists() and (d / "ui" / "index.html").exists()


def leftover_temp_dirs() -> list[Path]:
    current = Path(getattr(sys, "_MEIPASS", "")).resolve() if hasattr(sys, "_MEIPASS") else None
    found = []
    for d in Path(os.getenv("TEMP", "")).glob("_MEI*"):
        try:
            if d.is_dir() and not d.name.endswith(".del") and d.resolve() != current and is_salvai_temp_dir(d):
                found.append(d)
        except OSError:
            pass
    return found


def cleanup_leftovers() -> int:
    freed = 0
    for d in leftover_temp_dirs():
        trash = d.with_name(d.name + ".del")
        try:
            d.rename(trash)
        except OSError:
            continue
        freed += remove_tree(trash)
    for trash in Path(os.getenv("TEMP", "")).glob("_MEI*.del"):
        freed += remove_tree(trash)
    return freed


STORAGE = [
    {
        "key": "webview",
        "name": "Cache da interface",
        "default": True,
        "desc": "Miniaturas dos vídeos e arquivos da tela do app, guardados para abrir mais rápido. "
        "Pode apagar sem medo: tudo é baixado de novo quando precisar.",
    },
    {
        "key": "ytdlp",
        "name": "Dados do YouTube",
        "default": True,
        "desc": "Informações que o motor de download guarda para reconhecer os vídeos mais rápido. "
        "Pode apagar sem medo.",
    },
    {
        "key": "temp",
        "name": "Sobras de aberturas anteriores",
        "default": True,
        "desc": "Cópias temporárias do app que ficam para trás quando ele é fechado à força "
        "(pelo Gerenciador de Tarefas, por exemplo). Pode apagar sem medo.",
    },
    {
        "key": "components",
        "name": "Componentes baixados",
        "default": False,
        "desc": "O Deno (motor que o YouTube exige quando o PC não tem Node.js) e as atualizações do motor de "
        "download. Se apagar, o app baixa de novo quando precisar.",
    },
    {
        "key": "essential",
        "name": "Essenciais",
        "default": False,
        "locked": True,
        "desc": "O ffmpeg junta vídeo e áudio e converte para MP3, e o conector deixa o Claude usar o Salvaí. "
        "Fazem parte do app e são recriados sozinhos, por isso não podem ser removidos.",
    },
]


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def read_clipboard() -> str:
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def find_own_window(title: str) -> int:
    found = []
    pid = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(hwnd)
                return False
        return True

    ctypes.windll.user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def center_window(hwnd: int) -> None:
    if not hwnd:
        return
    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    monitor = user32.MonitorFromPoint(pt, 2)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return
    work, rect = info.rcWork, wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    ww, wh = work.right - work.left, work.bottom - work.top
    w, h = min(rect.right - rect.left, ww), min(rect.bottom - rect.top, wh)
    x, y = work.left + (ww - w) // 2, work.top + (wh - h) // 2
    user32.SetWindowPos(wintypes.HWND(hwnd), None, x, y, w, h, 0x0004 | 0x0010)


def style_titlebar(hwnd: int, theme: str) -> None:
    if not hwnd:
        return
    dwm = ctypes.windll.dwmapi
    for attr, value in ((20, int(theme == "dark")), (35, THEMES[theme]), (36, TITLE_TEXT[theme])):
        v = ctypes.c_int(value)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))


def build_options(fmt: str, quality: str, out_dir: str, ffmpeg: str, hook=None, url: str = "") -> dict:
    name = "%(title)s.%(ext)s" if not url or is_youtube(url) else "%(title).120B [%(id)s].%(ext)s"
    opts = {
        "outtmpl": os.path.join(out_dir, name),
        "socket_timeout": 20,
        "logger": _QuietLogger(),
        "ffmpeg_location": ffmpeg,
        "progress_hooks": [hook] if hook else [],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        "overwrites": False,
        "continuedl": True,
        "concurrent_fragment_downloads": 4,
        "http_chunk_size": 10 * 1024 * 1024,
        "js_runtimes": js_runtimes(),
        "cachedir": str(CACHE_DIR / "yt-dlp"),
    }
    if fmt == "MP4":
        height = None if quality == "Máxima" else int(quality.split("p")[0])
        opts.update(
            format="bv*+ba/b",
            format_sort=[f"res:{height}" if height else "res", "ext:mp4:m4a", "vcodec:h264"],
            merge_output_format="mp4",
            postprocessors=[{"key": "FFmpegMetadata", "add_metadata": True}],
        )
    else:
        bitrate = "0" if quality == "Máxima" else quality.split()[0]
        opts.update(
            format="ba/b",
            writethumbnail=True,
            postprocessors=[
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail"},
            ],
        )
    return opts


def clean_error(e: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    msg = re.sub(r"^\[[\w:]+\] [\w-]+: ", "", msg)
    msg = re.split(r"\s*(?:Use --|See\s+https?://|please report|Confirm you are on)", msg, maxsplit=1)[0].strip()
    return msg[:160]


class Api:
    def __init__(self):
        self._cfg = load_config()
        self._theme = self._cfg.get("theme", "dark")
        self._out_dir = self._cfg.get("out_dir") or str(Path.home() / "Downloads")
        splash_step(84, "Preparando o ffmpeg…")
        self._ffmpeg = ffmpeg_dir()
        self._ready = False
        self._login_windows: dict[str, object] = {}
        self._phone = PhoneServer(self)
        self._room: RoomBase | None = None
        self._peek_cache: dict[str, tuple[float, dict]] = {}
        self._files_cache: tuple[float, list] | None = None
        self._saved = load_saved()
        self._saved_lock = threading.Lock()
        self._tray = Tray(self)
        self._hidden = False
        self._quitting = False
        self._items: dict[str, dict] = {}
        self._order: list[str] = []
        self._cv = threading.Condition()
        self._current = None
        self._window = None
        self._hwnd = 0
        self._meta_pool = ThreadPoolExecutor(max_workers=3)
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._prepare_runtime, daemon=True).start()

    def ready(self):
        with self._cv:
            if self._ready:
                return
            self._ready = True
        splash_step(100, "Pronto!")
        time.sleep(0.3)
        splash_close()
        center_window(find_own_window(APP_NAME))
        self._window.show()
        try:
            self._tray.start()
        except Exception:
            pass
        threading.Thread(target=self._check_updates, daemon=True).start()
        threading.Thread(target=self._setup_mcp, daemon=True).start()

    def _setup_mcp(self):
        if not getattr(sys, "frozen", False):
            return
        if self._cfg.get("app_path") != sys.executable:
            self._cfg["app_path"] = sys.executable
            save_config(self._cfg)
        try:
            ensure_mcp()
        except Exception:
            return
        done = self._cfg.get("claude_registered", [])
        added = register_claude(done)
        if not added:
            return
        self._cfg["claude_registered"] = done + added
        save_config(self._cfg)
        try:
            self._window.run_js('window.app && app.updateAvailable({"kind": "claude"})')
        except Exception:
            pass

    def _watch_login(self, site: str, win, state: dict):
        cfg, connected = LOGIN_SITES[site], False
        self._notify_accounts()
        while state["open"]:
            time.sleep(1.5)
            if not state["open"]:
                break
            try:
                cookies = cookies_from_webview(win.get_cookies())
            except Exception:
                continue
            if any(c["name"] == cfg["auth"] and c["value"] for c in cookies):
                sessions = load_sessions()
                sessions[site] = {"cookies": cookies, "since": int(time.time()), "source": "app"}
                save_sessions(sessions)
                connected = True
                self._login_windows.pop(site, None)
                self._notify_accounts(site)
                time.sleep(1.0)
                try:
                    win.destroy()
                except Exception:
                    pass
                break
        self._login_windows.pop(site, None)
        if not connected:
            self._notify_accounts()

    def _notify_accounts(self, just_connected: str | None = None):
        try:
            payload = json.dumps({"accounts": self.accounts(), "connected": just_connected})
            self._window.run_js(f"window.app && app.accountsChanged && app.accountsChanged({payload})")
        except Exception:
            pass

    def _active_count(self) -> int:
        return sum(1 for it in self._items.values() if it["status"] in ACTIVE_STATUSES)

    def _downloads_label(self) -> str:
        n = self._active_count()
        if not n:
            return "Nenhum download em andamento"
        return "1 download em andamento" if n == 1 else f"{n} downloads em andamento"

    def _on_closing(self):
        if self._quitting:
            return True
        busy = self._active_count()
        if self._tray.icon is None or (not busy and not self._phone.running and not self._room_active()):
            return True
        threading.Thread(target=self._hide_to_tray, args=(busy,), daemon=True).start()
        return False

    def _hide_to_tray(self, busy: int):
        self._window.hide()
        self._hidden = True
        reasons = []
        if busy:
            reasons.append(
                "ainda há 1 download em andamento" if busy == 1 else f"ainda há {busy} downloads em andamento"
            )
        if self._phone.running:
            reasons.append("o modo celular está ligado")
        if self._room_active():
            reasons.append("a sala de troca está aberta")
        self._tray.refresh()
        self._tray.notify(
            "O Salvaí continua aberto aqui",
            f"Ele foi para a bandeja porque {' e '.join(reasons)}. "
            "Clique no ícone para voltar ou use o botão direito para sair.",
        )

    def _show_from_tray(self):
        self._hidden = False
        self._window.show()
        self._window.restore()
        hwnd = find_own_window(APP_NAME)
        if hwnd:
            ctypes.windll.user32.SetForegroundWindow(hwnd)

    def _toggle_phone_from_tray(self):
        if self._phone.running:
            self._phone.stop()
        else:
            self._phone.start()
        try:
            self._window.run_js("window.app && app.phoneChanged && app.phoneChanged()")
        except Exception:
            pass
        self._tray.refresh()

    def _phone_received(self, job: dict | None):
        if job:
            device = job["device"]
            if job["count"] > 1:
                self._tray.notify("Arquivos recebidos do celular", f"{job['count']} arquivos chegaram de {device}.")
            else:
                self._tray.notify("Arquivo recebido do celular", f"{job['dest'].name} chegou de {device}.")
        try:
            self._window.run_js("window.app && app.phoneChanged && app.phoneChanged()")
        except Exception:
            pass

    def _phone_auto_off(self):
        self._tray.refresh()
        self._tray.notify(
            "Modo celular desligado",
            "Desliguei o modo celular depois de 30 minutos sem uso, por segurança. Ligue de novo quando precisar.",
        )
        try:
            self._window.run_js("window.app && app.phoneChanged && app.phoneChanged()")
        except Exception:
            pass

    def _quit(self):
        self._quitting = True
        self._phone.stop()
        self.room_close()
        self._tray.stop()
        self._window.destroy()

    def _on_main_closed(self):
        self._tray.stop()
        self._phone.stop()
        if self._room:
            self._room.close()
        for win in list(self._login_windows.values()):
            try:
                win.destroy()
            except Exception:
                pass

    def _on_gui_started(self):
        splash_step(94, "Carregando a interface…")
        threading.Timer(15, self.ready).start()

    def init(self):
        return {
            "theme": self._theme,
            "version": APP_VERSION,
            "engine_version": engine().version.__version__,
            "out_dir": self._out_dir,
            "items": [self._public(i) for i in self._ordered()],
        }

    def add(self, text: str, fmt: str, quality: str) -> int:
        return len(self._enqueue(text, fmt, quality))

    def _enqueue(self, text: str, fmt: str, quality: str, folder: str = "", source: str = "app") -> list[dict]:
        urls = list(dict.fromkeys(u.rstrip(".,;)") for u in URL_RE.findall(text or "")))
        target = safe_subfolder(Path(self._out_dir), folder)
        out_dir = str(target)
        rel_folder = "" if target == Path(self._out_dir) else str(target.relative_to(self._out_dir)).replace("\\", "/")
        new = []
        with self._cv:
            for url in urls:
                vid = youtube_id(url)
                item = {
                    "id": uuid.uuid4().hex[:10],
                    "url": url,
                    "fmt": fmt,
                    "quality": quality,
                    "out_dir": out_dir,
                    "folder": rel_folder,
                    "source": source,
                    "status": "queued",
                    "progress": 0.0,
                    "title": None,
                    "duration": None,
                    "speed": None,
                    "eta": None,
                    "error": None,
                    "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None,
                    "site": site_label(None, url),
                    "error_kind": None,
                    "filepath": None,
                    "_info": None,
                    "_info_at": 0,
                    "_cancel": False,
                    "_fetch_lock": threading.Lock(),
                }
                self._items[item["id"]] = item
                self._order.append(item["id"])
                new.append(item)
            self._cv.notify_all()
        for item in new:
            self._push(item)
            self._meta_pool.submit(self._fetch_meta, item)
        return new

    def _status(self) -> dict:
        counts = {}
        for it in self._items.values():
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "download_folder": self._out_dir,
            "connected_accounts": [LOGIN_SITES[k]["name"] for k in load_sessions()],
            "queue": counts,
        }

    def _report(self, it: dict) -> dict:
        path = it.get("filepath")
        if path and it.get("_rel_for") != path:
            try:
                it["_rel"] = str(Path(path).resolve().relative_to(Path(self._out_dir).resolve()))
            except ValueError:
                it["_rel"] = path
            it["_rel_for"] = path
        rel = it.get("_rel") if path else None
        return {
            "id": it["id"],
            "url": it["url"],
            "title": it["title"],
            "source": it.get("source"),
            "site": it.get("site"),
            "format": it["fmt"],
            "quality": it["quality"],
            "folder": it.get("folder") or "",
            "status": it["status"],
            "progress": round(it["progress"] * 100),
            "file": rel,
            "file_id": file_key(path) if path else None,
            "error": it.get("error"),
            "needs_login": it.get("login_site"),
        }

    def _phone_files(self) -> list[dict]:
        if self._files_cache and time.time() - self._files_cache[0] < 5:
            return self._files_cache[1]
        files = self._scan_media()
        self._files_cache = (time.time(), files)
        return files

    def _remember(self, path: str, replaces: str | None = None):
        path = str(Path(path).resolve())
        with self._saved_lock:
            if replaces is not None and replaces not in self._saved:
                return
            rest = [p for p in self._saved if p not in (path, replaces)]
            self._store_saved([path, *rest][:SAVED_LIMIT])

    def _store_saved(self, saved: list[str]):
        self._saved = saved
        SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SAVED_PATH.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        self._files_cache = None

    def _forget(self, key: str) -> bool:
        with self._saved_lock:
            keep = [p for p in self._saved if file_key(p) != key]
            if len(keep) == len(self._saved):
                return False
            self._store_saved(keep)
        return True

    def _clear_saved(self):
        with self._saved_lock:
            self._store_saved([])

    def _trash(self, key: str) -> str:
        target = self._saved_file(key)
        if not target:
            raise ValueError("Arquivo não encontrado.")
        send_to_trash(target)
        self._forget(key)
        return target.name

    def _saved_file(self, key: str) -> Path | None:
        for raw in list(self._saved):
            p = Path(raw)
            if file_key(p) == key and p.suffix.lower() in MEDIA_EXTENSIONS and p.is_file():
                return p
        return None

    def _scan_media(self) -> list[dict]:
        base = Path(self._out_dir).resolve()
        found = []
        for raw in list(self._saved):
            p = Path(raw)
            if p.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            try:
                folder = p.parent.relative_to(base).as_posix()
            except ValueError:
                folder = p.parent.name
            found.append(
                {
                    "id": file_key(p),
                    "name": p.name,
                    "folder": "" if folder == "." else folder,
                    "size_mb": round(size / 1048576, 1),
                    "kind": "audio"
                    if p.suffix.lower() in {".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac"}
                    else "video",
                }
            )
            if len(found) == 80:
                break
        return found

    def phone_start(self) -> dict:
        self._phone.start()
        self._tray.refresh()
        return self._phone.status()

    def phone_revoke(self, device_id: str) -> dict:
        self._phone.revoke(device_id)
        return self._phone.status()

    def phone_revoke_all(self) -> dict:
        self._phone.revoke_all()
        return self._phone.status()

    def phone_clear_history(self) -> dict:
        self._cfg["phone_history"] = []
        save_config(self._cfg)
        return self._phone.status()

    def phone_stop(self) -> dict:
        self._phone.stop()
        self._tray.refresh()
        return self._phone.status()

    def phone_status(self) -> dict:
        return self._phone.status()

    def phone_open_received(self, entry_id: str) -> bool:
        target = self._phone.received_file(entry_id)
        if not target:
            return False
        subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
        return True

    def phone_open_inbox(self):
        inbox = self._phone.inbox()
        inbox.mkdir(parents=True, exist_ok=True)
        os.startfile(inbox)

    def phone_allow_firewall(self) -> bool:
        port = self._phone.server.server_address[1] if self._phone.server else PHONE_PORT
        program = Path(sys.executable).resolve()
        args = (
            f'advfirewall firewall add rule name="Salvaí (celular)" dir=in action=allow protocol=TCP '
            f'localport={int(port)} profile=private,public program="{program}"'
        )
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", args, None, 0)
        return result > 32

    def share_whatsapp(self) -> dict:
        status = self._phone.status()
        if not status.get("on"):
            return {"ok": False}
        return self._open_whatsapp(whatsapp_message(status["url"], self._phone.network or {}))

    def _open_whatsapp(self, message: str) -> dict:
        text = urllib.parse.quote(message)
        desktop = whatsapp_installed()
        os.startfile(f"whatsapp://send?text={text}" if desktop else f"https://web.whatsapp.com/send?text={text}")
        return {"ok": True, "app": "desktop" if desktop else "web"}

    def _room_changed(self):
        try:
            self._window.run_js("window.app && app.roomChanged && app.roomChanged()")
        except Exception:
            pass

    def _room_event(self, kind: str, text: str):
        if kind == "join":
            self._tray.notify(
                "Alguém quer entrar na sala",
                f"{text} pediu para entrar na sua sala de troca. Abra o Salvaí para aprovar.",
            )
        else:
            self._tray.notify("Sala de troca fechada", text)
        self._tray.refresh()
        self._room_changed()

    def _room_active(self) -> bool:
        return bool(self._room and self._room.active)

    def _remember_room_name(self, name: str):
        label = clean_label(name)
        if label and label != self._cfg.get("room_name"):
            self._cfg["room_name"] = label
            save_config(self._cfg)

    def room_status(self) -> dict:
        if self._room:
            return self._room.status()
        return {"role": None, "phase": "idle", "name": self._cfg.get("room_name") or os.getenv("USERNAME") or ""}

    def room_create(self, name: str) -> dict:
        self._remember_room_name(name)
        if self._room:
            self._room.close()
        self._room = Room(self)
        self._room.start(name)
        self._tray.refresh()
        return self.room_status()

    def room_join(self, link: str, code: str, name: str) -> dict:
        self._remember_room_name(name)
        client = RoomClient(self)
        try:
            client.join(link, code, name)
        except ValueError as e:
            return dict(self.room_status(), notice=str(e))
        if self._room:
            self._room.close()
        self._room = client
        return self.room_status()

    def room_close(self) -> dict:
        if self._room:
            self._room.close()
            self._room = None
        self._tray.refresh()
        return self.room_status()

    def _room_call(self, action) -> dict:
        if not self._room or self._room.phase != "open":
            return self.room_status()
        try:
            action(self._room)
        except Exception as e:
            return dict(self.room_status(), notice=clean_error(e))
        return self.room_status()

    def room_add(self, kind: str) -> dict:
        if not self._room or self._room.phase != "open":
            return self.room_status()
        folder = kind == "folder"
        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
            directory=self._out_dir,
            allow_multiple=not folder,
        )
        if not result:
            return self.room_status()
        paths = [result] if isinstance(result, str) else list(result)
        return self._room_call(lambda room: room.add_paths(paths))

    def _on_loaded(self):
        modal = self._window.dom.get_element("#room-modal")
        if modal:
            modal.events.drop += DOMEventHandler(self._on_room_drop, prevent_default=True)

    def _on_room_drop(self, event: dict):
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if not paths:
            return
        status = self._room_call(lambda room: room.add_paths(paths))
        try:
            self._window.run_js(f"window.app && app.roomDropped && app.roomDropped({json.dumps(status)})")
        except Exception:
            pass

    def room_remove(self, item_id: str) -> dict:
        return self._room_call(lambda room: room.remove_item(item_id))

    def room_download(self, ids) -> dict:
        if not self._room or self._room.phase != "open":
            return self.room_status()
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=self._out_dir)
        if not result:
            return self.room_status()
        dest = Path(result[0] if isinstance(result, (list, tuple)) else result)
        return self._room_call(lambda room: room.download(ids, dest))

    def room_approve(self, person_id: str) -> dict:
        return self._room_call(lambda room: room.approve(person_id))

    def room_kick(self, person_id: str) -> dict:
        return self._room_call(lambda room: room.kick(person_id))

    def room_reveal(self, item_id: str):
        root = self._room.item_root(item_id) if self._room else None
        if not root or not root.exists():
            return
        if root.is_dir():
            os.startfile(root)
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(root)])

    def room_share_whatsapp(self) -> dict:
        status = self.room_status()
        if status["role"] != "host" or status["phase"] != "open":
            return {"ok": False}
        return self._open_whatsapp(room_whatsapp_message(status["url"], status["code"], status["name"]))

    def open_network_settings(self):
        kind = (self._phone.network or {}).get("kind")
        os.startfile("ms-settings:network-wifi" if kind == "wifi" else "ms-settings:network-ethernet")

    def _search(self, query: str, limit: int = 5, site: str = "youtube") -> dict:
        prefix = {"youtube": "ytsearch", "soundcloud": "scsearch"}.get(site, "ytsearch")
        limit = max(1, min(limit, 15))
        opts = {
            "quiet": True,
            "logger": _QuietLogger(),
            "extract_flat": "in_playlist",
            "skip_download": True,
            "js_runtimes": js_runtimes(),
            "cachedir": str(CACHE_DIR / "yt-dlp"),
            "socket_timeout": 20,
        }
        with make_ydl(opts) as ydl:
            info = ydl.extract_info(f"{prefix}{limit}:{query}", download=False)
        results = []
        for e in info.get("entries") or []:
            url = e.get("webpage_url") or e.get("url")
            if e.get("ie_key") == "Youtube" and e.get("id"):
                url = f"https://www.youtube.com/watch?v={e['id']}"
            results.append(
                {
                    "title": e.get("title"),
                    "url": url,
                    "channel": e.get("channel") or e.get("uploader"),
                    "duration_seconds": e.get("duration"),
                    "views": e.get("view_count"),
                }
            )
        return {"query": query, "site": site, "results": results}

    def _files(self, folder: str = "", depth: int = 3) -> dict:
        base = Path(self._out_dir)
        root = safe_subfolder(base, folder)
        entries, depth = [], max(0, min(depth, 6))
        if root.exists():
            for dirpath, dirs, files in os.walk(root):
                level = len(Path(dirpath).relative_to(root).parts)
                if level >= depth:
                    dirs[:] = []
                for name in sorted(files):
                    if len(entries) >= 400:
                        break
                    p = Path(dirpath) / name
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    entries.append(
                        {
                            "path": str(p.relative_to(base)),
                            "size_mb": round(st.st_size / 1048576, 1),
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                            "incomplete": name.endswith((".part", ".ytdl")),
                        }
                    )
        return {
            "download_folder": str(base),
            "folder": str(root.relative_to(base)) if root != base else "",
            "files": entries,
            "truncated": len(entries) >= 400,
        }

    def _move(self, path: str, folder: str) -> dict:
        base = Path(self._out_dir)
        src = (base / path).resolve()
        if base.resolve() not in src.parents or not src.is_file():
            raise ValueError("arquivo não encontrado dentro da pasta de downloads")
        dest_dir = safe_subfolder(base, folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest, n = dest_dir / src.name, 2
        while dest.exists():
            dest = dest_dir / f"{src.stem} ({n}){src.suffix}"
            n += 1
        shutil.move(str(src), str(dest))
        self._remember(str(dest), replaces=str(src))
        for it in self._items.values():
            if it.get("filepath") and Path(it["filepath"]).resolve() == src:
                it["filepath"] = str(dest)
        return {"moved_to": str(dest.relative_to(base))}

    def add_items(self, items: list) -> int:
        return sum(self.add(it["url"], it["fmt"], it["quality"]) for it in items)

    def reorder(self, ids: list):
        with self._cv:
            self._order = [i for i in ids if i in self._items] + [i for i in self._order if i not in ids]
            self._preempt()
            self._cv.notify_all()

    def remove(self, item_id: str):
        with self._cv:
            item = self._items.pop(item_id, None)
            if item_id in self._order:
                self._order.remove(item_id)
            if item and item is self._current:
                item["_cancel"] = True
            self._cv.notify_all()

    def retry(self, item_id: str):
        with self._cv:
            item = self._items.get(item_id)
            if item and item["status"] == "error":
                item.update(status="queued", error=None, progress=0.0, _info=None)
                self._cv.notify_all()
        if item:
            self._push(item)

    def clear_done(self) -> list:
        with self._cv:
            done = [i for i, it in self._items.items() if it["status"] in ("done", "error")]
            for i in done:
                self._items.pop(i)
                self._order.remove(i)
        return done

    def open_item(self, item_id: str):
        item = self._items.get(item_id)
        if not item:
            return
        path = item["filepath"]
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(item["out_dir"])

    def choose_folder(self):
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=self._out_dir)
        if not result:
            return None
        self._out_dir = os.path.normpath(result[0] if isinstance(result, (list, tuple)) else result)
        self._cfg["out_dir"] = self._out_dir
        save_config(self._cfg)
        return self._out_dir

    def peek(self, url: str):
        cached = self._peek_cache.get(url)
        if cached and time.time() - cached[0] < PEEK_TTL:
            return dict(cached[1])
        result = self._peek(url)
        if not result.get("error"):
            self._peek_cache[url] = (time.time(), result)
        return result

    def _peek(self, url: str):
        vid = youtube_id(url)
        if vid:
            try:
                q = urllib.parse.urlencode({"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
                with urllib.request.urlopen(f"https://www.youtube.com/oembed?{q}", timeout=8) as r:
                    data = json.load(r)
                return {
                    "title": data.get("title"),
                    "author": data.get("author_name"),
                    "thumb": data.get("thumbnail_url"),
                    "site": "YouTube",
                }
            except Exception:
                pass
        try:
            opts = build_options("MP4", "Máxima", self._out_dir, self._ffmpeg, url=url)
            with make_ydl(opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
            thumbs = info.get("thumbnails") or []
            thumb = info.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
            if vid:
                thumb = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
            author = info.get("uploader") or info.get("channel") or info.get("uploader_id")
            return {"title": info.get("title"), "author": author, "thumb": thumb, "site": site_label(info, url)}
        except Exception as e:
            kind, msg = friendly_error(e, url)
            return {
                "error": msg,
                "error_kind": kind,
                "site": site_label(None, url),
                "login_site": login_site_for(url) if kind in ("login", "noaccess") else None,
            }

    def check_url(self, url: str) -> bool:
        try:
            return supported_site(url)
        except Exception:
            return False

    def accounts(self) -> dict:
        sessions = load_sessions()
        sites = [
            {
                "key": k,
                "name": s["name"],
                "connected": k in sessions,
                "since": sessions.get(k, {}).get("since"),
                "source": sessions.get(k, {}).get("source"),
                "busy": k in self._login_windows,
            }
            for k, s in LOGIN_SITES.items()
        ]
        browsers = [{"key": k, "name": n} for k, (n, p) in BROWSERS.items() if p.exists()]
        return {"sites": sites, "browsers": browsers}

    def login(self, site: str):
        cfg = LOGIN_SITES[site]
        if site in self._login_windows:
            return
        win = webview.create_window(
            f"Entrar no {cfg['name']}",
            cfg["login"],
            width=480,
            height=780,
            background_color="#0E0E11" if self._theme == "dark" else "#F4F4F6",
        )
        state = {"open": True}
        win.events.closed += lambda: state.update(open=False)
        self._login_windows[site] = win
        threading.Thread(target=self._watch_login, args=(site, win, state), daemon=True).start()

    def logout(self, site: str):
        sessions = load_sessions()
        sessions.pop(site, None)
        save_sessions(sessions)
        try:
            self._window.clear_cookies()
        except Exception:
            pass
        return self.accounts()

    def import_browser(self, browser: str) -> dict:
        name = BROWSERS[browser][0]
        try:
            jar = engine().cookies.extract_cookies_from_browser(browser, logger=_QuietLogger())
        except Exception as e:
            low = str(e).lower()
            if "could not copy" in low or "being used" in low or "permission" in low:
                msg = (
                    f"O {name} está aberto e trava os próprios arquivos. Feche ele por completo "
                    "(inclusive o ícone perto do relógio) e tente de novo — ou use o botão Entrar."
                )
            elif "decrypt" in low or "dpapi" in low or "app-bound" in low or "key" in low:
                msg = (
                    f"O {name} protege os logins com uma criptografia que outros programas não conseguem ler. "
                    "Use o botão Entrar, que funciona sempre."
                )
            else:
                msg = f"Não consegui ler o {name}: {clean_error(e)}"
            return {"ok": False, "message": msg, "accounts": self.accounts()}
        sessions, found = load_sessions(), []
        for key, cfg in LOGIN_SITES.items():
            cookies = [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                    "secure": bool(c.secure),
                    "expires": c.expires,
                }
                for c in jar
                if any(c.domain.lstrip(".").endswith(d) for d in cfg["domains"])
            ]
            if any(c["name"] == cfg["auth"] and c["value"] for c in cookies):
                sessions[key] = {"cookies": cookies, "since": int(time.time()), "source": name}
                found.append(cfg["name"])
        save_sessions(sessions)
        if found:
            return {
                "ok": True,
                "message": f"Contas importadas do {name}: {', '.join(found)}.",
                "accounts": self.accounts(),
            }
        return {
            "ok": False,
            "message": f"Não achei nenhuma conta logada no {name} (Instagram, TikTok, X ou Facebook).",
            "accounts": self.accounts(),
        }

    def storage_info(self) -> dict:
        ffmpeg = file_size(BIN_DIR / "ffmpeg.exe") + file_size(BIN_DIR / "ffmpeg.version")
        essential = ffmpeg + dir_size(MCP_DIR)
        sizes = {
            "webview": dir_size(WEBVIEW_DIR),
            "ytdlp": dir_size(CACHE_DIR),
            "temp": sum(dir_size(d) for d in leftover_temp_dirs()),
            "components": dir_size(BIN_DIR) - ffmpeg + dir_size(ENGINE_DIR),
            "essential": essential,
        }
        cats = [dict(c, size=sizes[c["key"]]) for c in STORAGE]
        return {
            "version": APP_VERSION,
            "categories": cats,
            "total": sum(sizes.values()),
            "pending_webview": WEBVIEW_CLEAR_FLAG.exists(),
        }

    def clear_storage(self, keys: list) -> dict:
        freed, notes = 0, []
        if "ytdlp" in keys:
            freed += remove_tree(CACHE_DIR)
        if "temp" in keys:
            freed += cleanup_leftovers()
            if leftover_temp_dirs():
                notes.append("Algumas sobras estão em uso por outra janela do app e serão apagadas depois.")
        if "components" in keys:
            with self._cv:
                busy = self._current is not None
            if busy:
                notes.append("Os componentes não foram apagados porque há um download em andamento.")
            else:
                with _runtime_lock:
                    deno = BIN_DIR / "deno.exe"
                    freed += file_size(deno)
                    deno.unlink(missing_ok=True)
                    freed += remove_tree(ENGINE_DIR)
        if "webview" in keys:
            before = dir_size(WEBVIEW_DIR)
            for sub in ("Cache", "Code Cache", "GPUCache"):
                for p in WEBVIEW_DIR.rglob(sub):
                    if p.is_dir():
                        freed += remove_tree(p)
            if dir_size(WEBVIEW_DIR) > 0 and before:
                WEBVIEW_CLEAR_FLAG.touch()
                notes.append("O restante do cache da interface será apagado na próxima vez que o app abrir.")
        return {"freed": freed, "notes": notes, "info": self.storage_info()}

    def update_engine(self) -> dict:
        try:
            sums = http_get(ENGINE_RELEASES + "SHA2-256SUMS").decode()
            expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1:] == ["yt-dlp"])
            data = http_get(ENGINE_RELEASES + "yt-dlp", timeout=180)
            if hashlib.sha256(data).hexdigest() != expected.lower():
                return {"ok": False, "message": "O arquivo baixado não confere com o oficial. Nada foi alterado."}
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                version = re.search(r"__version__ = ['\"]([\d.]+)['\"]", z.read("yt_dlp/version.py").decode()).group(1)
            ENGINE_DIR.mkdir(parents=True, exist_ok=True)
            target = ENGINE_DIR / f"yt-dlp-{version}.zip"
            target.write_bytes(data)
            for old in ENGINE_DIR.glob("yt-dlp-*.zip"):
                if old != target:
                    try:
                        old.unlink()
                    except OSError:
                        pass
            return {"ok": True, "version": version}
        except Exception as e:
            return {"ok": False, "message": f"Não foi possível atualizar agora: {clean_error(e)}"}

    def update_app(self) -> dict:
        release = None
        try:
            if not getattr(sys, "frozen", False):
                return {"ok": False, "message": "A atualização automática funciona no app instalado (Salvai.exe)."}
            release = github_latest(APP_REPO)
            if version_key(release["tag_name"].lstrip("v")) <= version_key(APP_VERSION):
                return {"ok": False, "message": "Você já está na versão mais recente."}
            last = [0.0]

            def progress(fraction: float):
                now = time.monotonic()
                if now - last[0] > 0.15 or fraction >= 1:
                    last[0] = now
                    try:
                        self._window.run_js(f"window.app && app.otaProgress({round(fraction * 100)})")
                    except Exception:
                        pass

            version = install_release(
                release,
                Path(sys.executable).resolve(),
                CONFIG_PATH.parent / "update",
                progress,
                trusted_prefix=f"https://github.com/{APP_REPO}/releases/download/",
            )
            return {"ok": True, "version": version}
        except PermissionError:
            return {
                "ok": False,
                "message": "Sem permissão para trocar o app nesta pasta. Baixe a nova versão pela página da release.",
                "url": (release or {}).get("html_url"),
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"Não foi possível atualizar agora: {clean_error(e)}",
                "url": (release or {}).get("html_url"),
            }

    def restart_app(self):
        if getattr(sys, "frozen", False):
            args = [sys.executable]
        else:
            args = [sys.executable, str(Path(__file__).resolve())]
        subprocess.Popen(args, close_fds=True, creationflags=0x00000008, env=fresh_env())
        threading.Timer(0.3, self._window.destroy).start()

    def skip_update(self, kind: str, version: str):
        self._cfg[f"skip_{kind}"] = version
        save_config(self._cfg)

    def open_release(self, url: str):
        if url.startswith(f"https://github.com/{APP_REPO}/"):
            os.startfile(url)

    def _check_updates(self):
        time.sleep(3)
        notices, _ = self._fetch_update_notices()
        self._show_notices(notices, respect_skip=True)

    def release_notes(self) -> dict:
        page = f"https://github.com/{APP_REPO}/releases"
        try:
            releases = json.loads(http_get(f"https://api.github.com/repos/{APP_REPO}/releases?per_page=30", timeout=10))
        except Exception:
            return {"ok": False, "url": page}
        found = []
        for release in releases:
            version = release["tag_name"].lstrip("v")
            if release.get("draft") or release.get("prerelease") or version_key(version) <= version_key(APP_VERSION):
                continue
            found.append(
                {
                    "version": version,
                    "date": (release.get("published_at") or "")[:10],
                    "sections": parse_release_notes(release.get("body") or ""),
                }
            )
        found.sort(key=lambda r: version_key(r["version"]), reverse=True)
        return {"ok": True, "current": APP_VERSION, "releases": found, "url": page}

    def check_updates_now(self) -> dict:
        notices, offline = self._fetch_update_notices()
        self._show_notices(notices, respect_skip=False)
        return {"found": len(notices), "offline": offline}

    def _show_notices(self, notices: list[dict], respect_skip: bool):
        for notice in notices:
            if respect_skip and self._cfg.get(f"skip_{notice['kind']}") == notice["latest"]:
                continue
            try:
                self._window.run_js(f"window.app && app.updateAvailable({json.dumps(notice)})")
            except Exception:
                pass

    def _fetch_update_notices(self) -> tuple[list[dict], bool]:
        notices, failures = [], 0
        try:
            latest = github_latest("yt-dlp/yt-dlp")["tag_name"]
            current = engine().version.__version__
            if version_key(latest) > version_key(current):
                notices.append({"kind": "engine", "current": current, "latest": latest})
        except Exception:
            failures += 1
        try:
            release = github_latest(APP_REPO)
            latest = release["tag_name"].lstrip("v")
            if version_key(latest) > version_key(APP_VERSION):
                notices.append({"kind": "app", "current": APP_VERSION, "latest": latest, "url": release["html_url"]})
        except Exception:
            failures += 1
        return notices, failures == 2

    def paste(self) -> str:
        try:
            return read_clipboard()
        except Exception:
            return ""

    def set_theme(self, theme: str):
        self._theme = theme
        self._cfg["theme"] = theme
        save_config(self._cfg)
        threading.Timer(0.22, style_titlebar, (self._hwnd, theme)).start()

    def _on_shown(self):
        self._hwnd = find_own_window(APP_NAME)
        style_titlebar(self._hwnd, self._theme)

    def _prepare_runtime(self):
        try:
            ensure_js_runtime()
        except Exception:
            pass

    def _ordered(self):
        return [self._items[i] for i in self._order if i in self._items]

    def _public(self, item: dict) -> dict:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    def _announce(self, item: dict):
        self._tray.refresh()
        if not self._hidden:
            return
        title = item.get("title") or item["url"]
        if item["status"] == "done":
            self._tray.notify("Salvo! ✓", f"{title} · {item['fmt']}")
        elif item["status"] == "error":
            self._tray.notify("Não deu para baixar", f"{title}: {item.get('error') or ''}")

    def _push(self, item: dict):
        if self._window and item["id"] in self._items:
            try:
                self._window.run_js(f"window.app && app.update({json.dumps(self._public(item))})")
            except Exception:
                pass

    def _preempt(self):
        cur = self._current
        if not cur or cur["status"] not in ("fetching", "downloading"):
            return
        first = next((it for it in self._ordered() if it["status"] in PENDING or it is cur), None)
        if first is not cur:
            cur["_cancel"] = True

    def _next(self):
        return next((it for it in self._ordered() if it["status"] in PENDING), None)

    def _ensure_info(self, item: dict):
        with item["_fetch_lock"]:
            if item["_info"] and time.time() - item["_info_at"] < INFO_TTL:
                return item["_info"]
            opts = build_options(item["fmt"], item["quality"], item["out_dir"], self._ffmpeg, url=item["url"])
            with make_ydl(opts) as ydl:
                info = ydl.extract_info(item["url"], download=False, process=False)
            if item["status"] not in ("done", "error"):
                item["_info"], item["_info_at"] = info, time.time()
            item["title"] = info.get("title") or item["title"]
            item["duration"] = info.get("duration")
            item["site"] = site_label(info, item["url"])
            if info.get("id") and info.get("extractor_key") == "Youtube":
                item["thumb"] = f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg"
            elif not item["thumb"]:
                thumbs = info.get("thumbnails") or []
                item["thumb"] = info.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
            return info

    def _fetch_meta(self, item: dict):
        cached = self._peek_cache.get(item["url"])
        if cached and not is_youtube(item["url"]):
            info = cached[1]
            item["title"] = info.get("title") or item["title"]
            item["thumb"] = item["thumb"] or info.get("thumb")
            item["site"] = info.get("site") or item["site"]
            self._push(item)
            return
        try:
            self._ensure_info(item)
            self._push(item)
        except Exception:
            pass

    def _worker(self):
        while True:
            with self._cv:
                item = self._next()
                while item is None:
                    self._cv.wait()
                    item = self._next()
                item["_cancel"] = False
                self._current = item
            try:
                self._download(item)
            finally:
                with self._cv:
                    self._current = None

    def _download(self, item: dict):
        last = [0.0]

        def hook(d):
            if item["_cancel"]:
                raise Paused()
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                frac = d.get("downloaded_bytes", 0) / total if total else 0
                fi = d.get("info_dict") or {}
                if item["fmt"] == "MP4" and fi.get("acodec") == "none":
                    frac = 0.9 * frac
                elif item["fmt"] == "MP4" and fi.get("vcodec") == "none":
                    frac = 0.9 + 0.1 * frac
                item.update(
                    status="downloading", progress=max(0.0, min(frac, 1.0)), speed=d.get("speed"), eta=d.get("eta")
                )
                now = time.monotonic()
                if now - last[0] > 0.15:
                    last[0] = now
                    self._push(item)

        def pp_hook(d):
            if d["status"] == "started" and item["status"] != "processing":
                item.update(status="processing", progress=1.0)
                self._push(item)

        try:
            os.makedirs(item["out_dir"], exist_ok=True)
            self._ffmpeg = ffmpeg_dir()
            if not js_runtimes():
                item["status"] = "setup"
                self._push(item)
                try:
                    ensure_js_runtime()
                except Exception as e:
                    raise RuntimeError(f"sem internet para preparar o app ({clean_error(e)})") from e
            youtube = is_youtube(item["url"])
            if not item["_info"] or not youtube:
                item["status"] = "fetching"
                self._push(item)
            info = copy.deepcopy(self._ensure_info(item)) if youtube else None
            if item["_cancel"]:
                raise Paused()
            item.update(status="downloading")
            self._push(item)

            opts = build_options(item["fmt"], item["quality"], item["out_dir"], self._ffmpeg, hook, url=item["url"])
            opts["postprocessor_hooks"] = [pp_hook]
            with make_ydl(opts) as ydl:
                if youtube:
                    result = ydl.process_ie_result(info, download=True)
                else:
                    result = ydl.extract_info(item["url"], download=True)
                    item["title"] = item["title"] or result.get("title")
                    item["duration"] = item["duration"] or result.get("duration")
                req = result.get("requested_downloads") or []
                if not req and result.get("entries"):
                    entries = [e for e in result["entries"] if e]
                    req = (entries[0].get("requested_downloads") or []) if entries else []
                path = req[0].get("filepath") if req else ydl.prepare_filename(result)
            if item["fmt"] == "MP3" and path:
                path = os.path.splitext(path)[0] + ".mp3"
            item.update(
                status="done", progress=1.0, filepath=path if path and os.path.exists(path) else None, _info=None
            )
            if item["filepath"]:
                self._remember(item["filepath"])
        except Exception as e:
            if item["_cancel"]:
                item.update(status="paused", speed=None, eta=None)
            else:
                kind, msg = friendly_error(e, item["url"])
                item.update(
                    status="error",
                    _info=None,
                    error=msg,
                    error_kind=kind,
                    login_site=login_site_for(item["url"]) if kind in ("login", "noaccess") else None,
                )
        self._push(item)
        self._announce(item)


def selftest(out_dir: str):
    lines = [f"runtime {ensure_js_runtime()}", f"engine {bundled_engine_version()} override {ENGINE_OVERRIDE}"]
    for fmt in ("MP4", "MP3"):
        try:
            opts = build_options(fmt, "Máxima", out_dir, ffmpeg_dir())
            with engine().YoutubeDL(opts) as ydl:
                info = ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw")
            lines.append(f"{fmt} ok {info.get('format_id')}")
        except Exception as e:
            lines.append(f"{fmt} FAIL {clean_error(e)}")
    Path(out_dir, "selftest.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    if "--selftest" in sys.argv:
        splash_close()
        return selftest(sys.argv[sys.argv.index("--selftest") + 1])
    if stale_bundle():
        splash_close()
        subprocess.Popen([sys.executable, *sys.argv[1:]], close_fds=True, creationflags=0x00000008, env=fresh_env())
        return
    cleanup_old_versions()
    threading.Thread(target=cleanup_leftovers, daemon=True).start()
    if WEBVIEW_CLEAR_FLAG.exists():
        remove_tree(WEBVIEW_DIR)
        WEBVIEW_CLEAR_FLAG.unlink(missing_ok=True)
    api = Api()
    splash_step(92, "Abrindo a janela…")
    window = webview.create_window(
        APP_NAME,
        url=str(BASE / "ui" / "index.html"),
        js_api=api,
        width=1040,
        height=860,
        min_size=(760, 620),
        hidden=True,
        background_color="#0E0E11" if api._theme == "dark" else "#F4F4F6",
    )
    api._window = window
    window.events.shown += api._on_shown
    window.events.loaded += api._on_loaded
    window.events.closed += api._on_main_closed
    window.events.closing += api._on_closing
    bridge = Bridge(api)
    try:
        bridge.start()
        window.events.closed += bridge.stop
    except Exception:
        pass
    webview.start(api._on_gui_started, debug="--debug" in sys.argv, private_mode=False, storage_path=str(WEBVIEW_DIR))
    api._tray.stop()
    api._phone.stop()
    bridge.stop()
    os._exit(0)


if __name__ == "__main__":
    main()
