"""End-to-end smoke test of the Qt app (offscreen, simulated pings)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core.models import HealthStatus, ServerSpec  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from src.ui.theme import THEME

    THEME.load_fonts()
    return app


def pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PING_MONITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PING_MONITOR_SIMULATE", "1")
    from src.app import AppController

    ctrl = AppController(qapp, start_hidden=True)
    yield ctrl
    ctrl.quit()


def test_pings_flow_into_pages_and_tray(qapp, controller):
    pump(qapp, 1.4)
    names = controller.settings.server_names()
    for name in names:
        assert controller.histories[name].counters.pings >= 1
        assert controller.window.page(name).stream.model.rowCount() >= 1
    assert controller.tray.tray.toolTip().startswith("Ping Monitor")


def test_settings_apply_keeps_unchanged_servers(qapp, controller, tmp_path):
    pump(qapp, 1.2)
    kept_before = controller.histories["cloudflare.com"].counters.pings
    new = controller.settings.with_changes(
        servers=(ServerSpec("cloudflare.com", "1.1.1.1"), ServerSpec("example.org", "93.184.215.14")),
        ping_threshold_healthy=30,
        preserved_minutes=5,
    )
    controller.apply_settings(new)
    assert (tmp_path / "app_config.json").exists()
    assert controller.window.page("google.com") is None
    assert controller.window.tabs.names() == ["cloudflare.com", "example.org"]
    pump(qapp, 1.2)
    assert controller.histories["cloudflare.com"].counters.pings > kept_before
    assert controller.histories["example.org"].counters.pings >= 1
    assert controller.histories["cloudflare.com"].thresholds == (30, 60)


def test_reset_pause_and_close_to_tray(qapp, controller):
    pump(qapp, 1.2)
    controller.reset_all()
    for name, history in controller.histories.items():
        assert history.counters.pings == 0
        assert controller.window.page(name).stream.model.rowCount() == 0
        assert history.health() is HealthStatus.UNKNOWN
    controller.set_paused(True)
    pump(qapp, 0.3)
    counts = {name: h.counters.pings for name, h in controller.histories.items()}
    pump(qapp, 1.3)
    assert counts == {name: h.counters.pings for name, h in controller.histories.items()}
    controller.set_paused(False)
    pump(qapp, 1.2)
    assert any(h.counters.pings for h in controller.histories.values())

    controller.set_close_to_tray(False)
    assert controller.settings.close_to_tray is False
    controller.set_close_to_tray(True)
    assert controller.settings.close_to_tray is True
