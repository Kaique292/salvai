import hashlib
import json
import os
import time
import types
from pathlib import Path

import pytest
from conftest import FakeResponse, FakeWindow, FakeYDL, wait_until, zip_bytes

import app

YT = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
TT = "https://www.tiktok.com/@a/video/1"


def downloaded(name="Vídeo.mp4", create=True, result=None, cancel_wait=False):
    def run(ydl, url):
        folder = os.path.dirname(ydl.opts["outtmpl"])
        path = os.path.join(folder, name)
        if create:
            Path(path).write_bytes(b"x")
        for hook in ydl.opts["progress_hooks"]:
            hook(
                {
                    "status": "downloading",
                    "total_bytes": 100,
                    "downloaded_bytes": 50,
                    "speed": 1,
                    "eta": 2,
                    "info_dict": {"acodec": "none"},
                }
            )
            hook(
                {
                    "status": "downloading",
                    "total_bytes_estimate": 100,
                    "downloaded_bytes": 100,
                    "info_dict": {"vcodec": "none"},
                }
            )
            hook({"status": "downloading", "downloaded_bytes": 1})
            hook({"status": "finished"})
            if cancel_wait:
                for _ in range(500):
                    hook({"status": "downloading", "total_bytes": 10, "downloaded_bytes": 5})
                    time.sleep(0.01)
        for hook in ydl.opts.get("postprocessor_hooks", []):
            hook({"status": "started"})
            hook({"status": "started"})
            hook({"status": "finished"})
        if result is not None:
            return result
        return {"title": "Título", "duration": 9, "requested_downloads": [{"filepath": path}]}

    return run


def youtube_info(title="Me at the zoo"):
    return {"id": "jNQXAC9IVRw", "title": title, "extractor_key": "Youtube", "webpage_url": YT, "duration": 19}


def finish(api, count=1, timeout=10):
    return wait_until(lambda: sum(1 for i in api._items.values() if i["status"] in ("done", "error")) >= count, timeout)


def item_by_url(api, url):
    return next(i for i in api._items.values() if i["url"] == url)


def test_init_reports_state(api):
    state = api.init()
    assert state["theme"] == "dark" and state["version"] == app.APP_VERSION
    assert state["engine_version"] == "2026.8.19" and state["items"] == []


def test_enqueue_and_youtube_download(api):
    FakeYDL.script = {"jNQXAC9IVRw": {"info": youtube_info(), "download": downloaded()}}
    created = api._enqueue(f"{YT} {YT} texto", "MP4", "Máxima", folder="Vestibular/../Química", source="claude")
    assert len(created) == 1 and created[0]["folder"] == "Vestibular/Química"
    assert created[0]["thumb"].endswith("jNQXAC9IVRw/hqdefault.jpg")
    assert finish(api)
    item = created[0]
    assert item["status"] == "done" and item["filepath"].endswith("Vídeo.mp4") and item["_info"] is None
    assert any("app.update" in js for js in api._window.js)


def test_youtube_403_renews_links_and_retries_once(api):
    calls = []

    def flaky(ydl, url):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("unable to download video data: HTTP Error 403: Forbidden")
        return downloaded()(ydl, url)

    FakeYDL.script = {"jNQXAC9IVRw": {"info": youtube_info(), "download": flaky}}
    api.add(YT, "MP4", "Máxima")
    assert finish(api)
    assert item_by_url(api, YT)["status"] == "done" and len(calls) == 2


def test_youtube_other_errors_are_not_retried(api):
    calls = []

    def broken(ydl, url):
        calls.append(url)
        raise RuntimeError("Video unavailable")

    FakeYDL.script = {"jNQXAC9IVRw": {"info": youtube_info(), "download": broken}}
    api.add(YT, "MP4", "Máxima")
    assert finish(api)
    assert item_by_url(api, YT)["status"] == "error" and len(calls) == 1


def test_download_other_site_uses_single_extraction(api):
    FakeYDL.script = {"tiktok": {"info": {"title": "Peek"}, "download": downloaded(name="tt.mp4")}}
    api._peek_cache[TT] = (time.time(), {"title": "Do cache", "thumb": "https://t/x.jpg", "site": "TikTok"})
    api.add(TT, "MP4", "720p")
    assert finish(api)
    item = item_by_url(api, TT)
    assert item["status"] == "done" and item["title"] == "Do cache" and item["thumb"] == "https://t/x.jpg"


def test_download_other_site_without_cache_takes_title_from_result(api):
    def without_title(ydl, url):
        return downloaded(name="v.mp4", result={"title": "Do download", "duration": 3, "requested_downloads": []})(
            ydl, url
        )

    FakeYDL.script = {"vimeo": {"error": RuntimeError("sem metadados"), "download": without_title}}
    api.add("https://vimeo.com/123", "MP4", "Máxima")
    assert finish(api)
    item = item_by_url(api, "https://vimeo.com/123")
    assert item["title"] == "Do download" and item["status"] == "done" and item["filepath"] is None


def test_download_playlist_mp3(api):
    def playlist(ydl, url):
        folder = os.path.dirname(ydl.opts["outtmpl"])
        Path(folder, "faixa.mp3").write_bytes(b"x")
        return {"entries": [None, {"requested_downloads": [{"filepath": os.path.join(folder, "faixa.webm")}]}]}

    FakeYDL.script = {"soundcloud": {"info": {"title": "Lista"}, "download": playlist}}
    api.add("https://soundcloud.com/a/sets/b", "MP3", "320 kbps")
    assert finish(api)
    item = item_by_url(api, "https://soundcloud.com/a/sets/b")
    assert item["filepath"].endswith("faixa.mp3")


def test_download_empty_playlist(api):
    FakeYDL.script = {
        "empty": {"info": {"title": "Nada"}, "download": lambda ydl, url: {"title": "Nada", "entries": [None]}}
    }
    api.add("https://exemplo.org/empty", "MP4", "Máxima")
    assert finish(api)
    assert item_by_url(api, "https://exemplo.org/empty")["status"] == "done"


def test_download_error_retry_and_clear(api):
    FakeYDL.script = {
        "instagram": {
            "error": RuntimeError("login required"),
            "download": lambda y, u: (_ for _ in ()).throw(RuntimeError("login required")),
        }
    }
    api.add("https://www.instagram.com/stories/a/1/", "MP4", "Máxima")
    assert finish(api)
    item = item_by_url(api, "https://www.instagram.com/stories/a/1/")
    assert item["status"] == "error" and item["login_site"] == "instagram"
    FakeYDL.script = {"instagram": {"info": {"title": "Story"}, "download": downloaded(name="s.mp4")}}
    api.retry(item["id"])
    assert wait_until(lambda: item["status"] == "done")
    api.retry(item["id"])
    api.retry("inexistente")
    assert api.clear_done() == [item["id"]] and not api._items


def test_setup_runtime_failure(api, monkeypatch):
    monkeypatch.setattr(app, "js_runtimes", lambda: {})

    def no_internet():
        raise OSError("offline")

    monkeypatch.setattr(app, "ensure_js_runtime", no_internet)
    api.add(YT, "MP4", "Máxima")
    assert finish(api)
    assert "sem internet" in item_by_url(api, YT)["error"]


def test_setup_runtime_success(api, monkeypatch):
    state = {"ready": False}
    monkeypatch.setattr(app, "js_runtimes", lambda: {"node": {}} if state["ready"] else {})
    monkeypatch.setattr(app, "ensure_js_runtime", lambda: state.update(ready=True))
    FakeYDL.script = {"jNQXAC9IVRw": {"info": youtube_info(), "download": downloaded()}}
    api.add(YT, "MP4", "Máxima")
    assert finish(api) and item_by_url(api, YT)["status"] == "done"


def test_pause_by_reorder_and_resume(api):
    FakeYDL.script = {
        "slow": {"info": {"title": "Lento"}, "download": downloaded(name="lento.mp4", cancel_wait=True)},
        "fast": {"info": {"title": "Rápido"}, "download": downloaded(name="rapido.mp4")},
    }
    api.add("https://exemplo.org/slow", "MP4", "Máxima")
    slow = item_by_url(api, "https://exemplo.org/slow")
    assert wait_until(lambda: slow["status"] == "downloading" and api._current is slow)
    api.add("https://exemplo.org/fast", "MP4", "Máxima")
    fast = item_by_url(api, "https://exemplo.org/fast")
    api.reorder([fast["id"], slow["id"]])
    assert wait_until(lambda: fast["status"] == "done", 10)
    assert wait_until(lambda: slow["status"] in ("downloading", "paused"))
    api.remove(slow["id"])
    api.remove("inexistente")


def test_pause_before_download_starts(api, monkeypatch):
    FakeYDL.script = {"jNQXAC9IVRw": {"info": youtube_info(), "download": downloaded()}}
    real = api._ensure_info

    def cancel_during_info(item):
        info = real(item)
        item["_cancel"] = True
        return info

    monkeypatch.setattr(api, "_ensure_info", cancel_during_info)
    api.add(YT, "MP4", "Máxima")
    item = item_by_url(api, YT)
    assert wait_until(lambda: item["status"] == "paused")
    with api._cv:
        item["status"] = "error"


def test_preempt_guards(api):
    api._current = None
    api._preempt()
    api._current = {"status": "processing"}
    api._preempt()
    current = {"id": "a", "status": "downloading", "_cancel": False}
    api._items = {"a": current}
    api._order = ["a"]
    api._current = current
    api._preempt()
    assert current["_cancel"] is False
    api._current = None


def test_ensure_info_caches_and_picks_thumbnails(api):
    FakeYDL.script = {"vimeo": {"info": {"title": "V", "thumbnails": [{"url": "a"}, {"url": "b"}]}}}
    item = {
        "url": "https://vimeo.com/1",
        "fmt": "MP4",
        "quality": "Máxima",
        "out_dir": api._out_dir,
        "_info": None,
        "_info_at": 0,
        "_fetch_lock": app.threading.Lock(),
        "title": None,
        "thumb": None,
        "site": "",
        "status": "queued",
    }
    info = api._ensure_info(item)
    assert item["thumb"] == "b" and item["site"] == "Vimeo"
    assert api._ensure_info(item) is info
    item.update(_info=None, thumb="ja-tinha")
    api._ensure_info(item)
    assert item["thumb"] == "ja-tinha"
    FakeYDL.script = {"vimeo": {"info": {"title": "V"}}}
    item.update(_info=None, thumb=None)
    api._ensure_info(item)
    assert item["thumb"] is None
    item.update(_info=None, status="done")
    assert api._ensure_info(item)["title"] == "V" and item["_info"] is None


def test_fetch_meta_swallows_errors(api):
    FakeYDL.script = {"quebrado": {"error": RuntimeError("x")}}
    item = {
        "url": "https://exemplo.org/quebrado",
        "fmt": "MP4",
        "quality": "Máxima",
        "out_dir": api._out_dir,
        "_info": None,
        "_info_at": 0,
        "_fetch_lock": app.threading.Lock(),
        "title": None,
        "thumb": None,
        "site": "",
        "id": "z",
    }
    api._fetch_meta(item)
    assert item["title"] is None


def test_open_item(api, monkeypatch):
    opened = []
    monkeypatch.setattr(app.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(app.os, "startfile", lambda path: opened.append(path), raising=False)
    file = Path(api._out_dir, "a.mp4")
    file.write_bytes(b"x")
    api._items = {"a": {"filepath": str(file), "out_dir": api._out_dir}, "b": {"filepath": None, "out_dir": "C:/x"}}
    api.open_item("a")
    api.open_item("b")
    api.open_item("zz")
    assert opened[0][0] == "explorer" and opened[1] == "C:/x"


def test_choose_folder(api, tmp_path):
    assert api.choose_folder() is None
    api._window.dialog_result = [str(tmp_path / "a")]
    assert api.choose_folder() == str(tmp_path / "a") and app.load_config()["out_dir"] == str(tmp_path / "a")
    api._window.dialog_result = str(tmp_path / "b")
    assert api.choose_folder() == str(tmp_path / "b")


def test_peek_youtube_oembed_and_cache(api, monkeypatch):
    calls = []

    def urlopen(url, timeout=0):
        calls.append(url)
        return FakeResponse(json.dumps({"title": "Zoo", "author_name": "jawed", "thumbnail_url": "t"}).encode())

    monkeypatch.setattr(app.urllib.request, "urlopen", urlopen)
    assert api.peek(YT) == {"title": "Zoo", "author": "jawed", "thumb": "t", "site": "YouTube"}
    assert api.peek(YT)["title"] == "Zoo" and len(calls) == 1


def test_peek_youtube_falls_back_to_engine(api, monkeypatch):
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda url, timeout=0: (_ for _ in ()).throw(OSError()))
    FakeYDL.script = {"jNQXAC9IVRw": {"info": dict(youtube_info(), uploader="jawed")}}
    result = api.peek(YT)
    assert result["thumb"].endswith("mqdefault.jpg") and result["author"] == "jawed"


def test_peek_other_sites_and_errors(api):
    FakeYDL.script = {
        "vimeo": {"info": {"title": "V", "thumbnails": [{"url": "a"}], "channel": "c", "extractor_key": "Vimeo"}},
        "fotos": {"info": {"title": "F"}},
        "privado": {"error": RuntimeError("login required")},
    }
    assert api.peek("https://vimeo.com/1") == {"title": "V", "author": "c", "thumb": "a", "site": "Vimeo"}
    assert api.peek("https://exemplo.org/fotos")["thumb"] is None
    result = api.peek("https://www.instagram.com/privado/")
    assert result["error_kind"] == "login" and result["login_site"] == "instagram"
    assert "https://www.instagram.com/privado/" not in api._peek_cache


def test_check_url(api, monkeypatch):
    monkeypatch.setattr(app, "supported_site", lambda url: True)
    assert api.check_url("https://x") is True
    monkeypatch.setattr(app, "supported_site", lambda url: (_ for _ in ()).throw(RuntimeError()))
    assert api.check_url("https://x") is False


def test_accounts_and_browsers(api, monkeypatch, tmp_path):
    edge = tmp_path / "edge"
    edge.mkdir()
    monkeypatch.setitem(app.BROWSERS, "edge", ("Microsoft Edge", edge))
    app.save_sessions({"tiktok": {"cookies": [], "since": 5, "source": "app"}})
    api._login_windows["x"] = object()
    data = api.accounts()
    tiktok = next(s for s in data["sites"] if s["key"] == "tiktok")
    assert tiktok["connected"] and tiktok["since"] == 5
    assert next(s for s in data["sites"] if s["key"] == "x")["busy"]
    assert {"key": "edge", "name": "Microsoft Edge"} in data["browsers"]


def test_login_flow_connects(api, monkeypatch, no_sleep):
    win = FakeWindow()
    monkeypatch.setattr(app.webview, "create_window", lambda *a, **k: win)
    started = []
    monkeypatch.setattr(api, "_watch_login", lambda *args: started.append(args))
    api.login("instagram")
    api.login("instagram")
    assert len(started) == 1
    state = started[0][2]
    win.events.closed.fire()
    assert state["open"] is False


def make_cookie(name, value, domain=".instagram.com"):
    from http.cookies import SimpleCookie

    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["domain"] = domain
    return cookie


def test_watch_login_saves_session(api, no_sleep):
    win = FakeWindow()
    win.fail.add("destroy")
    win.cookies = [make_cookie("sessionid", "abc")]
    api._login_windows["instagram"] = win
    api._watch_login("instagram", win, {"open": True})
    assert "instagram" in app.load_sessions() and "instagram" not in api._login_windows


def test_watch_login_already_closed(api):
    win = FakeWindow()
    api._login_windows["instagram"] = win
    api._watch_login("instagram", win, {"open": False})
    assert "instagram" not in api._login_windows and "instagram" not in app.load_sessions()


def test_watch_login_until_closed(api, monkeypatch):
    win = FakeWindow()
    win.fail.add("get_cookies")
    state = {"open": True}
    ticks = {"n": 0}

    def sleep(seconds):
        ticks["n"] += 1
        if ticks["n"] == 2:
            win.fail.discard("get_cookies")
        if ticks["n"] == 3:
            state["open"] = False

    monkeypatch.setattr(app.time, "sleep", sleep)
    api._watch_login("instagram", win, state)
    assert "instagram" not in app.load_sessions()
    state2 = {"open": True}
    monkeypatch.setattr(app.time, "sleep", lambda s: state2.update(open=False))
    api._watch_login("instagram", win, state2)


def test_logout(api):
    app.save_sessions({"x": {"cookies": [], "since": 1}})
    api._window.fail.add("clear_cookies")
    data = api.logout("x")
    assert not next(s for s in data["sites"] if s["key"] == "x")["connected"]


def jar_cookie(name, value, domain):
    return types.SimpleNamespace(name=name, value=value, domain=domain, path="", secure=0, expires=None)


def test_import_browser(api, monkeypatch):
    monkeypatch.setattr(
        app,
        "yt_dlp",
        app.yt_dlp.__class__(
            **{
                **vars(app.yt_dlp),
                "cookies": types.SimpleNamespace(
                    extract_cookies_from_browser=lambda b, logger=None: [
                        jar_cookie("sessionid", "1", ".tiktok.com"),
                        jar_cookie("outro", "2", ".tiktok.com"),
                    ]
                ),
            }
        ),
    )
    result = api.import_browser("edge")
    assert result["ok"] and "TikTok" in result["message"]
    monkeypatch.setattr(
        app,
        "yt_dlp",
        app.yt_dlp.__class__(
            **{
                **vars(app.yt_dlp),
                "cookies": types.SimpleNamespace(extract_cookies_from_browser=lambda b, logger=None: []),
            }
        ),
    )
    assert api.import_browser("edge")["ok"] is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Could not copy Chrome cookie database", "trava"),
        ("Failed to decrypt with DPAPI", "criptografia"),
        ("algo diferente", "Não consegui ler"),
    ],
)
def test_import_browser_errors(api, monkeypatch, error, expected):
    def fail(browser, logger=None):
        raise RuntimeError(error)

    monkeypatch.setattr(
        app,
        "yt_dlp",
        app.yt_dlp.__class__(
            **{**vars(app.yt_dlp), "cookies": types.SimpleNamespace(extract_cookies_from_browser=fail)}
        ),
    )
    result = api.import_browser("chrome")
    assert not result["ok"] and expected in result["message"]


def test_storage_info_and_clear(api, monkeypatch, tmp_path):
    (app.CACHE_DIR / "yt-dlp").mkdir(parents=True)
    (app.CACHE_DIR / "yt-dlp" / "a").write_bytes(b"12")
    app.BIN_DIR.mkdir(parents=True)
    (app.BIN_DIR / "ffmpeg.exe").write_bytes(b"12345678")
    (app.BIN_DIR / "ffmpeg.version").write_text("v")
    (app.BIN_DIR / "deno.exe").write_bytes(b"123")
    app.ENGINE_DIR.mkdir(parents=True)
    (app.ENGINE_DIR / "yt-dlp-2099.1.1.zip").write_bytes(b"1")
    leftover = tmp_path / "_MEI9"
    leftover.mkdir()
    (leftover / "x").write_bytes(b"1234")
    cache = app.WEBVIEW_DIR / "EBWebView" / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "c").write_bytes(b"1")
    (app.WEBVIEW_DIR / "EBWebView" / "Local State").write_bytes(b"perfil")
    state = {"left": [leftover]}
    monkeypatch.setattr(app, "leftover_temp_dirs", lambda: state["left"])
    monkeypatch.setattr(app, "cleanup_leftovers", lambda: 0)
    info = api.storage_info()
    sizes = {c["key"]: c["size"] for c in info["categories"]}
    assert sizes == {"webview": 7, "ytdlp": 2, "temp": 4, "components": 4, "essential": 9}
    assert next(c for c in info["categories"] if c["key"] == "essential")["locked"]
    api._current = {"id": "rodando"}
    result = api.clear_storage(["ytdlp", "temp", "components", "webview"])
    assert len(result["notes"]) == 3 and app.WEBVIEW_CLEAR_FLAG.exists()
    assert (app.BIN_DIR / "deno.exe").exists()
    api._current = None
    state["left"] = []
    result = api.clear_storage(["temp", "components"])
    assert result["freed"] == 3 + 1 and not (app.BIN_DIR / "deno.exe").exists()
    assert (app.BIN_DIR / "ffmpeg.exe").exists() and not app.ENGINE_DIR.exists()
    app.WEBVIEW_CLEAR_FLAG.unlink()
    api.clear_storage(["webview"])
    assert app.WEBVIEW_CLEAR_FLAG.exists()


def test_clear_storage_empty_webview(api):
    result = api.clear_storage(["webview"])
    assert result["notes"] == [] and not app.WEBVIEW_CLEAR_FLAG.exists()


def engine_zip(version="2027.1.2"):
    return zip_bytes({"yt_dlp/version.py": f"__version__ = '{version}'\n", "__main__.py": ""})


def test_update_engine(api, monkeypatch):
    data = engine_zip()
    sums = f"{hashlib.sha256(data).hexdigest()}  yt-dlp\nabc  yt-dlp.exe\n"
    monkeypatch.setattr(app, "http_get", lambda url, timeout=60: sums.encode() if url.endswith("SUMS") else data)
    app.ENGINE_DIR.mkdir(parents=True)
    (app.ENGINE_DIR / "yt-dlp-2020.1.1.zip").write_bytes(b"velho")
    (app.ENGINE_DIR / "yt-dlp-2019.1.1.zip").mkdir()
    assert api.update_engine() == {"ok": True, "version": "2027.1.2"}
    assert (app.ENGINE_DIR / "yt-dlp-2027.1.2.zip").exists() and not (app.ENGINE_DIR / "yt-dlp-2020.1.1.zip").exists()


def test_update_engine_failures(api, monkeypatch):
    data = engine_zip()
    monkeypatch.setattr(
        app, "http_get", lambda url, timeout=60: b"0" * 64 + b"  yt-dlp" if url.endswith("SUMS") else data
    )
    assert "não confere" in api.update_engine()["message"]
    monkeypatch.setattr(app, "http_get", lambda url, timeout=60: (_ for _ in ()).throw(OSError("offline")))
    assert "Não foi possível" in api.update_engine()["message"]


def test_update_app_paths(api, monkeypatch):
    assert "instalado" in api.update_app()["message"]
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app, "APP_VERSION", "1.0.0")
    monkeypatch.setattr(app, "github_latest", lambda repo: {"tag_name": "v1.0.0", "html_url": "u"})
    assert "mais recente" in api.update_app()["message"]
    monkeypatch.setattr(app, "github_latest", lambda repo: {"tag_name": "v2.0.0", "html_url": "u"})

    def install(release, exe, staging, progress, trusted_prefix=""):
        progress(0.1)
        progress(0.2)
        api._window.fail.add("run_js")
        progress(1.0)
        return "2.0.0"

    monkeypatch.setattr(app, "install_release", install)
    assert api.update_app() == {"ok": True, "version": "2.0.0"}
    monkeypatch.setattr(app, "install_release", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    assert api.update_app()["url"] == "u"
    monkeypatch.setattr(app, "install_release", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert "Não foi possível" in api.update_app()["message"]


def test_restart_skip_and_release(api, monkeypatch, instant_timer):
    launched, envs = [], []
    monkeypatch.setattr(app.subprocess, "Popen", lambda args, **k: (launched.append(args), envs.append(k["env"])))
    api._tray.icon = object()
    api._room = types.SimpleNamespace(active=True, close=lambda reason="": None)
    stopped = []
    monkeypatch.setattr(api._phone, "stop", lambda: stopped.append("phone"))
    monkeypatch.setattr(api._tray, "stop", lambda: stopped.append("tray"))
    api.restart_app()
    assert stopped == ["phone", "tray"] and api._room is None and api._on_closing() is True
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    api.restart_app()
    assert launched[0][-1].endswith("app.py") and launched[1] == [app.sys.executable]
    assert all(env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" for env in envs)
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in app.os.environ
    assert wait_until(lambda: api._window.calls.count("destroy") == 2)
    api.skip_update("engine", "2027.1.1")
    assert app.load_config()["skip_engine"] == "2027.1.1"
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    api.open_release("https://github.com/Kaique292/salvai/releases/tag/v2")
    api.open_release("https://evil.example/")
    assert opened == ["https://github.com/Kaique292/salvai/releases/tag/v2"]


def release_latest(repo):
    if repo == "yt-dlp/yt-dlp":
        return {"tag_name": "2099.1.1"}
    return {"tag_name": "v1.5.0", "html_url": "https://github.com/Kaique292/salvai/releases/tag/v1.5.0"}


def test_check_updates_on_every_open(api, monkeypatch, no_sleep):
    monkeypatch.setattr(app, "APP_VERSION", "1.0.0")
    asked = []
    monkeypatch.setattr(app, "github_latest", lambda repo: (asked.append(repo), release_latest(repo))[1])
    api._cfg["skip_app"] = "1.5.0"
    api._check_updates()
    assert sum("updateAvailable" in js for js in api._window.js) == 1
    api._window.js.clear()
    api._window.fail.add("run_js")
    api._check_updates()
    api._window.fail.discard("run_js")
    api._cfg.pop("skip_app")
    api._check_updates()
    assert sum("updateAvailable" in js for js in api._window.js) == 2
    assert asked == ["yt-dlp/yt-dlp", "Kaique292/salvai"] * 3


def test_check_updates_now_ignores_skip_and_reports_offline(api, monkeypatch):
    monkeypatch.setattr(app, "APP_VERSION", "1.0.0")
    monkeypatch.setattr(app, "github_latest", release_latest)
    api._cfg["skip_app"] = "1.5.0"
    assert api.check_updates_now() == {"found": 2, "offline": False}
    assert sum("updateAvailable" in js for js in api._window.js) == 2
    monkeypatch.setattr(app, "APP_VERSION", "9.0.0")
    monkeypatch.setattr(app, "github_latest", lambda repo: {"tag_name": "0.0.1", "html_url": "u"})
    assert api.check_updates_now() == {"found": 0, "offline": False}
    monkeypatch.setattr(app, "github_latest", lambda repo: (_ for _ in ()).throw(OSError()))
    assert api.check_updates_now() == {"found": 0, "offline": True}


def test_fetch_update_notices_survives_errors(api, monkeypatch):
    monkeypatch.setattr(app, "github_latest", lambda repo: (_ for _ in ()).throw(OSError()))
    assert api._fetch_update_notices() == ([], True)
    monkeypatch.setattr(app, "github_latest", lambda repo: {"tag_name": "0.0.1", "html_url": "u"})
    assert api._fetch_update_notices() == ([], False)


def test_paste_theme_and_shown(api, monkeypatch, instant_timer):
    monkeypatch.setattr(app, "read_clipboard", lambda: "https://x")
    assert api.paste() == "https://x"
    monkeypatch.setattr(app, "read_clipboard", lambda: (_ for _ in ()).throw(OSError()))
    assert api.paste() == ""
    styled = []
    monkeypatch.setattr(app, "style_titlebar", lambda hwnd, theme: styled.append((hwnd, theme)))
    monkeypatch.setattr(app, "find_own_window", lambda title: 77)
    api._on_shown()
    api.set_theme("light")
    assert wait_until(lambda: (77, "light") in styled) and app.load_config()["theme"] == "light"


def test_prepare_runtime(api, monkeypatch):
    monkeypatch.setattr(app, "ensure_js_runtime", lambda: (_ for _ in ()).throw(OSError()))
    api._prepare_runtime()


def test_ready_shows_window_once(api, monkeypatch, no_sleep):
    shown = []
    monkeypatch.setattr(app, "center_window", lambda hwnd: shown.append("center"))
    monkeypatch.setattr(app, "find_own_window", lambda title: 1)
    monkeypatch.setattr(api._tray, "start", lambda: (_ for _ in ()).throw(RuntimeError("sem bandeja")))
    monkeypatch.setattr(api, "_check_updates", lambda: shown.append("updates"))
    api.ready()
    api.ready()
    assert api._window.calls.count("show") == 1 and wait_until(lambda: "updates" in shown)


def test_gui_started_schedules_ready(api, monkeypatch):
    timers = []
    monkeypatch.setattr(
        app.threading, "Timer", lambda delay, fn: types.SimpleNamespace(start=lambda: timers.append(delay))
    )
    api._on_gui_started()
    assert timers == [15]


def test_notify_accounts_failure(api):
    api._window.fail.add("run_js")
    api._notify_accounts("x")


def test_closing_and_tray_flow(api, monkeypatch):
    assert api._downloads_label() == "Nenhum download em andamento"
    assert api._on_closing() is True
    api._tray.icon = object()
    assert api._on_closing() is True
    api._items = {"a": {"status": "queued"}}
    assert api._downloads_label() == "1 download em andamento"
    hidden = []
    monkeypatch.setattr(api, "_hide_to_tray", lambda busy: hidden.append(busy))
    assert api._on_closing() is False and wait_until(lambda: hidden == [1])
    api._items["b"] = {"status": "downloading"}
    assert api._downloads_label() == "2 downloads em andamento"
    api._quitting = True
    assert api._on_closing() is True
    api._items = {}
    api._tray.icon = None


def test_hide_show_toggle_quit(api, monkeypatch):
    notes = []
    monkeypatch.setattr(api._tray, "notify", lambda title, msg: notes.append(msg))
    monkeypatch.setattr(api._tray, "refresh", lambda: None)
    monkeypatch.setattr(api._phone, "start", lambda: setattr(api._phone, "server", object()))
    monkeypatch.setattr(api._phone, "stop", lambda: setattr(api._phone, "server", None))
    api._toggle_phone_from_tray()
    api._hide_to_tray(2)
    assert "2 downloads" in notes[-1] and "modo celular" in notes[-1] and api._hidden
    api._window.fail.add("run_js")
    api._toggle_phone_from_tray()
    api._phone_auto_off()
    api._window.fail.discard("run_js")
    api._phone_auto_off()
    api._hide_to_tray(1)
    assert "1 download" in notes[-1]
    api._phone.server = object()
    api._hide_to_tray(0)
    assert "em andamento" not in notes[-1] and "modo celular" in notes[-1]
    api._phone.server = None
    foreground = []
    monkeypatch.setattr(
        app.ctypes, "windll", types.SimpleNamespace(user32=types.SimpleNamespace(SetForegroundWindow=foreground.append))
    )
    monkeypatch.setattr(app, "find_own_window", lambda title: 55)
    api._show_from_tray()
    monkeypatch.setattr(app, "find_own_window", lambda title: 0)
    api._show_from_tray()
    assert foreground == [55] and not api._hidden
    api._quit()
    assert api._quitting and "destroy" in api._window.calls


def test_main_closed_destroys_login_windows(api):
    broken = FakeWindow()
    broken.fail.add("destroy")
    api._login_windows = {"a": FakeWindow(), "b": broken}
    api._on_main_closed()


def test_announce_and_push(api, monkeypatch):
    notes = []
    monkeypatch.setattr(api._tray, "notify", lambda title, msg: notes.append(title))
    api._announce({"status": "done", "url": "u", "fmt": "MP4"})
    api._hidden = True
    api._announce({"status": "done", "url": "u", "title": "T", "fmt": "MP4"})
    api._announce({"status": "error", "url": "u", "error": "x"})
    api._announce({"status": "paused", "url": "u"})
    assert notes == ["Salvo! ✓", "Não deu para baixar"]
    item = {"id": "p"}
    api._push(item)
    api._items["p"] = item
    api._window.fail.add("run_js")
    api._push(item)
    api._window = None
    api._push(item)


def test_status_and_report(api, tmp_path):
    app.save_sessions({"tiktok": {"cookies": [], "since": 1}})
    inside = Path(api._out_dir, "a.mp4")
    inside.write_bytes(b"x")
    api._items = {
        "a": {
            "id": "a",
            "url": "u",
            "title": "T",
            "fmt": "MP4",
            "quality": "Máxima",
            "status": "done",
            "progress": 1,
            "filepath": str(inside),
        },
        "b": {
            "id": "b",
            "url": "u",
            "title": None,
            "fmt": "MP3",
            "quality": "Máxima",
            "status": "queued",
            "progress": 0,
            "filepath": str(tmp_path / "fora.mp3"),
        },
    }
    api._order = ["a", "b"]
    status = api._status()
    assert status["queue"] == {"done": 1, "queued": 1} and status["connected_accounts"] == ["TikTok"]
    reports = [api._report(i) for i in api._ordered()]
    assert reports[0]["file"] == "a.mp4" and reports[1]["file"].endswith("fora.mp3")
    assert api._report(api._items["a"])["file"] == "a.mp4"


def test_phone_files_only_lists_what_salvai_saved(api, monkeypatch, tmp_path):
    base = Path(api._out_dir)
    (base / "Projeto").mkdir()
    (base / "Projeto" / "foto-pessoal.jpg").write_bytes(b"1")
    (base / "a").mkdir()
    (base / "musica.mp3").write_bytes(b"1")
    (base / "a" / "video.mp4").write_bytes(b"1" * 2_000_000)
    (base / "doc.pdf").write_bytes(b"1")
    outside = tmp_path / "outra-pasta" / "antigo.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"1")
    assert api._phone_files() == []
    for path in (outside, base / "doc.pdf", base / "a" / "video.mp4", base / "musica.mp3", base / "sumiu.mp4"):
        api._remember(str(path))
    files = api._scan_media()
    assert [f["name"] for f in files] == ["musica.mp3", "video.mp4", "antigo.mp4"]
    assert [f["folder"] for f in files] == ["", "a", "outra-pasta"]
    assert files[0]["kind"] == "audio" and files[1]["size_mb"] == 1.9
    assert files[0]["id"] == app.file_key(base / "musica.mp3")
    cached = api._phone_files()
    assert api._phone_files() is cached
    monkeypatch.setattr(app, "SAVED_LIMIT", 2)
    api._remember(str(base / "a" / "video.mp4"))
    assert api._saved == [str((base / "a" / "video.mp4").resolve()), str((base / "sumiu.mp4").resolve())]
    assert app.load_saved() == api._saved


def test_phone_files_stops_at_80(api):
    base = Path(api._out_dir)
    for n in range(82):
        (base / f"{n}.mp3").write_bytes(b"1")
        api._remember(str(base / f"{n}.mp3"))
    assert len(api._scan_media()) == 80


def test_load_saved_handles_bad_files(isolated):
    assert app.load_saved() == []
    app.SAVED_PATH.write_text("{ quebrado", encoding="utf-8")
    assert app.load_saved() == []
    app.SAVED_PATH.write_text('{"a": 1}', encoding="utf-8")
    assert app.load_saved() == []
    app.SAVED_PATH.write_text('["C:/a.mp4", 3, null]', encoding="utf-8")
    assert app.load_saved() == ["C:/a.mp4"]


def test_forget_clear_and_trash(api, monkeypatch):
    base = Path(api._out_dir)
    for name in ("a.mp4", "b.mp3", "c.mp4"):
        (base / name).write_bytes(b"1")
        api._remember(str(base / name))
    api._phone_files()
    assert api._forget(app.file_key(base / "a.mp4")) is True and api._files_cache is None
    assert api._forget("nao-existe") is False
    trashed = []
    monkeypatch.setattr(app, "send_to_trash", lambda path: (trashed.append(path), path.unlink()))
    assert api._trash(app.file_key(base / "b.mp3")) == "b.mp3"
    assert trashed == [(base / "b.mp3").resolve()] and not (base / "b.mp3").exists()
    assert [f["name"] for f in api._scan_media()] == ["c.mp4"]
    with pytest.raises(ValueError, match="não encontrado"):
        api._trash(app.file_key(base / "b.mp3"))
    (base / "c.mp4").unlink()
    with pytest.raises(ValueError):
        api._trash(app.file_key(base / "c.mp4"))
    api._clear_saved()
    assert api._saved == [] and app.load_saved() == []


def test_saved_file_ignores_other_extensions(api):
    base = Path(api._out_dir)
    (base / "x.pdf").write_bytes(b"1")
    api._remember(str(base / "x.pdf"))
    assert api._saved_file(app.file_key(base / "x.pdf")) is None


def test_send_to_trash_reports_failures(monkeypatch, tmp_path):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"1")
    calls = []

    def operation(code, aborted=False, delete=True):
        def run(ref):
            op = ref._obj
            calls.append((op.wFunc, op.pFrom, op.fFlags))
            op.fAnyOperationsAborted = aborted
            if delete and target.exists():
                target.unlink()
            return code

        return run

    def use(fn):
        monkeypatch.setattr(
            app.ctypes, "windll", types.SimpleNamespace(shell32=types.SimpleNamespace(SHFileOperationW=fn))
        )

    use(operation(0))
    app.send_to_trash(target)
    assert calls[0] == (3, str(target), 0x0454) and not target.exists()
    target.write_bytes(b"1")
    use(operation(2, delete=False))
    with pytest.raises(OSError, match="Lixeira"):
        app.send_to_trash(target)
    use(operation(0, aborted=True, delete=False))
    with pytest.raises(OSError):
        app.send_to_trash(target)
    use(operation(0, delete=False))
    with pytest.raises(OSError):
        app.send_to_trash(target)


def test_phone_controls_and_firewall(api, monkeypatch):
    monkeypatch.setattr(
        app, "home_network", lambda: {"ipv4": ["127.0.0.1"], "ipv6": [], "v4_networks": [], "v6_networks": []}
    )
    assert api.phone_status() == {"on": False}
    assert api.phone_start()["on"] is True
    assert api.phone_stop() == {"on": False}
    calls = []
    shell = types.SimpleNamespace(ShellExecuteW=lambda *a: calls.append(a) or 42)
    monkeypatch.setattr(app.ctypes, "windll", types.SimpleNamespace(shell32=shell))
    assert api.phone_allow_firewall() is True and "localport=47800" in calls[0][3]
    api._phone.server = types.SimpleNamespace(server_address=("::", 5555))
    api.phone_allow_firewall()
    assert "localport=5555" in calls[1][3]
    api._phone.server = None
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    api.open_network_settings()
    api._phone.network = {"kind": "wifi"}
    api.open_network_settings()
    assert opened == ["ms-settings:network-ethernet", "ms-settings:network-wifi"]


def test_search(api):
    entries = [
        {"ie_key": "Youtube", "id": "abc", "title": "A", "channel": "C", "duration": 10, "view_count": 5},
        {"url": "https://soundcloud.com/x", "title": "B", "uploader": "U"},
    ]
    FakeYDL.script = {"ytsearch": {"info": {"entries": entries}}, "scsearch": {"info": {}}}
    result = api._search("aula", limit=50)
    assert result["results"][0]["url"].endswith("watch?v=abc") and result["results"][1]["channel"] == "U"
    assert FakeYDL.created[-1].opts["extract_flat"] == "in_playlist"
    assert api._search("lofi", site="soundcloud")["results"] == []


def test_files_listing(api, monkeypatch):
    base = Path(api._out_dir)
    (base / "Pasta" / "Sub").mkdir(parents=True)
    (base / "Pasta" / "a.mp4").write_bytes(b"x" * 2048)
    (base / "Pasta" / "Sub" / "b.mp4.part").write_bytes(b"x")
    result = api._files("Pasta", depth=0)
    assert result["folder"] == "Pasta" and [f["path"] for f in result["files"]] == ["Pasta\\a.mp4"]
    assert api._files("Pasta", depth=9)["files"][1]["incomplete"]
    assert api._files("NaoExiste")["files"] == []
    assert api._files()["folder"] == ""
    for n in range(405):
        (base / f"f{n:03}.txt").write_bytes(b"")
    assert api._files(depth=0)["truncated"]
    real_stat = Path.stat
    monkeypatch.setattr(
        Path,
        "stat",
        lambda self, **k: (_ for _ in ()).throw(OSError()) if self.name == "f000.txt" else real_stat(self, **k),
    )
    assert "f000.txt" not in [f["path"] for f in api._files(depth=0)["files"]]


def test_move_file(api):
    base = Path(api._out_dir)
    (base / "a.mp3").write_bytes(b"1")
    (base / "Org").mkdir()
    (base / "Org" / "a.mp3").write_bytes(b"0")
    api._items = {"x": {"filepath": str(base / "a.mp3")}, "y": {"filepath": None}}
    api._remember(str(base / "a.mp3"))
    assert api._move("a.mp3", "Org") == {"moved_to": "Org\\a (2).mp3"}
    assert api._items["x"]["filepath"].endswith("a (2).mp3")
    assert api._saved == [str((base / "Org" / "a (2).mp3").resolve())]
    (base / "c.mp3").write_bytes(b"1")
    (base / "Org" / "c.mp3").write_bytes(b"1")
    (base / "Org" / "c (2).mp3").write_bytes(b"1")
    assert api._move("c.mp3", "Org") == {"moved_to": "Org\\c (3).mp3"}
    with pytest.raises(ValueError):
        api._move("../../fora.txt", "")


def test_add_items(api, monkeypatch):
    monkeypatch.setattr(api, "_meta_pool", types.SimpleNamespace(submit=lambda *a: None))
    with api._cv:
        count = api.add_items(
            [
                {"url": "https://exemplo.org/a", "fmt": "MP3", "quality": "128 kbps"},
                {"url": "nada", "fmt": "MP4", "quality": "Máxima"},
            ]
        )
        assert count == 1
        api._items.clear()
        api._order.clear()


def test_clear_storage_skips_files_named_like_cache(api):
    (app.WEBVIEW_DIR / "Default").mkdir(parents=True)
    (app.WEBVIEW_DIR / "Default" / "Cache").write_bytes(b"arquivo")
    result = api.clear_storage(["webview"])
    assert (app.WEBVIEW_DIR / "Default" / "Cache").exists() and app.WEBVIEW_CLEAR_FLAG.exists()
    assert result["freed"] == 0


def test_setup_mcp_registers_once_and_notifies(api, monkeypatch, tmp_path):
    exe = tmp_path / "Salvai.exe"
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.sys, "executable", str(exe))
    ensured, registered = [], []
    monkeypatch.setattr(app, "ensure_mcp", lambda: ensured.append(1))
    monkeypatch.setattr(app, "register_claude", lambda done: (registered.append(list(done)), ["C:/claude.json"])[1])
    api._setup_mcp()
    assert api._cfg["app_path"] == str(exe) and api._cfg["claude_registered"] == ["C:/claude.json"]
    assert app.load_config()["claude_registered"] == ["C:/claude.json"]
    assert any('"kind": "claude"' in js for js in api._window.js)
    monkeypatch.setattr(app, "register_claude", lambda done: [])
    api._window.js.clear()
    api._setup_mcp()
    assert ensured == [1, 1] and api._window.js == []
    monkeypatch.setattr(app, "register_claude", lambda done: ["C:/outro.json"])
    api._window.fail.add("run_js")
    api._setup_mcp()
    assert api._cfg["claude_registered"] == ["C:/claude.json", "C:/outro.json"]


def test_setup_mcp_skips_when_not_installed_or_offline(api, monkeypatch):
    called = []
    monkeypatch.setattr(app, "register_claude", lambda done: called.append(1) or [])
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)
    api._setup_mcp()
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app, "ensure_mcp", lambda: (_ for _ in ()).throw(OSError("sem internet")))
    api._cfg["app_path"] = app.sys.executable
    api._setup_mcp()
    assert called == [] and "claude_registered" not in api._cfg


def test_whatsapp_message_mentions_the_network():
    url = "http://192.168.0.2:47800/?k=abc"
    wifi = app.whatsapp_message(url, {"kind": "wifi", "name": "Casa 5G"})
    assert url in wifi and "Wi-Fi *Casa 5G*" in wifi and wifi.startswith("📲 *Salvaí no celular*")
    assert "mesmo roteador" in app.whatsapp_message(url, {"kind": "cabo"})
    assert "mesmo Wi-Fi do computador" in app.whatsapp_message(url, {"kind": "wifi"})
    assert "mesmo Wi-Fi do computador" in app.whatsapp_message(url, {})


def test_whatsapp_installed(monkeypatch):
    closed = []
    fake = types.SimpleNamespace(
        HKEY_CLASSES_ROOT="HKCR", OpenKey=lambda root, name: (root, name), CloseKey=closed.append
    )
    monkeypatch.setattr(app, "winreg", fake)
    assert app.whatsapp_installed() is True and closed == [("HKCR", "whatsapp")]
    fake.OpenKey = lambda root, name: (_ for _ in ()).throw(FileNotFoundError())
    assert app.whatsapp_installed() is False


def test_share_whatsapp(api, monkeypatch):
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(api._phone, "status", lambda: {"on": False})
    assert api.share_whatsapp() == {"ok": False} and opened == []
    monkeypatch.setattr(api._phone, "status", lambda: {"on": True, "url": "http://10.0.0.2:47800/?k=x"})
    api._phone.network = {"kind": "wifi", "name": "Casa & Cia"}
    monkeypatch.setattr(app, "whatsapp_installed", lambda: True)
    assert api.share_whatsapp() == {"ok": True, "app": "desktop"}
    assert opened[-1].startswith("whatsapp://send?text=") and "Casa%20%26%20Cia" in opened[-1]
    monkeypatch.setattr(app, "whatsapp_installed", lambda: False)
    api._phone.network = None
    assert api.share_whatsapp() == {"ok": True, "app": "web"}
    assert opened[-1].startswith("https://web.whatsapp.com/send?text=")
    assert app.urllib.parse.quote("http://10.0.0.2:47800/?k=x") in opened[-1]


def test_release_notes_between_versions(api, monkeypatch):
    monkeypatch.setattr(app, "APP_VERSION", "1.2.0")
    releases = [
        {"tag_name": "v1.2.1", "published_at": "2026-10-18T22:46:12Z", "body": "### 🐛 Correções\n\n* corrige"},
        {"tag_name": "v1.3.0", "published_at": None, "body": None},
        {"tag_name": "v1.2.0", "body": "### ✨ Novidades\n* antiga"},
        {"tag_name": "v1.4.0", "draft": True, "body": ""},
        {"tag_name": "v1.5.0-beta", "prerelease": True, "body": ""},
    ]
    asked = []
    monkeypatch.setattr(app, "http_get", lambda url, timeout=60: (asked.append(url), json.dumps(releases).encode())[1])
    result = api.release_notes()
    assert asked == ["https://api.github.com/repos/Kaique292/salvai/releases?per_page=30"]
    assert result["ok"] and result["current"] == "1.2.0" and result["url"].endswith("/salvai/releases")
    assert [r["version"] for r in result["releases"]] == ["1.3.0", "1.2.1"]
    assert result["releases"][0] == {"version": "1.3.0", "date": "", "sections": []}
    assert result["releases"][1]["date"] == "2026-10-18"
    assert result["releases"][1]["sections"] == [{"title": "🐛 Correções", "items": ["Corrige"]}]
    monkeypatch.setattr(app, "http_get", lambda url, timeout=60: (_ for _ in ()).throw(OSError()))
    assert api.release_notes() == {"ok": False, "url": "https://github.com/Kaique292/salvai/releases"}
