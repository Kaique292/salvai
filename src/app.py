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
import urllib.parse
import urllib.request
import uuid
import zipfile
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
import yt_dlp

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


def js_runtimes() -> dict:
    found = {} if os.getenv("YTD_FORCE_DENO") else {n: {} for n in ("deno", "node", "bun") if shutil.which(n)}
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
            urllib.request.urlretrieve(DENO_URL, tmp_zip)
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
    for ie in yt_dlp.extractor.gen_extractor_classes():
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
    ydl = yt_dlp.YoutubeDL(opts)
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
    key = re.sub(r"(p|kbps|k)$", "", str(quality or "max").strip().lower().replace(" ", ""))
    key = "max" if key in ("", "max", "máxima", "maxima", "best", "melhor") else key
    table = AUDIO_QUALITY if fmt == "MP3" else VIDEO_QUALITY
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
                auth = self.headers.get("Authorization", "")
                if not secrets.compare_digest(auth, f"Bearer {bridge.token}"):
                    return self._reply(401, {"error": "token inválido"})
                url = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                body = {}
                if method == "POST":
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}")
                try:
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

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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
            for it in body["items"]:
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
                if not items:
                    created.append({"url": it["url"], "error": "isso não parece um link"})
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


def github_latest(repo: str) -> dict:
    return json.loads(http_get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10))


PHONE_PORT = 47800
MEDIA_EXTENSIONS = {".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".mov", ".opus", ".ogg", ".wav", ".flac", ".jpg", ".png"}
CREATE_NO_WINDOW = 0x08000000


def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]


NETWORK_SCRIPT = (
    "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -or $_.IPv6DefaultGateway } | ForEach-Object { "
    "[pscustomobject]@{ alias = $_.InterfaceAlias; media = $_.NetAdapter.PhysicalMediaType; "
    "network = $_.NetProfile.Name; category = [string]$_.NetProfile.NetworkCategory; "
    "ipv4 = @($_.IPv4Address | ForEach-Object { $_.IPAddress }); "
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
    candidates = [i for i in interfaces if any(is_private_v4(a) for a in i.get("ipv4") or [])]
    chosen = next((i for i in candidates if primary in (i.get("ipv4") or [])), candidates[0] if candidates else None)
    if not chosen:
        chosen = next(iter(interfaces), None)
    if not chosen:
        return {"kind": None, "name": None, "public": False, "ipv4": [primary], "ipv6": [], "v6_networks": []}
    media = (chosen.get("media") or "").lower()
    ipv6 = [a for a in chosen.get("ipv6") or [] if not a.lower().startswith("fe80")]
    return {
        "kind": "wifi" if "802.11" in media or "wireless" in media else "cabo",
        "name": chosen.get("network"),
        "public": (chosen.get("category") or "").lower() == "public",
        "ipv4": [a for a in chosen.get("ipv4") or [] if is_private_v4(a)],
        "ipv6": ipv6,
        "v6_networks": [str(ipaddress.ip_network(f"{a}/64", strict=False)) for a in ipv6],
    }


def device_name(user_agent: str) -> str:
    ua = user_agent or ""
    for marker, name in (
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


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


class PhoneServer:
    def __init__(self, api: "Api"):
        self.api, self.server, self.token, self.devices = api, None, "", {}
        self.network, self.network_at, self.network_lock = None, 0.0, threading.Lock()

    def refresh_network(self):
        with self.network_lock:
            if self.network and time.time() - self.network_at < 60:
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
        self.token = secrets.token_urlsafe(12)
        self.devices = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, code: int, payload, cookie: str | None = None):
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _allowed(self, query: dict) -> bool:
                if not phone.client_allowed(self.client_address[0]):
                    return False
                cookie = re.search(r"salvai=([\w-]+)", self.headers.get("Cookie") or "")
                given = query.get("k") or (cookie.group(1) if cookie else "")
                return secrets.compare_digest(given, phone.token)

            def _handle(self, method: str):
                url = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                if not self._allowed(query):
                    return self._json(403, {"error": "Abra pelo QR code que aparece no Salvaí do computador."})
                phone.devices[self.client_address[0]] = {
                    "name": device_name(self.headers.get("User-Agent")),
                    "seen": time.time(),
                }
                try:
                    phone.route(self, method, url.path, query)
                except (ConnectionError, BrokenPipeError):
                    pass
                except (KeyError, ValueError) as e:
                    self._json(400, {"error": str(e)})
                except Exception as e:
                    self._json(500, {"error": clean_error(e)})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_HEAD(self):
                self._handle("HEAD")

        self.server = None
        for server_class, host in ((DualStackServer, "::"), (ThreadingHTTPServer, "0.0.0.0")):
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

    def stop(self):
        if self.server:
            server, self.server = self.server, None
            threading.Thread(target=server.shutdown, daemon=True).start()
            server.server_close()

    def route(self, h, method: str, path: str, query: dict):
        api = self.api
        if method == "GET" and path == "/":
            page = (BASE / "ui" / "mobile" / "index.html").read_bytes()
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(page)))
            h.send_header("Cache-Control", "no-store")
            if query.get("k"):
                h.send_header("Set-Cookie", f"salvai={self.token}; Path=/; SameSite=Strict; HttpOnly")
            h.end_headers()
            h.wfile.write(page)
            return
        if method in ("GET", "HEAD") and path in ("/mobile.css", "/mobile.js"):
            return send_file(h, BASE / "ui" / "mobile" / path.lstrip("/"), as_attachment=False, head=method == "HEAD")
        if method == "GET" and path == "/api/state":
            downloads = [dict(api._report(i), thumb=i.get("thumb")) for i in api._ordered()]
            return h._json(200, {"version": APP_VERSION, "computer": socket.gethostname(), "downloads": downloads})
        if method == "POST" and path == "/api/add":
            length = int(h.headers.get("Content-Length") or 0)
            body = json.loads(h.rfile.read(length) or b"{}")
            fmt, quality = normalize_request(body.get("format", "mp4"), body.get("quality", "max"))
            items = api._enqueue(body["url"], fmt, quality, source="phone")
            if not items:
                raise ValueError("Isso não parece um link.")
            return h._json(200, {"queued": len(items)})
        if method == "GET" and path == "/api/files":
            return h._json(200, {"files": api._phone_files()})
        if method in ("GET", "HEAD") and path == "/api/file":
            base = Path(api._out_dir).resolve()
            target = (base / query["path"]).resolve()
            if base not in target.parents or not target.is_file():
                raise ValueError("Arquivo não encontrado.")
            return send_file(h, target, as_attachment=query.get("dl") == "1", head=method == "HEAD")
        h._json(404, {"error": "não encontrado"})

    def status(self) -> dict:
        if not self.server:
            return {"on": False}
        if not self.network or time.time() - self.network_at > 60:
            threading.Thread(target=self.refresh_network, daemon=True).start()
        urls = self.addresses()
        now = time.time()
        devices = sorted({d["name"] for d in self.devices.values() if now - d["seen"] < 20})
        qr = segno.make(urls[0], error="m").svg_inline(scale=5, border=2, dark="#111114", light="#ffffff")
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
        }


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
            if dest.exists():
                dest.replace(old)
            shutil.move(str(new_file), str(dest))
            done.append((dest, old))
    except Exception:
        for dest, old in reversed(done):
            try:
                if dest.exists():
                    dest.unlink()
                old.replace(dest)
            except OSError:
                pass
        raise


def install_release(release: dict, current_exe: Path, staging: Path, progress=None) -> str:
    version = release["tag_name"].lstrip("v")
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets") or []}
    if "Salvai.exe" not in assets or "SHA256SUMS.txt" not in assets:
        raise RuntimeError("essa versão ainda não tem os arquivos publicados")
    sums = parse_sums(download(assets["SHA256SUMS.txt"]).decode())
    targets = [("Salvai.exe", current_exe)]
    mcp = current_exe.with_name("salvai-mcp.exe")
    if mcp.exists() and "salvai-mcp.exe" in assets:
        targets.append(("salvai-mcp.exe", mcp))
    staging.mkdir(parents=True, exist_ok=True)
    staged = []
    for index, (name, dest) in enumerate(targets):
        data = download(assets[name], lambda f, i=index: progress and progress((i + f) / len(targets)))
        if hashlib.sha256(data).hexdigest() != sums.get(name):
            raise RuntimeError(f"o arquivo {name} baixado não confere com o oficial")
        file = staging / name
        file.write_bytes(data)
        staged.append((file, dest))
    swap_files(staged)
    return version


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


def leftover_temp_dirs() -> list[Path]:
    current = Path(getattr(sys, "_MEIPASS", "")).resolve() if hasattr(sys, "_MEIPASS") else None
    found = []
    for d in Path(os.getenv("TEMP", "")).glob("_MEI*"):
        try:
            if (
                d.is_dir()
                and d.resolve() != current
                and (d / "ffmpeg.zip").exists()
                and (d / "ui" / "index.html").exists()
            ):
                found.append(d)
        except OSError:
            pass
    return found


def other_instances_running() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    name = os.path.basename(sys.executable)
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            creationflags=0x08000000,
        ).stdout
        return out.lower().count(name.lower()) > 2
    except Exception:
        return True


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
        "name": "Componentes do app",
        "default": False,
        "desc": "Programas que o app usa para juntar vídeo e áudio e converter para MP3 (ffmpeg e Deno). "
        "Se apagar, o app prepara tudo de novo no próximo download, o que leva alguns segundos.",
    },
]


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
        if self._tray.icon is None or (not busy and not self._phone.running):
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

    def _quit(self):
        self._quitting = True
        self._phone.stop()
        self._tray.stop()
        self._window.destroy()

    def _on_main_closed(self):
        self._tray.stop()
        self._phone.stop()
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
            "engine_version": yt_dlp.version.__version__,
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
        base = Path(self._out_dir)
        path = it.get("filepath")
        rel = None
        if path:
            try:
                rel = str(Path(path).resolve().relative_to(base.resolve()))
            except ValueError:
                rel = path
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
            "error": it.get("error"),
            "needs_login": it.get("login_site"),
        }

    def _phone_files(self) -> list[dict]:
        base = Path(self._out_dir)
        found = []
        for dirpath, dirs, files in os.walk(base):
            if len(Path(dirpath).relative_to(base).parts) >= 3:
                dirs[:] = []
            for name in files:
                p = Path(dirpath) / name
                if p.suffix.lower() in MEDIA_EXTENSIONS:
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    found.append((st.st_mtime, p, st.st_size))
        found.sort(reverse=True)
        return [
            {
                "path": str(p.relative_to(base)).replace("\\", "/"),
                "name": p.name,
                "folder": str(p.parent.relative_to(base)).replace("\\", "/") if p.parent != base else "",
                "size_mb": round(size / 1048576, 1),
                "kind": "audio" if p.suffix.lower() in {".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac"} else "video",
            }
            for _, p, size in found[:80]
        ]

    def phone_start(self) -> dict:
        self._phone.start()
        self._tray.refresh()
        return self._phone.status()

    def phone_stop(self) -> dict:
        self._phone.stop()
        self._tray.refresh()
        return self._phone.status()

    def phone_status(self) -> dict:
        return self._phone.status()

    def phone_allow_firewall(self) -> bool:
        port = self._phone.server.server_address[1] if self._phone.server else PHONE_PORT
        args = (
            f'advfirewall firewall add rule name="Salvaí (celular)" dir=in action=allow protocol=TCP '
            f"localport={port} profile=private,public"
        )
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", args, None, 0)
        return result > 32

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
            jar = yt_dlp.cookies.extract_cookies_from_browser(browser, logger=_QuietLogger())
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
        sizes = {
            "webview": dir_size(WEBVIEW_DIR),
            "ytdlp": dir_size(CACHE_DIR),
            "temp": sum(dir_size(d) for d in leftover_temp_dirs()),
            "components": dir_size(BIN_DIR),
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
            if other_instances_running():
                notes.append("As sobras não foram apagadas porque há outra janela do app aberta.")
            else:
                for d in leftover_temp_dirs():
                    freed += remove_tree(d)
        if "components" in keys:
            with self._cv:
                busy = self._current is not None
            if busy:
                notes.append("Os componentes não foram apagados porque há um download em andamento.")
            else:
                with _runtime_lock:
                    freed += remove_tree(BIN_DIR)
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
            last = [0.0]

            def progress(fraction: float):
                now = time.monotonic()
                if now - last[0] > 0.15 or fraction >= 1:
                    last[0] = now
                    try:
                        self._window.run_js(f"window.app && app.otaProgress({round(fraction * 100)})")
                    except Exception:
                        pass

            version = install_release(release, Path(sys.executable).resolve(), CONFIG_PATH.parent / "update", progress)
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
        subprocess.Popen(args, close_fds=True, creationflags=0x00000008)
        threading.Timer(0.3, self._window.destroy).start()

    def skip_update(self, kind: str, version: str):
        self._cfg[f"skip_{kind}"] = version
        save_config(self._cfg)

    def open_release(self, url: str):
        if url.startswith(f"https://github.com/{APP_REPO}/"):
            os.startfile(url)

    def _check_updates(self):
        time.sleep(3)
        notices = []
        try:
            latest = github_latest("yt-dlp/yt-dlp")["tag_name"]
            current = yt_dlp.version.__version__
            if version_key(latest) > version_key(current) and self._cfg.get("skip_engine") != latest:
                notices.append({"kind": "engine", "current": current, "latest": latest})
        except Exception:
            pass
        try:
            release = github_latest(APP_REPO)
            latest = release["tag_name"].lstrip("v")
            if version_key(latest) > version_key(APP_VERSION) and self._cfg.get("skip_app") != latest:
                notices.append({"kind": "app", "current": APP_VERSION, "latest": latest, "url": release["html_url"]})
        except Exception:
            pass
        for notice in notices:
            try:
                self._window.run_js(f"window.app && app.updateAvailable({json.dumps(notice)})")
            except Exception:
                pass

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
            if not item["_info"]:
                item["status"] = "fetching"
                self._push(item)
            info = copy.deepcopy(self._ensure_info(item))
            if item["_cancel"]:
                raise Paused()
            item.update(status="downloading")
            self._push(item)

            opts = build_options(item["fmt"], item["quality"], item["out_dir"], self._ffmpeg, hook, url=item["url"])
            opts["postprocessor_hooks"] = [pp_hook]
            with make_ydl(opts) as ydl:
                if is_youtube(item["url"]):
                    result = ydl.process_ie_result(info, download=True)
                else:
                    result = ydl.extract_info(item["url"], download=True)
                req = result.get("requested_downloads") or []
                if not req and result.get("entries"):
                    entries = [e for e in result["entries"] if e]
                    req = (entries[0].get("requested_downloads") or []) if entries else []
                path = req[0].get("filepath") if req else ydl.prepare_filename(result)
            if item["fmt"] == "MP3" and path:
                path = os.path.splitext(path)[0] + ".mp3"
            item.update(status="done", progress=1.0, filepath=path if path and os.path.exists(path) else None)
        except Exception as e:
            if item["_cancel"]:
                item.update(status="paused", speed=None, eta=None)
            else:
                kind, msg = friendly_error(e, item["url"])
                item.update(
                    status="error",
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
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw")
            lines.append(f"{fmt} ok {info.get('format_id')}")
        except Exception as e:
            lines.append(f"{fmt} FAIL {clean_error(e)}")
    Path(out_dir, "selftest.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    if "--selftest" in sys.argv:
        splash_close()
        return selftest(sys.argv[sys.argv.index("--selftest") + 1])
    cleanup_old_versions()
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
