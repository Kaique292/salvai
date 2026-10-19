import argparse
import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import segno

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
MB = 1024 * 1024
LOW_RES = {"eRsGyueVLvQ"}
DEFAULTS = {"webview", "ytdlp", "temp"}


def thumb(video_id: str) -> str:
    return f"img/{video_id}.jpg"


def fetch_thumbs(target: Path) -> None:
    target.mkdir()
    for video_id in ("aqz-KE-bpKQ", "eRsGyueVLvQ", "R6MlUcmOul8", "Y-rmzh0PI3c", "WhWc3b3KhnY"):
        size = "mqdefault" if video_id in LOW_RES else "maxresdefault"
        with urllib.request.urlopen(f"https://i.ytimg.com/vi/{video_id}/{size}.jpg", timeout=30) as r:
            (target / f"{video_id}.jpg").write_bytes(r.read())


LINKS = [
    ("https://www.youtube.com/@blender/spring", "MP4"),
    ("https://www.tiktok.com/@blender/video/1", "MP3"),
    ("https://www.instagram.com/stories/blender/1", "MP3"),
]
PEEKS = {
    LINKS[0][0]: {
        "title": "Spring - Blender Open Movie",
        "site": "YouTube",
        "author": "Blender",
        "thumb": thumb("WhWc3b3KhnY"),
    },
    LINKS[1][0]: {
        "title": "Bastidores de Cosmos Laundromat em 30 segundos",
        "site": "TikTok",
        "author": "blender",
        "thumb": thumb("Y-rmzh0PI3c"),
    },
    LINKS[2][0]: {
        "site": "Instagram",
        "error": "Stories do Instagram só podem ser vistos com login, mesmo de perfis públicos.",
        "login_site": "instagram",
    },
}
ITEMS = [
    {
        "id": "a",
        "url": "https://youtu.be/aqz-KE-bpKQ",
        "fmt": "MP4",
        "quality": "Máxima",
        "status": "downloading",
        "progress": 0.64,
        "speed": 8.4 * MB,
        "eta": 46,
        "title": "Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film",
        "thumb": thumb("aqz-KE-bpKQ"),
        "duration": 634,
        "site": "YouTube",
    },
    {
        "id": "b",
        "url": "https://youtu.be/eRsGyueVLvQ",
        "fmt": "MP3",
        "quality": "320 kbps",
        "status": "queued",
        "title": "Sintel - Open Movie by Blender Foundation",
        "thumb": thumb("eRsGyueVLvQ"),
        "duration": 888,
        "site": "YouTube",
        "folder": "Trilha para estudar",
        "source": "claude",
    },
    {
        "id": "c",
        "url": "https://youtu.be/R6MlUcmOul8",
        "fmt": "MP4",
        "quality": "1080p",
        "status": "done",
        "progress": 1,
        "title": "Tears of Steel - Blender VFX Open Movie",
        "thumb": thumb("R6MlUcmOul8"),
        "duration": 734,
        "site": "YouTube",
        "folder": "Filmes",
        "source": "phone",
    },
    {
        "id": "d",
        "url": "https://vimeo.com/blender/cosmos",
        "fmt": "MP4",
        "quality": "Máxima",
        "status": "paused",
        "progress": 0.37,
        "title": "Cosmos Laundromat - First Cycle",
        "thumb": thumb("Y-rmzh0PI3c"),
        "duration": 730,
        "site": "Vimeo",
    },
]
STORAGE = [
    (
        "webview",
        "Cache da interface",
        "Miniaturas dos vídeos e arquivos da tela do app, guardados para abrir mais rápido. "
        "Pode apagar sem medo: tudo é baixado de novo quando precisar.",
        20 * MB,
    ),
    (
        "ytdlp",
        "Dados do YouTube",
        "Informações que o motor de download guarda para reconhecer os vídeos mais rápido. Pode apagar sem medo.",
        410 * 1024,
    ),
    (
        "temp",
        "Sobras de aberturas anteriores",
        "Cópias temporárias do app que ficam para trás quando ele é fechado à força "
        "(pelo Gerenciador de Tarefas, por exemplo). Pode apagar sem medo.",
        107 * MB,
    ),
    (
        "components",
        "Componentes baixados",
        "O Deno (motor que o YouTube exige quando o PC não tem Node.js) e as atualizações do motor de download. "
        "Se apagar, o app baixa de novo quando precisar.",
        53 * MB,
    ),
    (
        "essential",
        "Essenciais",
        "O ffmpeg junta vídeo e áudio e converte para MP3, e o conector deixa o Claude usar o Salvaí. "
        "Fazem parte do app e são recriados sozinhos, por isso não podem ser removidos.",
        134 * MB,
    ),
]


def fake_data(version: str) -> dict:
    now = time.time()
    phone_url = "http://192.168.0.12:8765/?k=7f3k9q2m"
    done = {"state": "done", "done": 1, "total": 1, "files": 1, "finished": 1}
    return {
        "version": version,
        "links": LINKS,
        "peeks": PEEKS,
        "items": ITEMS,
        "storage": {
            "version": version,
            "categories": [
                {"key": k, "name": n, "desc": d, "size": s, "default": k in DEFAULTS, "locked": k == "essential"}
                for k, n, d, s in STORAGE
            ],
            "total": sum(s for *_, s in STORAGE),
        },
        "accounts": {
            "sites": [
                {"key": "instagram", "name": "Instagram", "connected": True, "since": now - 86400 * 3, "source": "app"},
                {"key": "tiktok", "name": "TikTok", "connected": False},
                {"key": "x", "name": "X (Twitter)", "connected": False},
                {"key": "facebook", "name": "Facebook", "connected": False},
            ],
            "browsers": [{"key": "edge", "name": "Microsoft Edge"}],
        },
        "phone": {
            "on": True,
            "url": phone_url,
            "others": [],
            "qr": segno.make(phone_url, error="m").svg_inline(border=2, dark="#111114", light="#ffffff", omitsize=True),
            "network": {"ready": True, "kind": "wifi", "name": "Casa", "public": False},
            "devices": [
                {"id": "p1", "name": "iPhone", "ip": "192.168.0.21", "since": now - 900, "seen": now, "online": True}
            ],
            "history": [],
            "incoming": None,
            "received": [],
        },
        "room": {
            "role": "host",
            "phase": "open",
            "name": "Kaique",
            "host": "Kaique",
            "url": "https://sunny-river-studio.trycloudflare.com",
            "code": "B39 HBJ",
            "people": [{"id": "p", "name": "Ana", "device": "Android", "state": "approved", "online": True}],
            "theirs": [
                {
                    "id": "t1",
                    "kind": "file",
                    "name": "Formatura da Ana.mp4",
                    "size": 1.4 * 1024 * MB,
                    "count": 1,
                    "risky": False,
                    "owner": "Ana",
                    "thumb": thumb("R6MlUcmOul8"),
                    "progress": {
                        "state": "sending",
                        "done": 0.58 * 1.4 * 1024 * MB,
                        "total": 1.4 * 1024 * MB,
                        "files": 1,
                        "finished": 0,
                    },
                },
                {
                    "id": "t2",
                    "kind": "folder",
                    "name": "Fotos da viagem",
                    "size": 312 * MB,
                    "count": 48,
                    "risky": False,
                    "owner": "Ana",
                    "thumb": thumb("Y-rmzh0PI3c"),
                    "progress": None,
                },
                {
                    "id": "t3",
                    "kind": "file",
                    "name": "Pôr do sol.jpg",
                    "size": 2.7 * MB,
                    "count": 1,
                    "risky": False,
                    "owner": "Ana",
                    "thumb": thumb("WhWc3b3KhnY"),
                    "progress": done,
                },
            ],
            "mine": [
                {
                    "id": "m1",
                    "kind": "file",
                    "name": "Sintel.mp4",
                    "size": 640 * MB,
                    "count": 1,
                    "risky": False,
                    "fetched": [],
                    "thumb": thumb("eRsGyueVLvQ"),
                }
            ],
        },
    }


STUB = """
const DATA = __DATA__;
window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16);
const still = document.createElement("style");
still.textContent = `*, *::before, *::after {
  transition: none !important;
  animation-duration: 0s !important;
  animation-delay: 0s !important;
}`;
document.head.append(still);
const params = new URLSearchParams(location.search);
const shot = params.get("shot");
const theme = params.get("theme") || "dark";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const roomState = () => {
  const room = JSON.parse(JSON.stringify(DATA.room));
  room.theirs[0].progress.done += (Date.now() - started) * 1500;
  return room;
};
const started = Date.now();
const impl = {
  init: async () => ({
    theme,
    version: DATA.version,
    engine_version: "2026.10.12",
    out_dir: "C:\\\\Users\\\\voce\\\\Downloads",
    items: shot === "main" ? DATA.items : [],
  }),
  ready: async () => true,
  paste: async () => "",
  peek: async (url) => DATA.peeks[url],
  accounts: async () => DATA.accounts,
  storage_info: async () => DATA.storage,
  phone_status: async () => DATA.phone,
  room_status: async () => roomState(),
};
window.pywebview = { api: new Proxy({}, { get: (_, k) => impl[k] || (async () => null) }) };
window.addEventListener("load", async () => {
  window.dispatchEvent(new Event("pywebviewready"));
  while (!document.body.classList.contains("ready")) await wait(50);
  await wait(500);
  const click = (s) => document.querySelector(s).click();
  if (shot === "main") {
    for (const [url, fmt] of DATA.links) {
      click(`#format button[data-value="${fmt}"]`);
      document.querySelector("#link-input").value = url;
      click("#add");
      await wait(150);
    }
    document.querySelector("#link-input").value = "";
    document.querySelector("#link-input").focus();
  } else if (shot === "room") {
    click("#room-btn");
    await wait(1200);
    click('.room-tabs button[data-rtab="theirs"]');
  } else {
    click(`#${shot}-btn`);
  }
});
"""

SHOTS = [
    ("app-escuro.png", "main", "dark", 880),
    ("app-claro.png", "main", "light", 880),
    ("contas.png", "accounts", "dark", 860),
    ("armazenamento.png", "storage", "dark", 860),
    ("celular.png", "phone", "dark", 900),
    ("sala-de-troca.png", "room", "dark", 900),
]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def build_site(target: Path, version: str) -> None:
    shutil.copytree(ROOT / "src" / "ui", target)
    fetch_thumbs(target / "img")
    page = target / "index.html"
    html = page.read_text(encoding="utf-8")
    page.write_text(
        html.replace(
            '<script src="sortable.min.js">', '<script src="stub.js"></script>\n    <script src="sortable.min.js">'
        ),
        encoding="utf-8",
    )
    data = json.dumps(fake_data(version), ensure_ascii=False)
    (target / "stub.js").write_text(STUB.replace("__DATA__", data), encoding="utf-8")


def capture(url: str, out: Path, height: int, profile: Path) -> None:
    subprocess.run(
        [
            str(EDGE),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            f"--user-data-dir={profile}",
            "--force-device-scale-factor=1.5",
            f"--window-size=1080,{height}",
            "--virtual-time-budget=15000",
            f"--screenshot={out}",
            url,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera os prints do README a partir da interface atual.")
    parser.add_argument("--version", default=(ROOT / "version.txt").read_text().strip())
    parser.add_argument("--only", nargs="*", help="nomes dos arquivos a gerar (ex.: contas.png)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "ui"
        build_site(site, args.version)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        for name, shot, theme, height in SHOTS:
            if args.only and name not in args.only:
                continue
            capture(
                f"http://127.0.0.1:{port}/index.html?shot={shot}&theme={theme}", OUT / name, height, Path(tmp) / "edge"
            )
            print(f"docs/images/{name} gerado")
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
