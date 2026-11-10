"""
Main window: server tabs (top left), actions (top right), one page per server.
"""

from PySide6.QtCore import QByteArray, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.models import HealthStatus, PingResult
from src.core.paths import APP_NAME, asset_path
from src.core.stats import ServerHistory
from src.ui import win32
from src.ui.controls import IconButton, Tween, fade, settle_fades
from src.ui.menus import FadeMenu
from src.ui.overlay import OverlayHost, Panel
from src.ui.server_page import ServerPage
from src.ui.tab_strip import TabStrip
from src.ui.theme import THEME
from src.ui.toast import ToastManager

DEFAULT_SIZE = QSize(1200, 800)
MINIMUM_SIZE = QSize(760, 520)
# Window size (logical px) at which the UI is drawn at 100 %.
BASE_WIDTH, BASE_HEIGHT = 1200, 780


class _Root(QWidget):
    """Paints the window background (plain or the optional picture, cross-faded);
    keeps overlays and toasts sized to it."""

    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._image_opacity = Tween(self, self.update, value=0.0, duration=THEME.SLOW)
        self._rescale_timer = QTimer(self)
        self._rescale_timer.setSingleShot(True)
        self._rescale_timer.setInterval(150)
        self._rescale_timer.timeout.connect(self._rescale)

    def set_background_image(self, enabled: bool) -> None:
        if enabled and self._image is None:
            path = asset_path("background.png")
            image = QPixmap(str(path)) if path.exists() else QPixmap()
            self._image = None if image.isNull() else image
        if enabled:
            self._rescale()
        self._image_opacity.to(1.0 if enabled and self._image is not None else 0.0)

    def _rescale(self) -> None:
        if self._image is None or self.width() <= 0 or self.height() <= 0:
            return
        ratio = self.devicePixelRatioF()
        target = QSize(round(self.width() * ratio), round(self.height() * ratio))
        scaled = self._image.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self._scaled = scaled
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._image_opacity.value > 0:
            self._rescale_timer.start()
        self.resized.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(THEME.colors.abyss))
        opacity = self._image_opacity.value
        if opacity <= 0.001 or self._scaled is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = self._scaled.deviceIndependentSize()
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(QRectF(self.rect()).center())
        painter.setOpacity(opacity)
        # Stretch the last good image while a resize is still settling.
        cover = QRectF(self.rect())
        if target.width() < cover.width() or target.height() < cover.height():
            target = cover
        painter.drawPixmap(target, self._scaled, QRectF(self._scaled.rect()))
        veil = QColor(THEME.colors.abyss)
        veil.setAlphaF(0.58)
        painter.fillRect(self.rect(), veil)


class _TopBar(QWidget):
    """Tabs on the left, actions on the right, hairline underneath."""

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(0, self.height() - 1, self.width(), 1, QColor(THEME.colors.hairline))


class MainWindow(QMainWindow):
    closeRequested = Signal()
    visibilityChanged = Signal(bool)
    resetCurrentRequested = Signal(str)
    resetAllRequested = Signal()
    pauseToggled = Signal(bool)
    configRequested = Signal()
    logsRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        icon_path = asset_path("icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(MINIMUM_SIZE)
        self._place_default()

        self._pages: dict[str, ServerPage] = {}
        self._order: list[str] = []
        self._styled = False
        self._paused = False

        root = _Root(self)
        root.setObjectName("Root")
        self.setCentralWidget(root)
        self.content = QWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.content)

        self.top_bar = _TopBar(self.content)
        self.tabs = TabStrip(self.top_bar)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(THEME.px(4))
        self.pause_button = IconButton("pause", "Pause pinging", self.top_bar)
        self.pause_button.clicked.connect(lambda: self.set_paused(not self._paused, emit=True))
        self.reset_button = IconButton("rotate-ccw", "Reset metrics", self.top_bar)
        self.reset_button.clicked.connect(self._show_reset_menu)
        self.logs_button = IconButton("scroll-text", "Open logs", self.top_bar)
        self.logs_button.clicked.connect(self.logsRequested.emit)
        self.config_button = IconButton("settings", "Open config", self.top_bar)
        self.config_button.clicked.connect(self.configRequested.emit)
        self._actions.addWidget(self.pause_button)
        self._actions.addWidget(self.reset_button)
        self._actions.addWidget(self.logs_button)
        self._actions.addWidget(self.config_button)

        self._top_layout = QHBoxLayout(self.top_bar)
        self._top_layout.addWidget(self.tabs, 1)
        self._top_layout.addLayout(self._actions)

        self.stack = QStackedWidget(self.content)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.top_bar)
        content_layout.addWidget(self.stack, 1)

        self.overlay = OverlayHost(root, self.content)
        self.toasts = ToastManager(root)
        root.resized.connect(self._root_resized)
        self._root = root

        self._reset_menu = FadeMenu(self)
        self._reset_menu.addAction("Reset current tab", self._reset_current)
        self._reset_menu.addAction("Reset all tabs", self.resetAllRequested.emit)

        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(140)
        self._scale_timer.timeout.connect(self._apply_scale)

        self._install_shortcuts()
        THEME.changed.connect(self._apply_theme)
        self._apply_theme()

    def _place_default(self) -> None:
        """Default size, but never larger than the screen (1366x768, 125 % / 150 %
        scaling) and centered on it. A saved window state overrides this."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(DEFAULT_SIZE)
            return
        area = screen.availableGeometry()
        frame = 40  # title bar and borders are outside the client size
        width = max(MINIMUM_SIZE.width(), min(DEFAULT_SIZE.width(), area.width() - 2 * frame))
        height = max(MINIMUM_SIZE.height(), min(DEFAULT_SIZE.height(), area.height() - 2 * frame))
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2,
                  area.y() + max(0, (area.height() - height - frame) // 2))

    # ------------------------------------------------------------ servers
    def set_servers(self, servers: list[tuple[str, str, ServerHistory]]) -> None:
        """Create/remove pages so they match ``servers`` (order matters)."""
        current = self.current_server()
        wanted = {name for name, _, _ in servers}
        for name in list(self._pages):
            if name not in wanted:
                page = self._pages.pop(name)
                self.stack.removeWidget(page)
                page.deleteLater()
        for name, host, history in servers:
            page = self._pages.get(name)
            if page is None or page.host != host or page.history is not history:
                if page is not None:
                    self.stack.removeWidget(page)
                    page.deleteLater()
                page = ServerPage(name, host, history)
                page.set_paused(self._paused)
                self._pages[name] = page
                self.stack.addWidget(page)
        self._order = [name for name, _, _ in servers]
        index = self._order.index(current) if current in self._order else 0
        self.tabs.set_tabs(self._order, index)
        if self._order:
            self.stack.setCurrentWidget(self._pages[self._order[index]])

    def page(self, name: str) -> ServerPage | None:
        return self._pages.get(name)

    def current_server(self) -> str | None:
        index = self.tabs.current_index()
        return self._order[index] if 0 <= index < len(self._order) else None

    def append_result(self, result: PingResult, evicted: int) -> None:
        page = self._pages.get(result.server)
        if page is not None:
            page.append(result, evicted)

    def update_tab(self, name: str, health: HealthStatus, value: str) -> None:
        if name in self._order:
            self.tabs.update_tab(self._order.index(name), health, value)

    def reload_page(self, name: str) -> None:
        page = self._pages.get(name)
        if page is not None:
            page.reload()

    def reload_all(self) -> None:
        for page in self._pages.values():
            page.reload()

    # ------------------------------------------------------------- actions
    def set_paused(self, paused: bool, emit: bool = False) -> None:
        self._paused = paused
        self.pause_button.set_icon_name("play" if paused else "pause")
        self.pause_button.setToolTip("Resume pinging (Ctrl+P)" if paused else "Pause pinging (Ctrl+P)")
        for page in self._pages.values():
            page.set_paused(paused)
        if emit:
            self.pauseToggled.emit(paused)

    def _show_reset_menu(self) -> None:
        anchor = self.reset_button.mapToGlobal(self.reset_button.rect().bottomRight())
        width = self._reset_menu.sizeHint().width()
        self._reset_menu.popup(QPoint(anchor.x() - width, anchor.y() + THEME.px(6)))

    def _reset_current(self) -> None:
        name = self.current_server()
        if name:
            self.resetCurrentRequested.emit(name)

    def _on_tab_changed(self, index: int) -> None:
        if not 0 <= index < len(self._order):
            return
        page = self._pages[self._order[index]]
        if self.stack.currentWidget() is page:
            return
        self.stack.setCurrentWidget(page)
        if self.isVisible() and not self.isMinimized():
            settle_fades(page)  # no nested opacity effects
            fade(page, True, THEME.duration(180))

    def _install_shortcuts(self) -> None:
        def go(offset: int) -> None:
            count = self.tabs.count()
            if count:
                self.tabs.set_current((self.tabs.current_index() + offset) % count)

        QShortcut(QKeySequence("Ctrl+Tab"), self, lambda: go(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, lambda: go(-1))
        for number in range(1, 10):
            QShortcut(QKeySequence(f"Ctrl+{number}"), self,
                      lambda n=number: self.tabs.set_current(n - 1) if n <= self.tabs.count() else None)
        QShortcut(QKeySequence("Ctrl+R"), self, self._reset_current)
        QShortcut(QKeySequence("Ctrl+,"), self, self.configRequested.emit)
        QShortcut(QKeySequence("Ctrl+L"), self, self.logsRequested.emit)
        QShortcut(QKeySequence("Ctrl+P"), self, lambda: self.set_paused(not self._paused, emit=True))

    # ------------------------------------------------------------- extras
    def set_background_image(self, enabled: bool) -> None:
        self._root.set_background_image(enabled)

    def save_state(self) -> dict:
        return {
            "geometry": bytes(self.saveGeometry().toBase64().data()).decode("ascii"),
            "tab": self.current_server(),
        }

    def restore_state(self, state: dict) -> None:
        geometry = state.get("geometry")
        if isinstance(geometry, str) and geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        tab = state.get("tab")
        if isinstance(tab, str) and tab in self._order:
            self.tabs.set_current(self._order.index(tab), animate=False)
            self.stack.setCurrentWidget(self._pages[tab])

    # ------------------------------------------------------------ overlays
    def open_panel(self, panel: Panel) -> None:
        self.overlay.open(panel)
        self.toasts.raise_all()

    def _root_resized(self) -> None:
        self.overlay.setGeometry(self._root.rect())
        self.toasts.reposition()

    # --------------------------------------------------------------- theme
    def _apply_theme(self) -> None:
        self._top_layout.setContentsMargins(THEME.px(16), THEME.px(8), THEME.px(14), 0)
        self._top_layout.setSpacing(THEME.px(12))
        self.top_bar.setFixedHeight(THEME.px(56))

    def _apply_scale(self) -> None:
        width, height = self.width(), self.height()
        raw = min(width / BASE_WIDTH, height / BASE_HEIGHT)
        THEME.set_scale(round(max(0.9, min(1.3, raw)) * 10) / 10)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_timer.start()

    # -------------------------------------------------------------- window
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._styled:
            self._styled = True
            c = THEME.colors
            win32.style_title_bar(int(self.winId()), c.abyss, c.ink, c.hairline)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.closeRequested.emit()

    def bring_to_front(self) -> None:
        if self.isMinimized():
            # Un-minimize but keep maximized / full screen (showNormal() would not).
            self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized)
                                | Qt.WindowState.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()
