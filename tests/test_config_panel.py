"""Config overlay behaviour (offscreen Qt, simulated pings)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QValidator  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.config_panel import ConfigPanel, NumberValidator  # noqa: E402
from src.ui.overlay import ConfirmDialog  # noqa: E402


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


def wait_until(app, predicate, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PING_MONITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PING_MONITOR_SIMULATE", "1")
    from src.app import AppController

    ctrl = AppController(qapp, start_hidden=True)
    yield ctrl
    ctrl.quit()


def open_panel(qapp, controller) -> ConfigPanel:
    controller.open_config()
    pump(qapp, 0.3)
    panel = controller.window.overlay.top_panel()
    assert isinstance(panel, ConfigPanel)
    return panel


def test_number_validator_refuses_too_big_values():
    calls = []
    validator = NumberValidator(999, allow_forever=True, on_too_big=lambda: calls.append(1))
    assert validator.validate("999", 3)[0] == QValidator.State.Acceptable
    assert validator.validate("1000", 4)[0] == QValidator.State.Invalid
    assert calls == [1]
    assert validator.validate("-1", 2)[0] == QValidator.State.Acceptable
    assert validator.validate("-2", 2)[0] == QValidator.State.Invalid
    assert validator.validate("4a", 2)[0] == QValidator.State.Invalid
    assert validator.validate("", 0)[0] == QValidator.State.Intermediate


def test_save_applies_settings_and_closes(qapp, controller):
    panel = open_panel(qapp, controller)
    assert not panel.save_button.isEnabled()
    panel.healthy.setText("35")
    assert panel.save_button.isEnabled()
    panel.save_button.click()
    assert controller.settings.ping_threshold_healthy == 35
    assert wait_until(qapp, lambda: not controller.window.overlay.is_open(), 2.0)


def test_invalid_values_are_flagged_and_not_saved(qapp, controller):
    panel = open_panel(qapp, controller)
    panel.healthy.setText("80")
    panel.degraded.setText("60")
    panel.save_button.click()
    assert controller.settings.ping_threshold_healthy == 40
    assert panel.degraded.property("invalid") is True
    assert controller.window.overlay.top_panel() is panel


def test_new_server_is_checked_then_saved(qapp, controller):
    panel = open_panel(qapp, controller)
    panel.add_button.click()
    row = panel._rows[-1]
    row.name.setText("example.org")
    row.host.setText("93.184.215.14")
    panel.save_button.click()
    assert wait_until(qapp, lambda: "example.org" in controller.settings.server_names(), 5.0)
    assert controller.window.tabs.names()[-1] == "example.org"


def test_bad_ip_format_is_rejected(qapp, controller):
    panel = open_panel(qapp, controller)
    panel._rows[0].host.setText("300.1.1.1")
    panel.save_button.click()
    assert panel._rows[0].host.property("invalid") is True
    assert controller.settings.servers[0].host == "1.1.1.1"


def test_only_one_empty_row_and_delete_confirmation(qapp, controller):
    panel = open_panel(qapp, controller)
    count = len(panel._rows)
    panel.add_button.click()
    panel.add_button.click()  # refused: an empty row already exists
    assert len(panel._rows) == count + 1

    panel._rows[0].delete.click()
    pump(qapp, 0.3)
    dialog = controller.window.overlay.top_panel()
    assert isinstance(dialog, ConfirmDialog)
    dialog.yes_button.click()
    pump(qapp, 0.3)
    assert len(panel._rows) == count
    assert panel._rows[0].name.text() == "google.com"


def test_unsaved_changes_ask_before_closing(qapp, controller):
    panel = open_panel(qapp, controller)
    panel.interval.setText("2")
    panel.request_close()
    pump(qapp, 0.3)
    dialog = controller.window.overlay.top_panel()
    assert isinstance(dialog, ConfirmDialog)
    dialog.no_button.click()
    pump(qapp, 0.3)
    assert controller.window.overlay.top_panel() is panel
    panel.request_close()
    pump(qapp, 0.3)
    controller.window.overlay.top_panel().yes_button.click()
    assert wait_until(qapp, lambda: not controller.window.overlay.is_open(), 2.0)
    assert controller.settings.ping_interval == 1


def start_host_check(qapp, panel) -> None:
    panel.add_button.click()
    row = panel._rows[-1]
    row.name.setText("example.org")
    row.host.setText("93.184.215.14")
    panel.save_button.click()  # the check runs in a thread; its result is queued
    assert panel._check_token is not None


def test_cancelling_a_host_check_restores_save(qapp, controller):
    panel = open_panel(qapp, controller)
    start_host_check(qapp, panel)
    panel.request_close()  # Esc / X / Cancel while "Checking…"
    pump(qapp, 0.3)
    dialog = controller.window.overlay.top_panel()
    assert isinstance(dialog, ConfirmDialog)
    dialog.no_button.click()
    pump(qapp, 0.6)
    assert controller.window.overlay.top_panel() is panel
    assert panel.save_button.isEnabled() and panel.save_button.text() == "Save"
    assert "example.org" not in controller.settings.server_names()


def test_no_delete_dialog_while_checking(qapp, controller):
    panel = open_panel(qapp, controller)
    start_host_check(qapp, panel)
    panel._rows[0].delete.click()
    assert controller.window.overlay.top_panel() is panel  # no "Delete server?" dialog
    assert wait_until(qapp, lambda: "example.org" in controller.settings.server_names(), 5.0)
    assert "cloudflare.com" in controller.settings.server_names()


def test_double_save_applies_once(qapp, controller):
    panel = open_panel(qapp, controller)
    calls = []
    save = panel._on_save
    panel._on_save = lambda settings: (calls.append(settings), save(settings))
    panel.healthy.setText("33")
    panel.save_button.click()
    panel._save()  # a second click while it fades out
    assert len(calls) == 1
    assert not panel.save_button.isEnabled()


def test_tab_stays_inside_the_panel(qapp, controller):
    panel = open_panel(qapp, controller)
    window = controller.window
    panel.save_button.setFocus()
    for _ in range(40):
        panel.focusNextPrevChild(True)
        assert panel.isAncestorOf(window.focusWidget())
    for _ in range(5):
        panel.focusNextPrevChild(False)
        assert panel.isAncestorOf(window.focusWidget())


def test_window_shortcuts_wait_while_a_panel_is_open(qapp, controller):
    from PySide6.QtGui import QShortcut

    open_panel(qapp, controller)
    for shortcut in controller.window.findChildren(QShortcut):
        if shortcut.key().toString() == "Ctrl+P":
            shortcut.activated.emit()
    assert not controller.engine.paused


def test_tray_toggle_while_open_is_not_undone_by_save(qapp, controller):
    panel = open_panel(qapp, controller)
    controller.set_close_to_tray(False)
    assert not panel.close_to_tray.isChecked()
    panel.healthy.setText("36")
    panel.save_button.click()
    assert controller.settings.ping_threshold_healthy == 36
    assert controller.settings.close_to_tray is False


def test_panel_grows_with_added_rows(qapp, controller):
    controller.window.resize(1200, 1000)
    panel = open_panel(qapp, controller)
    pump(qapp, 0.6)
    before = panel.height()
    panel.add_button.click()
    pump(qapp, 0.5)
    assert panel.height() > before


def test_ambient_animations_stop_while_a_panel_is_open(qapp, controller):
    from datetime import datetime

    from src.core.models import PingResult, PingStatus
    from src.ui.theme import THEME

    THEME.set_motion(True)
    controller.engine.stop()
    open_panel(qapp, controller)
    page = controller.window.page(controller.settings.servers[0].name)
    server = controller.settings.servers[0]
    for _ in range(3):
        controller._on_result(PingResult(server.name, server.host, datetime.now(), PingStatus.OK, 20))
        pump(qapp, 0.1)
    assert not page.stream.view._fresh_timer.isActive()
