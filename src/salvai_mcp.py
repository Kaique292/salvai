import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

BRIDGE_PATH = Path(os.getenv("APPDATA", Path.home())) / "Salvai" / "bridge.json"
DETACHED_PROCESS = 0x00000008


def cleanup_leftovers() -> None:
    current = Path(getattr(sys, "_MEIPASS", "")).resolve() if hasattr(sys, "_MEIPASS") else None
    for folder in Path(os.getenv("TEMP", "")).glob("_MEI*"):
        try:
            if folder.resolve() == current or not (folder / "salvai-mcp.marker").exists():
                continue
            trash = folder.with_name(folder.name + ".del")
            folder.rename(trash)
            shutil.rmtree(trash, ignore_errors=True)
        except OSError:
            continue


mcp = MCPServer(
    "salvai",
    title="Salvaí",
    instructions=(
        "Salvaí is the user's video/music downloader app on this Windows PC (YouTube, Instagram, TikTok, X, "
        "Facebook and ~1800 other sites). Use search_media to find content, download_media to save it "
        "(as MP4 video or MP3 audio) into subfolders of the user's download folder, list_downloads to follow "
        "progress, and list_files / move_file to organize what was saved. Downloads also appear in the app's "
        "window, so the user can watch them. Prefer clear, human folder names (e.g. 'Vestibular/Química'). "
        "If a download fails with needs_login, tell the user to connect that account in the app (person icon → "
        "Contas) — never ask for passwords."
    ),
)


def find_app() -> str | None:
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    for candidate in (os.getenv("SALVAI_EXE"), here / "Salvai.exe", here / "dist" / "Salvai.exe"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def read_bridge():
    try:
        return json.loads(BRIDGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def request(bridge: dict, method: str, path: str, body=None, timeout: float = 60):
    url = f"http://127.0.0.1:{bridge['port']}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {bridge['token']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            message = json.load(e).get("error")
        except Exception:
            message = str(e)
        raise ToolError(message) from e


def bridge_is_alive(bridge) -> bool:
    if not bridge:
        return False
    try:
        request(bridge, "GET", "/status", timeout=3)
        return True
    except Exception:
        return False


def open_bridge() -> dict:
    bridge = read_bridge()
    if bridge_is_alive(bridge):
        return bridge
    exe = find_app()
    if not exe:
        raise ToolError("O Salvaí não está aberto e não encontrei o Salvai.exe. Abra o app e tente de novo.")
    subprocess.Popen([exe], close_fds=True, creationflags=DETACHED_PROCESS)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(1)
        bridge = read_bridge()
        if bridge_is_alive(bridge):
            return bridge
    raise ToolError("Abri o Salvaí, mas ele não respondeu a tempo. Tente de novo em alguns segundos.")


def call(method: str, path: str, body=None, timeout: float = 60):
    return request(open_bridge(), method, path, body, timeout)


class DownloadItem(BaseModel):
    url: str = Field(description="Link of the video/post/track (YouTube, Instagram, TikTok, X, Facebook, …).")
    format: Literal["mp4", "mp3"] = Field("mp4", description="mp4 = video, mp3 = audio only.")
    quality: str = Field("max", description="mp4: max, 2160, 1440, 1080, 720, 480, 360. mp3: max, 320, 256, 192, 128.")
    folder: str = Field(
        "",
        description="Subfolder inside the user's download folder, e.g. 'Vestibular/Química'. "
        "Empty = main download folder. Created automatically.",
    )


@mcp.tool(
    description="Show the Salvaí app status: download folder, connected accounts and how many downloads "
    "are in each state."
)
def salvai_status() -> dict:
    return call("GET", "/status")


@mcp.tool(
    description="Search YouTube (or SoundCloud) and return titles, channels, durations and links ready for "
    "download_media. Be specific, e.g. 'aula estequiometria vestibular' or 'lofi para estudar 1 hora'."
)
def search_media(query: str, limit: int = 5, site: Literal["youtube", "soundcloud"] = "youtube") -> dict:
    return call("POST", "/search", {"query": query, "limit": limit, "site": site}, timeout=90)


@mcp.tool(
    description="Queue one or more downloads in Salvaí. Each item has its own format, quality and destination "
    "folder. Returns the download ids; use list_downloads to follow progress. Downloads run one at "
    "a time in the app."
)
def download_media(items: list[DownloadItem]) -> dict:
    return call("POST", "/downloads", {"items": [i.model_dump() for i in items]})


@mcp.tool(
    description="List downloads with status (queued, downloading, done, error, paused…), progress %, saved "
    "file and errors. Pass ids to filter. wait_seconds (max 300) waits until those downloads finish "
    "before answering — handy right after download_media to report the final result."
)
def list_downloads(ids: list[str] | None = None, wait_seconds: int = 0) -> dict:
    path = "/downloads" + (f"?ids={urllib.parse.quote(','.join(ids))}" if ids else "")
    deadline = time.time() + max(0, min(wait_seconds, 300))
    while True:
        result = call("GET", path)
        unfinished = [d for d in result["downloads"] if d["status"] not in ("done", "error")]
        if not unfinished or time.time() >= deadline:
            result["all_finished"] = not unfinished
            return result
        time.sleep(2)


@mcp.tool(
    description="List files saved in the user's download folder (or a subfolder), with size and date. "
    "Paths are relative to the download folder."
)
def list_files(folder: str = "", depth: int = 3) -> dict:
    return call("GET", f"/files?{urllib.parse.urlencode({'folder': folder, 'depth': depth})}")


@mcp.tool(
    description="Move a saved file (relative path from list_files) into another subfolder of the download "
    "folder. Only works inside the download folder and never deletes anything. Name clashes get "
    "' (2)' appended."
)
def move_file(path: str, folder: str) -> dict:
    return call("POST", "/move", {"path": path, "folder": folder})


def main():
    threading.Thread(target=cleanup_leftovers, daemon=True).start()
    mcp.run()


if __name__ == "__main__":
    main()
