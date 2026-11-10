"""Logs overlay behaviour (offscreen Qt, simulated pings)."""

import os
import time
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core.models import PingResult, PingStatus  # noqa: E402
from src.core.spike_log import SessionMarker, SpikeEntry  # noqa: E402
from src.ui.logs_panel import ITEM_ROLE, LogModel, LogsPanel  # noqa: E402


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
    model = LogModel()
    model.set_items(items)
    rows = [model.data(model.index(row), ITEM_ROLE) for row in range(model.rowCount())]
    assert rows[0] == new_session and rows[1].server == "b.com"
    assert rows[2] == old_session and rows[3].kind == "timeout" and rows[4].rtt_ms == 70
    assert model.session_count(old_session) == 2 and model.session_count(new_session) == 1


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
    finally:
        ctrl.quit()
