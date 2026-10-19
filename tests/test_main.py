import types

import pytest
from conftest import FakeWindow

import app


class Exited(Exception):
    pass


@pytest.fixture
def launch(monkeypatch, isolated, fake_engine):
    monkeypatch.setattr(app, "ffmpeg_dir", lambda: "ffmpeg")
    monkeypatch.setattr(app, "ensure_js_runtime", lambda: {"node": {}})
    monkeypatch.setattr(app, "cleanup_leftovers", lambda: 0)
    windows, started = [], []

    def create_window(*args, **kwargs):
        window = FakeWindow()
        window.kwargs = kwargs
        windows.append(window)
        return window

    monkeypatch.setattr(app.webview, "create_window", create_window)
    monkeypatch.setattr(app.webview, "start", lambda func, **kwargs: started.append(kwargs))
    monkeypatch.setattr(app.os, "_exit", lambda code: (_ for _ in ()).throw(Exited(code)))
    monkeypatch.setattr(app.sys, "argv", ["Salvai.exe"])
    return types.SimpleNamespace(windows=windows, started=started)


def test_main_opens_window_and_exits_cleanly(launch, monkeypatch):
    app.WEBVIEW_DIR.mkdir(parents=True)
    (app.WEBVIEW_DIR / "x").write_text("1")
    app.WEBVIEW_CLEAR_FLAG.write_text("")
    with pytest.raises(Exited):
        app.main()
    window = launch.windows[0]
    assert window.kwargs["hidden"] and window.kwargs["background_color"] == "#0E0E11"
    assert len(window.events.closing.handlers) == 1 and len(window.events.closed.handlers) == 2
    assert window.events.loaded.handlers[0].__func__ is app.Api._on_loaded
    assert launch.started[0]["storage_path"] == str(app.WEBVIEW_DIR)
    assert not app.WEBVIEW_DIR.exists() and not app.WEBVIEW_CLEAR_FLAG.exists()
    assert not app.BRIDGE_PATH.exists()


def test_main_light_theme_and_bridge_failure(launch, monkeypatch):
    app.save_config({"theme": "light"})
    monkeypatch.setattr(app.Bridge, "start", lambda self: (_ for _ in ()).throw(OSError("porta")))
    with pytest.raises(Exited):
        app.main()
    window = launch.windows[0]
    assert window.kwargs["background_color"] == "#F4F4F6" and len(window.events.closed.handlers) == 1


def test_main_selftest_mode(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(app.sys, "argv", ["Salvai.exe", "--selftest", str(tmp_path)])
    monkeypatch.setattr(app, "selftest", lambda out: ran.append(out))
    monkeypatch.setattr(app, "pyi_splash", None)
    app.main()
    assert ran == [str(tmp_path)]


def test_main_relaunches_cleanly_over_stale_bundle(launch, monkeypatch):
    started = []
    monkeypatch.setattr(app, "stale_bundle", lambda: True)
    monkeypatch.setattr(app, "pyi_splash", None)
    monkeypatch.setattr(app.sys, "argv", ["Salvai.exe", "--debug"])
    monkeypatch.setattr(app.subprocess, "Popen", lambda args, **k: started.append((args, k["env"])))
    app.main()
    assert started[0][0] == [app.sys.executable, "--debug"]
    assert started[0][1]["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and launch.windows == []
