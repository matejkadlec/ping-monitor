"""
Application controller: wires settings, the ping engine, histories, the spike
log, the main window and the tray icon together.

Results travel from the worker threads to the GUI thread through a queued Qt
signal; every piece of state is only touched on the GUI thread.
"""

import json
import logging
import os
import sys
import time

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from src.core import autostart
from src.core.alerts import STARTUP_QUIET_S, WAKE_GAP_S, WAKE_QUIET_S, Alert, HealthAlerts
from src.core.engine import PingEngine
from src.core.fileio import atomic_write_text
from src.core.models import HealthStatus, PingResult, PingStatus, ServerSpec, is_problem
from src.core.paths import APP_NAME, APP_USER_MODEL_ID, asset_path, data_dir
from src.core.settings import Settings, load_settings, save_settings
from src.core.spike_log import SpikeLog
from src.core.stats import ServerHistory
from src.ui import win32
from src.ui.config_panel import ConfigPanel
from src.ui.logs_panel import LogsPanel
from src.ui.main_window import MainWindow
from src.ui.theme import THEME
from src.ui.tray import TrayController
from src.utils.logging_setup import configure_logging
from src.utils.single_instance import SingleInstance

LOGGER = logging.getLogger(__name__)

WATCHDOG_INTERVAL_MS = 2_000
CLEANUP_INTERVAL_MS = 60 * 60 * 1000
UI_STATE_FILE_NAME = "ui_state.json"
SETTINGS_QUIET_S = 30.0  # no "failing" alert right after editing the config


def short_value(result: PingResult) -> str | None:
    """Compact latest value for tabs and the tray tooltip (None keeps the previous one)."""
    if result.status is PingStatus.OK:
        return "<1 ms" if result.rtt_ms == 0 else f"{result.rtt_ms} ms"
    if result.status is PingStatus.TIMEOUT:
        return "timeout"
    if result.status is PingStatus.GAP:
        return None
    return "lost"


class _ResultBridge(QObject):
    result = Signal(object)


class AppController(QObject):
    def __init__(self, app: QApplication, start_hidden: bool = False) -> None:
        super().__init__()
        self.app = app
        self.settings: Settings = load_settings()
        self.histories: dict[str, ServerHistory] = {}
        self._hosts: dict[str, str] = {}
        self._last_values: dict[str, str] = {}
        self._quitting = False
        self._tray_health = HealthStatus.UNKNOWN
        self._alerts = HealthAlerts()
        self._alerts.quiet(time.monotonic(), STARTUP_QUIET_S)  # Wi-Fi may still be connecting

        self.spike_log = SpikeLog(data_dir())
        self.spike_log.start_session()

        # Start pinging before the UI exists: queued results are delivered as
        # soon as the event loop runs, so the first ping is never delayed.
        self._bridge = _ResultBridge()
        self._bridge.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
        self.engine = PingEngine(self._bridge.result.emit, interval_s=self.settings.ping_interval)
        self._sync_histories()
        self.engine.set_servers(self.settings.servers)
        self.engine.start()

        self.window = MainWindow()
        self.window.closeRequested.connect(self._on_close_requested)
        self.window.visibilityChanged.connect(self._on_visibility_changed)
        self.window.resetCurrentRequested.connect(self.reset_server)
        self.window.resetAllRequested.connect(self.reset_all)
        self.window.pauseToggled.connect(self.set_paused)
        self.window.configRequested.connect(self.open_config)
        self.window.logsRequested.connect(self.open_logs)
        self.window.set_servers(self._page_specs())
        self.window.set_background_image(self.settings.background_image)
        try:
            self.window.restore_state(self._load_ui_state())
        except Exception:  # a hand-edited ui_state.json must never stop the app
            LOGGER.warning("Ignoring the saved window state", exc_info=True)

        self.tray = TrayController(self)
        self.tray.showRequested.connect(self.show_window)
        self.tray.hideRequested.connect(self.hide_window)
        self.tray.quitRequested.connect(self.quit)
        self.tray.closeToTrayToggled.connect(self.set_close_to_tray)
        self.tray.set_close_to_tray(self.settings.close_to_tray)
        self.tray.set_window_visible(False)
        self.tray.show()

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self.engine.check_workers)
        self._watchdog.start()
        self._cleanup = QTimer(self)
        self._cleanup.setInterval(CLEANUP_INTERVAL_MS)
        self._cleanup.timeout.connect(self.spike_log.cleanup)
        self._cleanup.start()

        self._window_fade = QPropertyAnimation(self.window, b"windowOpacity", self)
        self._window_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._window_fade.finished.connect(self._window_fade_finished)
        self._hide_after_fade = False
        if not start_hidden:
            self.show_window()

    # ------------------------------------------------------------ servers
    def _sync_histories(self) -> None:
        settings = self.settings
        wanted = {server.name: server.host for server in settings.servers}
        for name in list(self.histories):
            if wanted.get(name) != self._hosts.get(name):
                del self.histories[name]
                self._hosts.pop(name, None)
                self._last_values.pop(name, None)
        for server in settings.servers:
            history = self.histories.get(server.name)
            if history is None:
                history = ServerHistory(settings.preserved_minutes, settings.ping_threshold_healthy,
                                        settings.ping_threshold_degraded, settings.ping_interval)
                self.histories[server.name] = history
                self._hosts[server.name] = server.host
            else:
                history.set_thresholds(settings.ping_threshold_healthy, settings.ping_threshold_degraded)
                history.set_interval(settings.ping_interval)
                history.set_preserved_minutes(settings.preserved_minutes)

    def _page_specs(self) -> list[tuple[str, str, ServerHistory]]:
        return [(server.name, server.host, self.histories[server.name]) for server in self.settings.servers]

    @property
    def tray_server(self) -> ServerSpec | None:
        return self.settings.servers[0] if self.settings.servers else None

    # ------------------------------------------------------------ results
    def _on_result(self, result: PingResult) -> None:
        history = self.histories.get(result.server)
        if history is None or self._hosts.get(result.server) != result.host:
            return  # result of a server that was just removed or changed
        if self.engine.paused:
            return  # queued just before pausing
        if result.status is PingStatus.GAP and (result.gap_seconds or 0) >= WAKE_GAP_S:
            self._alerts.quiet(time.monotonic(), WAKE_QUIET_S)  # back from sleep: network reconnecting
        evicted = history.add(result)
        if is_problem(result, self.settings.ping_threshold_degraded):
            entry = self.spike_log.record(result)
            logs = self.window.overlay.contains_panel(LogsPanel)
            if logs is not None:
                logs.add_entry(entry)
        value = short_value(result)
        if value is not None:
            self._last_values[result.server] = value
        self.window.append_result(result, evicted)
        self.window.update_tab(result.server, history.health(), self._last_values.get(result.server, ""))
        tray_server = self.tray_server
        if tray_server is not None and result.server == tray_server.name:
            self._update_tray(problem=is_problem(result, self.settings.ping_threshold_degraded))

    def _update_tray(self, problem: bool | None = None) -> None:
        """Refresh the tray icon; ``problem`` is given after a ping of the tray server."""
        tray_server = self.tray_server
        if tray_server is None:
            return
        history = self.histories.get(tray_server.name)
        report = history.health_report() if history else None
        status = report.status if report else HealthStatus.UNKNOWN
        lines = [f"{server.name}: {self._last_values.get(server.name, '–')}" for server in self.settings.servers]
        if self.engine.paused:
            lines.insert(0, "Paused")
        self.tray.set_status(status, lines)
        self._tray_health = status
        if problem is not None:
            self._alert(tray_server.name, self._alerts.update(status, time.monotonic(), problem),
                        report.summary() if report else "")

    def _alert(self, name: str, alert: Alert | None, reasons: str = "") -> None:
        """Windows notification when the tray server starts failing and when it is
        healthy again (the timing rules live in HealthAlerts)."""
        if alert is None or not self.settings.notifications:
            return
        if alert is Alert.FAILING:
            detail = f"{reasons[:1].upper()}{reasons[1:]}." if reasons else "The connection has problems."
            self.tray.notify(f"{name} is failing", detail, warning=True)
        else:
            self.tray.notify(f"{name} is healthy again", "Pings are back to normal.")

    # ------------------------------------------------------------ actions
    def reset_server(self, name: str) -> None:
        history = self.histories.get(name)
        if history is None:
            return
        history.reset()
        self._last_values.pop(name, None)
        if self.tray_server is not None and name == self.tray_server.name:
            self._alerts.reset()
        self.window.reload_page(name)
        self.window.update_tab(name, HealthStatus.UNKNOWN, "")
        self._update_tray()
        LOGGER.info("Reset metrics of %s", name)

    def reset_all(self) -> None:
        for name in list(self.histories):
            self.reset_server(name)

    def set_paused(self, paused: bool) -> None:
        self.engine.set_paused(paused)
        self.window.set_paused(paused)
        self._update_tray()
        LOGGER.info("Pinging %s", "paused" if paused else "resumed")

    def set_close_to_tray(self, enabled: bool) -> None:
        if enabled == self.settings.close_to_tray:
            return
        try:
            self.apply_settings(self.settings.with_changes(close_to_tray=enabled))
        except OSError as error:
            self.tray.set_close_to_tray(self.settings.close_to_tray)
            self.tray.notify(APP_NAME, f"Could not save the setting: {error}", warning=True)
            return
        panel = self.window.overlay.contains_panel(ConfigPanel)
        if panel is not None:
            panel.sync_close_to_tray(enabled)  # its next Save must not undo this

    def apply_settings(self, settings: Settings) -> None:
        """Persist and apply new settings without throwing away unchanged data.

        Raises OSError (and changes nothing) when the settings cannot be saved.
        """
        save_settings(settings)
        previous = self.settings
        self.settings = settings
        old_tray = (previous.servers[0].name, previous.servers[0].host) if previous.servers else None
        new_tray = (settings.servers[0].name, settings.servers[0].host) if settings.servers else None
        if old_tray != new_tray:
            self._alerts.reset()  # another server drives the tray now
        self._alerts.quiet(time.monotonic(), SETTINGS_QUIET_S)
        self._sync_histories()
        self.engine.set_interval(settings.ping_interval)
        self.engine.set_servers(settings.servers)
        if [(s.name, s.host) for s in previous.servers] != [(s.name, s.host) for s in settings.servers]:
            self.window.set_servers(self._page_specs())
        display = ("ping_threshold_healthy", "ping_threshold_degraded", "preserved_minutes")
        if any(getattr(previous, field) != getattr(settings, field) for field in display):
            # Recolor / trim the existing data (pages of untouched servers keep
            # their scroll position and selection when only other settings change).
            self.window.reload_all()
        for name, history in self.histories.items():
            self.window.update_tab(name, history.health(), self._last_values.get(name, ""))
        self.tray.set_close_to_tray(settings.close_to_tray)
        self.window.set_background_image(settings.background_image)
        self._update_tray()
        LOGGER.info("Settings applied")

    def open_config(self) -> None:
        overlay = self.window.overlay
        if overlay.contains_panel(ConfigPanel) is not None:
            return
        self.show_window()
        self.window.open_panel(ConfigPanel(self.settings, self.apply_settings, overlay, self.window.toasts))

    def open_logs(self) -> None:
        if self.window.overlay.contains_panel(LogsPanel) is not None:
            return
        self.show_window()
        self.window.open_panel(LogsPanel(self.spike_log, self.settings.ping_threshold_degraded, data_dir()))

    # ------------------------------------------------------------- window
    def show_window(self) -> None:
        window = self.window
        fading_in = not window.isVisible() or window.windowOpacity() < 1.0
        if fading_in and THEME.motion:
            window.setWindowOpacity(0.0)
        self._hide_after_fade = False
        window.bring_to_front()
        if fading_in and THEME.motion:
            self._window_fade.stop()
            self._window_fade.setDuration(THEME.duration(200))
            self._window_fade.setStartValue(window.windowOpacity())
            self._window_fade.setEndValue(1.0)
            self._window_fade.start()

    def hide_window(self) -> None:
        window = self.window
        if not window.isVisible():
            return
        self._save_ui_state()
        if not THEME.motion:
            window.hide()
            return
        self._window_fade.stop()
        self._hide_after_fade = True
        self._window_fade.setDuration(THEME.duration(150))
        self._window_fade.setStartValue(window.windowOpacity())
        self._window_fade.setEndValue(0.0)
        self._window_fade.start()

    # ----------------------------------------------------------- ui state
    def _ui_state_path(self):
        return data_dir() / UI_STATE_FILE_NAME

    def _load_ui_state(self) -> dict:
        try:
            with open(self._ui_state_path(), "r", encoding="utf-8") as handle:
                state = json.load(handle)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_ui_state(self) -> None:
        try:
            atomic_write_text(self._ui_state_path(), json.dumps(self.window.save_state()) + "\n")
        except OSError:
            LOGGER.warning("Saving the window state failed", exc_info=True)

    def _window_fade_finished(self) -> None:
        if self._hide_after_fade:
            self._hide_after_fade = False
            self.window.hide()
            self.window.setWindowOpacity(1.0)

    def _on_visibility_changed(self, visible: bool) -> None:
        self.tray.set_window_visible(visible)

    def _on_close_requested(self) -> None:
        if self.settings.close_to_tray:
            self.hide_window()  # silently: the tray icon shows it is still running
        else:
            self.quit()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        LOGGER.info("Shutting down")
        if self.window.isVisible():
            self._save_ui_state()
        self._watchdog.stop()
        self._cleanup.stop()
        # Hide first so closing feels instant; workers may need a moment to stop.
        self.window.hide()
        self.tray.hide()
        self.engine.stop()
        self.spike_log.close()
        self.app.quit()


def apply_app_style(app: QApplication) -> None:
    app.setFont(THEME.font(13))
    app.setStyleSheet(THEME.stylesheet())


def run(argv: list[str]) -> int:
    configure_logging()
    win32.set_app_user_model_id(APP_USER_MODEL_ID)
    # Name + icon for notifications (otherwise Windows shows the raw ID as the sender).
    win32.register_app_identity(APP_USER_MODEL_ID, APP_NAME, asset_path("icon.ico"), data_dir())
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance()
    if instance.notify_running_instance():
        LOGGER.info("Ping Monitor is already running, showing the existing window")
        return 0
    instance.listen()

    THEME.load_fonts()
    THEME.set_motion(win32.animations_enabled())
    apply_app_style(app)
    THEME.changed.connect(lambda: apply_app_style(app))
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateMenu, False)  # menus fade themselves
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateTooltip, THEME.motion)
    app.setEffectEnabled(Qt.UIEffect.UI_FadeTooltip, THEME.motion)

    controller = AppController(app, start_hidden="--minimized" in argv)
    if not (os.environ.get("PING_MONITOR_DATA_DIR") or os.environ.get("PING_MONITOR_SIMULATE")):
        try:
            autostart.refresh()  # repair the entry if the app's folder moved
        except OSError:
            LOGGER.warning("Checking Start With Windows failed", exc_info=True)
    instance.activationRequested.connect(controller.show_window)
    app.aboutToQuit.connect(controller.quit)
    code = app.exec()
    instance.close()
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv))
