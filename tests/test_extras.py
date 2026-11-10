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


def feed(ctrl, rtts, start: datetime | None = None, server=None):
    server = server or ctrl.settings.servers[0]
    start = start or datetime.now() - timedelta(seconds=len(rtts))
    for offset, rtt in enumerate(rtts):
        status = PingStatus.TIMEOUT if rtt is None else PingStatus.OK
        ctrl._on_result(PingResult(server.name, server.host, start + timedelta(seconds=offset), status, rtt))


def no_waiting(ctrl) -> None:
    """Announce right away (the timing rules are tested in test_alerts.py)."""
    from src.core.alerts import HealthAlerts

    ctrl._alerts = HealthAlerts(alert_gap_s=0, recovery_hold_s=0)


def test_notifications_on_failing_and_recovery(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda title, message, warning=False: sent.append(title))
    no_waiting(controller)
    feed(controller, [20, 20])
    assert sent == []
    feed(controller, [None, None, None])
    assert sent == ["cloudflare.com is failing"]
    feed(controller, [None])
    assert len(sent) == 1  # still failing: no repeat
    feed(controller, [20, 20], start=datetime.now() + timedelta(minutes=6))  # the losses aged out
    assert sent[-1] == "cloudflare.com is healthy again"


def test_no_failing_alert_right_after_start(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda *args, **kwargs: sent.append(args))
    feed(controller, [None, None, None])  # e.g. Wi-Fi still connecting after sign-in
    assert sent == []


def test_notifications_can_be_turned_off_without_stray_messages_later(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda title, *args, **kwargs: sent.append(title))
    no_waiting(controller)
    controller.apply_settings(controller.settings.with_changes(notifications=False))
    no_waiting(controller)  # settings changes start a short quiet period
    feed(controller, [None, None, None])
    feed(controller, [20, 20], start=datetime.now() + timedelta(minutes=6))  # recovered silently
    controller.apply_settings(controller.settings.with_changes(notifications=True))
    feed(controller, [20], start=datetime.now() + timedelta(minutes=7))
    assert sent == []


def test_another_tray_server_starts_without_an_incident(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda title, *args, **kwargs: sent.append(title))
    no_waiting(controller)
    feed(controller, [None, None, None])
    assert sent == ["cloudflare.com is failing"]
    servers = controller.settings.servers
    controller.apply_settings(controller.settings.with_changes(servers=(servers[1], servers[0], *servers[2:])))
    no_waiting(controller)
    feed(controller, [20, 20], server=controller.settings.servers[0])
    assert sent == ["cloudflare.com is failing"]  # no "google.com is healthy again"


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


def test_background_picture_is_sharp_and_released(qapp, controller):
    window = controller.window
    root = window._root
    controller.apply_settings(controller.settings.with_changes(background_image=True))
    window.show()
    window.resize(1100, 700)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        qapp.processEvents()
    target, scaled = root._target_size(), root._scaled.size()  # covers the window, aspect kept
    assert scaled.width() >= target.width() and scaled.height() >= target.height()
    assert target.width() in (scaled.width(), 0) or target.height() == scaled.height()
    controller.apply_settings(controller.settings.with_changes(background_image=False))
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and root._image is not None:
        qapp.processEvents()
    assert root._image is None and root._scaled is None


def test_hand_edited_window_state_never_stops_the_start(qapp, controller, tmp_path):
    (tmp_path / "ui_state.json").write_text('{"geometry": "Matěj", "tab": 5}', encoding="utf-8")
    from src.app import AppController

    second = AppController(qapp, start_hidden=True)
    second.quit()


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}

    def read(self, path, name):
        return self.values.get((path, name))

    def write_string(self, path, name, value):
        self.values[(path, name)] = value

    def delete(self, path, name):
        self.values.pop((path, name), None)


def test_autostart_follows_windows_startup_settings(monkeypatch):
    fake = FakeRegistry()
    monkeypatch.setattr(autostart, "registry", fake)
    monkeypatch.setattr(autostart, "is_supported", lambda: True)
    run = (autostart.RUN_KEY, autostart.VALUE_NAME)
    approved = (autostart.APPROVED_KEY, autostart.VALUE_NAME)

    autostart.set_enabled(True)
    assert fake.values[run] == autostart.launch_command() and autostart.is_enabled()
    fake.values[approved] = bytes([3, 0, 0, 0]) + bytes(8)  # "Disabled" in Task Manager
    assert not autostart.is_enabled()
    autostart.set_enabled(True)  # turning it on in the app really turns it on again
    assert approved not in fake.values and autostart.is_enabled()

    fake.values[run] = '"C:\\old place\\pythonw.exe" "C:\\old place\\main.py" --minimized'
    autostart.refresh()  # the folder moved: the entry is repaired
    assert fake.values[run] == autostart.launch_command()

    import sys
    working = f'"{sys.executable}" "{__file__}" --minimized'
    fake.values[run] = working  # another copy that still works is not taken over
    autostart.refresh()
    assert fake.values[run] == working

    autostart.set_enabled(False)
    assert run not in fake.values and not autostart.is_enabled()
    autostart.refresh()
    assert run not in fake.values


def test_only_waking_from_sleep_delays_alerts(controller, monkeypatch):
    sent = []
    monkeypatch.setattr(controller.tray, "notify", lambda title, *args, **kwargs: sent.append(title))
    no_waiting(controller)
    server = controller.settings.servers[0]
    now = datetime.now()
    for offset in range(3):  # an outage where every ping call hangs: slow-call gaps
        controller._on_result(PingResult(server.name, server.host, now + timedelta(seconds=3 * offset),
                                         PingStatus.GAP, gap_seconds=2, detail="slow-call"))
        controller._on_result(PingResult(server.name, server.host, now + timedelta(seconds=3 * offset + 2),
                                         PingStatus.TIMEOUT))
    assert sent == ["cloudflare.com is failing"]

    no_waiting(controller)
    controller.reset_server(server.name)
    later = now + timedelta(minutes=10)
    controller._on_result(PingResult(server.name, server.host, later, PingStatus.GAP, gap_seconds=3600,
                                     detail="system"))  # the PC slept for an hour
    feed(controller, [None, None, None], start=later + timedelta(seconds=1))  # Wi-Fi reconnecting
    assert sent == ["cloudflare.com is failing"]
