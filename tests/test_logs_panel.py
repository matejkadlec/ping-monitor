"""Logs overlay behaviour (offscreen Qt, simulated pings)."""

import os
import time
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core.models import PingResult, PingStatus  # noqa: E402
from src.core.spike_log import SessionMarker, SpikeEntry, SpikeLog  # noqa: E402
from src.ui.logs_panel import ITEM_ROLE, EarlierEntries, LogModel, LogsPanel, MoreInFile, _LogList  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from src.ui.theme import THEME

    THEME.load_fonts()
    return app


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_model_shows_sessions_newest_first(qapp):
    t = datetime(2026, 11, 10, 10, 0, 0)
    old_session, new_session = SessionMarker(t), SessionMarker(t + timedelta(hours=2))
    items = [
        old_session,
        SpikeEntry(t + timedelta(minutes=1), "a.com", "spike", 70),
        SpikeEntry(t + timedelta(minutes=2), "a.com", "timeout"),
        new_session,
        SpikeEntry(t + timedelta(hours=2, minutes=1), "b.com", "spike", 90),
    ]
    model = LogModel(headers=True)
    model.set_items(items)
    rows = [model.data(model.index(row), ITEM_ROLE) for row in range(model.rowCount())]
    assert rows[0] == new_session and rows[1].server == "b.com"
    assert rows[2] == old_session and rows[3].kind == "timeout" and rows[4].rtt_ms == 70
    assert model.session_count(old_session) == (2, False) and model.session_count(new_session) == (1, False)


def test_model_keeps_file_order_and_labels_legacy_entries(qapp):
    t = datetime(2026, 10, 25, 2, 30, 0)  # DST fall-back: 02:xx happens twice
    legacy = [SpikeEntry(t, "old.com", "spike", 80), SpikeEntry(t, "old.com", "timeout")]
    marker = SessionMarker(t)
    later_hour = [SpikeEntry(t + timedelta(minutes=50), "a.com", "spike", 70),
                  SpikeEntry(t - timedelta(minutes=10), "a.com", "spike", 75)]  # clock went back
    model = LogModel(headers=True)
    model.set_items([*legacy, marker, *later_hour])
    rows = [model.data(model.index(row), ITEM_ROLE) for row in range(model.rowCount())]
    assert rows[0] == marker and rows[1].rtt_ms == 75 and rows[2].rtt_ms == 70  # newest = last written
    assert isinstance(rows[3], EarlierEntries) and model.session_count(rows[3]) == (2, False)
    assert rows[4].kind == "timeout" and rows[5].kind == "spike"


def test_model_keeps_only_the_newest_entries(qapp):
    model = LogModel(headers=False, limit=3, overflow_text="older entries are in the file")
    start = datetime(2026, 11, 10, 12, 0, 0)
    model.set_items([SpikeEntry(start, "a.com", "spike", 61)])
    for offset in range(1, 6):
        model.prepend(SpikeEntry(start + timedelta(seconds=offset), "a.com", "spike", 61 + offset))
    rows = [model.data(model.index(row), ITEM_ROLE) for row in range(model.rowCount())]
    assert model.entry_count() == 3
    assert [row.rtt_ms for row in rows[:3]] == [66, 65, 64]
    assert isinstance(rows[3], MoreInFile) and len(rows) == 4


def entries(count: int) -> list[SpikeEntry]:
    start = datetime.now() - timedelta(seconds=count)
    return [SpikeEntry(start + timedelta(seconds=i), "a.com", "spike", 60 + i % 40) for i in range(count)]


def test_new_entries_keep_the_reading_position(qapp):
    from src.ui.theme import THEME

    THEME.set_motion(True)
    view = _LogList(False, "empty", headers=False)
    view.resize(500, 300)
    view.show()
    view.model_.set_items(entries(200))
    pump(qapp, 0.2)
    bar = view.verticalScrollBar()
    bar.setValue(400)
    pump(qapp, 0.1)
    top = view.indexAt(view.viewport().rect().topLeft()).data(ITEM_ROLE)
    for entry in entries(5):
        view.model_.prepend(entry)
    pump(qapp, 0.1)
    assert view.indexAt(view.viewport().rect().topLeft()).data(ITEM_ROLE) is top
    view.deleteLater()


def test_fresh_timer_stops_even_when_rows_are_not_painted(qapp):
    from src.ui.theme import THEME

    THEME.set_motion(True)
    view = _LogList(False, "empty", headers=False)
    view.resize(500, 300)
    view.show()
    view.model_.set_items(entries(200))
    view.verticalScrollBar().setValue(2000)  # the new rows at the top are off screen
    for entry in entries(3):
        view.model_.prepend(entry)
    assert view._fresh_timer.isActive()
    pump(qapp, 1.6)
    assert not view._fresh_timer.isActive()
    view.deleteLater()


def test_logs_panel_updates_live(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PING_MONITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PING_MONITOR_SIMULATE", "1")
    previous = tmp_path / "ping_spikes.log"
    stamp = (datetime.now() - timedelta(hours=1)).replace(microsecond=0)
    previous.write_text(f"=== Session {stamp:%Y-%m-%d %H:%M:%S} ===\n[{stamp:%Y-%m-%d %H:%M:%S}] a.com: 99ms\n",
                        encoding="utf-8")
    from src.app import AppController

    ctrl = AppController(qapp, start_hidden=True)
    try:
        ctrl.open_logs()
        pump(qapp, 0.3)
        panel = ctrl.window.overlay.top_panel()
        assert isinstance(panel, LogsPanel)
        before = panel.current_list.model_.rowCount()
        server = ctrl.settings.servers[0]
        ctrl._on_result(PingResult(server.name, server.host, datetime.now(), PingStatus.OK, 250))
        assert panel.current_list.model_.rowCount() == before + 1
        first = panel.current_list.model_.data(panel.current_list.model_.index(0), ITEM_ROLE)
        assert first.rtt_ms == 250
        panel.tabs.set_current(1)
        rows = panel.previous_list.model_.rowCount()
        assert rows == 2  # session header + the archived entry
        panel.request_close()
        pump(qapp, 0.4)
        assert not ctrl.window.overlay.is_open()
        ctrl.open_logs()  # the last tab is remembered while the app runs
        pump(qapp, 0.3)
        panel = ctrl.window.overlay.top_panel()
        assert panel.tabs.current() == 1 and panel.previous_list.isVisible()
        assert not panel.current_list.isVisible()
    finally:
        LogsPanel._last_tab = 0
        ctrl.quit()


def test_previous_sessions_retry_after_a_read_error(qapp, tmp_path, monkeypatch):
    log = SpikeLog(tmp_path)
    log.start_session()
    calls = []

    def flaky(limit):
        calls.append(limit)
        if len(calls) == 1:
            raise PermissionError(13, "The file is in use")
        return SpikeLog.recent_previous_items(log, limit)

    monkeypatch.setattr(log, "recent_previous_items", flaky)
    panel = LogsPanel(log, 60, tmp_path)
    try:
        panel.tabs.set_current(1)
        assert "Could not read" in panel.previous_list.empty_text
        panel.tabs.set_current(0)
        panel.tabs.set_current(1)
        assert len(calls) == 2 and panel._previous_loaded
        assert "Could not read" not in panel.previous_list.empty_text
    finally:
        LogsPanel._last_tab = 0
        log.close()
        panel.deleteLater()


def test_new_entries_do_not_cut_a_glide_short(qapp):
    from src.ui.theme import THEME

    THEME.set_motion(True)
    view = _LogList(False, "empty", headers=False)
    view.resize(500, 300)
    view.show()
    view.model_.set_items(entries(300))
    pump(qapp, 0.1)
    bar = view.verticalScrollBar()
    bar.setValue(600)
    bar.glide_to(1200, 300)  # e.g. a wheel notch
    pump(qapp, 0.05)
    view.model_.prepend(entries(1)[0])
    pump(qapp, 0.5)
    assert bar.value() == 1200 + view._delegate.row_height()
    view.deleteLater()


def test_tabs_switch_back_and_forth_with_the_keyboard(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    log = SpikeLog(tmp_path)
    log.start_session()
    panel = LogsPanel(log, 60, tmp_path)
    panel.show()
    try:
        panel.tabs.setFocus()
        for key, expected in ((Qt.Key.Key_Right, 1), (Qt.Key.Key_Left, 0), (Qt.Key.Key_Right, 1)):
            panel.tabs.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
            assert panel.tabs.current() == expected
            assert panel.focusWidget() is panel.tabs
    finally:
        LogsPanel._last_tab = 0
        log.close()
        panel.deleteLater()


def test_highlight_finishes_after_showing_the_list_again(qapp):
    from src.ui.theme import THEME

    THEME.set_motion(True)
    view = _LogList(False, "empty", headers=False)
    view.resize(500, 300)
    view.show()
    view.hide()
    view.model_.prepend(entries(1)[0])  # arrives while another tab is shown
    view.show()
    assert view._fresh_timer.isActive()
    pump(qapp, 1.5)
    assert not view._fresh_timer.isActive()
    view.deleteLater()


def test_home_and_end_go_to_the_first_and_last_entry(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    view = _LogList(False, "empty", headers=False)
    view.resize(500, 300)
    view.show()
    view.model_.set_items(entries(100))
    view.setCurrentIndex(view.model_.index(10, 0))
    for key, row in ((Qt.Key.Key_End, 99), (Qt.Key.Key_Home, 0)):
        view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        assert view.currentIndex().row() == row
    view.deleteLater()
