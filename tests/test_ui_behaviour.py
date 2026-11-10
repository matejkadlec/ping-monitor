"""Behaviour of the stream, scrollbar, animations and window (offscreen Qt)."""

import os
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core.models import PingResult, PingStatus  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from src.ui.theme import THEME

    THEME.load_fonts()
    return app


@pytest.fixture
def motion():
    from src.ui.theme import THEME

    previous = THEME.motion, THEME.ambient
    THEME.set_motion(True)
    THEME.set_ambient_motion(True)
    yield
    THEME.set_motion(previous[0])
    THEME.set_ambient_motion(previous[1])


def pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def results(count: int, start: datetime | None = None) -> list[PingResult]:
    start = start or datetime.now() - timedelta(seconds=count)
    return [PingResult("s", "h", start + timedelta(seconds=i), PingStatus.OK, 20 + i % 7) for i in range(count)]


def test_fresh_highlights_expire_even_if_never_painted(monkeypatch):
    from src.ui import ping_stream

    model = ping_stream.PingStreamModel()
    for result in results(3):
        model.append(result)
    assert model.prune_fresh() == 3
    later = time.monotonic() + ping_stream.FRESH_MS / 1000 + 0.1
    monkeypatch.setattr(ping_stream, "time", SimpleNamespace(monotonic=lambda: later))
    assert model.prune_fresh() == 0
    assert not model.has_fresh_rows()


def test_fresh_timer_stops_after_rows_added_while_hidden(qapp, motion):
    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(600, 300)
    stream.show()
    stream.hide()
    for result in results(100):
        stream.model.append(result)  # most of these are never painted
    stream.show()
    stream.model.append(results(1, datetime.now())[0])
    assert stream.view._fresh_timer.isActive()
    pump(qapp, 1.3)
    assert not stream.view._fresh_timer.isActive()
    stream.deleteLater()


def test_evicted_current_row_does_not_scroll_to_the_top(qapp, motion):
    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(600, 300)
    stream.show()
    stream.model.reset_rows(results(200))
    pump(qapp, 0.2)
    view = stream.view
    view.setCurrentIndex(stream.model.index(5))  # the user clicked a row ...
    view.scroll_to_latest_instantly()  # ... and went back to the newest ping
    pump(qapp, 0.2)
    stream.hide()  # e.g. another tab or the tray
    for result in results(10, datetime.now()):
        stream.model.append(result, evicted=1)  # the clicked row drops off
    stream.show()
    pump(qapp, 0.3)
    bar = view.verticalScrollBar()
    assert view.following
    assert bar.value() == bar.maximum() > 0
    stream.deleteLater()


def test_glide_starts_from_the_current_value(qapp, motion):
    from src.ui.scrollbar import SmoothScrollBar

    bar = SmoothScrollBar()
    bar.setRange(0, 10000)
    bar.setPageStep(100)
    bar.show()
    bar.glide_to(8000, 100)
    pump(qapp, 0.3)
    assert bar.value() == 8000
    bar.setValue(3000)  # e.g. the user dragged the handle
    bar.glide_to(3100, 300)
    assert bar.value() == 3000  # no jump to a stale interpolated value
    pump(qapp, 0.5)
    assert bar.value() == 3100
    bar.deleteLater()


def test_scrollbar_fades_in_only_when_there_is_something_to_scroll(qapp, motion):
    from src.ui.scrollbar import SmoothScrollBar

    bar = SmoothScrollBar()
    bar.setRange(0, 0)
    bar.show()
    pump(qapp, 0.1)
    assert bar._presence.value == 0.0
    bar.setRange(0, 500)
    pump(qapp, 0.5)
    assert bar._presence.value == pytest.approx(1.0)
    bar.deleteLater()


def test_retargeted_tween_continues_from_its_value(qapp, motion):
    from src.ui.controls import Tween

    owner = QObject()
    tween = Tween(owner, lambda: None, duration=100)
    tween.to(1.0)
    pump(qapp, 0.3)
    assert tween.value == pytest.approx(1.0)
    tween.to(0.0, duration=300)  # a different duration re-interpolates the old curve
    assert tween.value == pytest.approx(1.0)
    pump(qapp, 0.5)
    assert tween.value == pytest.approx(0.0)


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PING_MONITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PING_MONITOR_SIMULATE", "1")
    from src.app import AppController

    ctrl = AppController(qapp, start_hidden=True)
    yield ctrl
    ctrl.quit()


def test_bring_to_front_keeps_the_window_maximized(qapp, controller):
    window = controller.window
    window.setWindowState(Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized)
    window.bring_to_front()
    state = window.windowState()
    assert state & Qt.WindowState.WindowMaximized
    assert not state & Qt.WindowState.WindowMinimized


def test_default_window_size_fits_the_screen(qapp, controller):
    area = qapp.primaryScreen().availableGeometry()
    window = controller.window
    assert window.width() <= max(area.width(), window.minimumWidth())
    assert window.height() <= max(area.height(), window.minimumHeight())


def test_toggling_close_to_tray_keeps_the_streams(qapp, controller, monkeypatch):
    calls = []
    monkeypatch.setattr(controller.window, "reload_all", lambda: calls.append(1))
    controller.set_close_to_tray(not controller.settings.close_to_tray)
    assert calls == []
    controller.apply_settings(controller.settings.with_changes(ping_threshold_healthy=35))
    assert calls == [1]
