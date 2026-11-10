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


def test_stream_stays_fast_with_long_histories(qapp):
    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(900, 600)
    stream.show()
    stream.model.reset_rows(results(100_000))
    pump(qapp, 0.1)
    timings = []
    for result in results(9, datetime.now()):
        started = time.perf_counter()
        stream.model.append(result, evicted=1)  # what every ping does once the window is full
        qapp.processEvents()
        timings.append(time.perf_counter() - started)
    assert sorted(timings)[4] < 0.04  # QListView needed ~0.13 s here
    stream.deleteLater()


def test_row_height_follows_the_ui_scale(qapp):
    from src.ui.ping_stream import PingStream
    from src.ui.theme import THEME

    stream = PingStream()
    stream.model.reset_rows(results(10))
    try:
        THEME.set_scale(1.2)
        assert stream.view.verticalHeader().defaultSectionSize() == THEME.px(26)
    finally:
        THEME.set_scale(1.0)
    assert stream.view.verticalHeader().defaultSectionSize() == THEME.px(26)
    stream.deleteLater()


def test_fresh_entries_are_pruned_while_hidden(monkeypatch):
    from src.ui import ping_stream

    model = ping_stream.PingStreamModel()
    for result in results(50):
        model.append(result)
    later = time.monotonic() + 5
    monkeypatch.setattr(ping_stream, "time", SimpleNamespace(monotonic=lambda: later))
    model.append(results(1, datetime.now())[0])
    assert len(model._fresh) == 1


def test_paused_badge_follows_the_state_on_hidden_tabs(qapp, controller):
    window = controller.window
    window.show()
    names = controller.settings.server_names()
    hidden = window.page(names[1])
    controller.set_paused(True)
    controller.set_paused(False)
    window.tabs.set_current(1)
    pump(qapp, 0.6)
    assert not hidden._paused_state
    assert not hidden._paused.isVisible()


def test_dropped_rows_do_not_cut_a_glide_short(qapp, motion):
    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(600, 300)
    stream.show()
    stream.model.reset_rows(results(300))
    pump(qapp, 0.5)  # the view glides to the newest row first
    view = stream.view
    bar = view.verticalScrollBar()
    bar.stop_glide()
    bar.setValue(1000)  # reading older pings (not following)
    pump(qapp, 0.05)
    assert not view.following
    bar.glide_to(1600, 300)
    pump(qapp, 0.05)
    stream.model.append(results(1, datetime.now())[0], evicted=1)  # the oldest row drops off
    pump(qapp, 0.5)
    assert bar.value() == 1600 - view._delegate.row_height()
    stream.deleteLater()


def test_arrow_clicks_update_following_right_away(qapp, motion):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(600, 300)
    stream.show()
    stream.model.reset_rows(results(200))
    pump(qapp, 0.5)
    view = stream.view
    bar = view.verticalScrollBar()

    def click(y: float) -> None:
        point = QPointF(bar.width() / 2, y)
        bar.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, point, point,
                                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                        Qt.KeyboardModifier.NoModifier))

    assert view.following
    click(2)  # the up arrow: glide to the oldest row
    assert not view.following
    stream.model.append(results(1, datetime.now())[0])  # a ping during the glide
    pump(qapp, 0.6)
    assert bar.value() == 0 and not view.following
    click(bar.height() - 2)  # the down arrow: back to the newest row
    assert view.following
    pump(qapp, 0.6)
    assert bar.value() == bar.maximum()
    stream.deleteLater()


def test_home_glides_to_the_oldest_ping(qapp, motion):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(600, 300)
    stream.show()
    stream.model.reset_rows(results(200))
    pump(qapp, 0.5)
    view = stream.view
    view.setCurrentIndex(stream.model.index(150, 0))  # a clicked row
    view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier))
    pump(qapp, 0.6)
    assert view.verticalScrollBar().value() == 0 and not view.following
    stream.deleteLater()


def test_shift_home_is_left_to_the_selection_handling(qapp, motion):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from src.ui.ping_stream import PingStream

    stream = PingStream()
    stream.resize(600, 300)
    stream.show()
    stream.model.reset_rows(results(50))
    pump(qapp, 0.3)
    view = stream.view
    view.setCurrentIndex(stream.model.index(40, 0))
    view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Home, Qt.KeyboardModifier.ShiftModifier))
    assert view.currentIndex().row() == 0  # Qt's own Shift+Home, not the plain Home glide
    stream.deleteLater()
