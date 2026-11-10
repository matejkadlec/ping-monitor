"""Extra features: notifications, background picture, window state, autostart command."""

import os
import time
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core import autostart  # noqa: E402
from src.core.models import PingResult, PingStatus  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from src.ui.theme import THEME

    THEME.load_fonts()
    return app


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PING_MONITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PING_MONITOR_SIMULATE", "1")
    from src.app import AppController

    ctrl = AppController(qapp, start_hidden=True)
    ctrl.engine.stop()  # only injected results from here on
    yield ctrl
    ctrl.quit()


def feed(ctrl, rtts):
    server = ctrl.settings.servers[0]
    start = datetime.now() - timedelta(seconds=len(rtts))
    for offset, rtt in enumerate(rtts):
        status = PingStatus.TIMEOUT if rtt is None else PingStatus.OK
        ctrl._on_result(PingResult(server.name, server.host, start + timedelta(seconds=offset), status, rtt))


def test_notifications_on_failing_and_recovery(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda title, message, warning=False: sent.append(title))
    feed(controller, [20, 20])
    assert sent == []
    feed(controller, [None, None, None])
    assert sent == ["cloudflare.com is failing"]
    feed(controller, [None])
    assert len(sent) == 1  # still failing: no repeat
    controller.reset_server("cloudflare.com")  # e.g. the spikes aged out
    feed(controller, [20])
    assert sent[-1] == "cloudflare.com is healthy again"


def test_notifications_can_be_turned_off(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda *args, **kwargs: sent.append(args))
    controller.apply_settings(controller.settings.with_changes(notifications=False))
    feed(controller, [None, None, None])
    assert sent == []


def test_background_picture_toggle(qapp, controller):
    root = controller.window._root
    controller.apply_settings(controller.settings.with_changes(background_image=True))
    assert root._image is not None
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and root._image_opacity.value < 1.0:
        qapp.processEvents()
    assert root._image_opacity.value == pytest.approx(1.0)


def test_window_state_roundtrip(qapp, controller, tmp_path):
    controller.window.resize(1000, 700)
    controller.window.tabs.set_current(1)
    controller._save_ui_state()
    assert (tmp_path / "ui_state.json").exists()
    from src.app import AppController

    second = AppController(qapp, start_hidden=True)
    try:
        assert second.window.current_server() == "google.com"
    finally:
        second.quit()


def test_autostart_command_points_at_the_app():
    command = autostart.launch_command()
    assert command.endswith(autostart.MINIMIZED_FLAG)
    assert "main.py" in command
    if not autostart.is_supported():
        assert autostart.is_enabled() is False
        autostart.set_enabled(True)  # no-op elsewhere
