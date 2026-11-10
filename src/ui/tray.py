"""
System tray icon: colored status dot (first server), compact styled menu.
"""

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSystemTrayIcon, QWidget, QWidgetAction

from src.core.models import HealthStatus
from src.core.paths import APP_NAME
from src.ui.controls import CheckBox, Tween
from src.ui.menus import FadeMenu
from src.ui.theme import THEME

TRAY_COLORS = {
    HealthStatus.UNKNOWN: "#8A94A6",
    HealthStatus.HEALTHY: "#4A964F",
    HealthStatus.DEGRADED: "#D4A72C",
    HealthStatus.FAILING: "#C73C3C",
}
WINDOWS_TOOLTIP_LIMIT = 127


def status_icon(status: HealthStatus) -> QIcon:
    """Anti-aliased dot with a hairline border in a darker shade of the same color."""
    fill = QColor(TRAY_COLORS[status])
    border = QColor(fill).darker(165)
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        border_width = size / 32  # 0.5 px at 16 px
        margin = size * 0.12
        diameter = size - 2 * margin
        pen = QPen(border)
        pen.setWidthF(border_width)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(margin, margin, diameter, diameter))
        # A tiny highlight keeps the dot from looking flat on dark taskbars.
        highlight = QColor(255, 255, 255, 46)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(highlight)
        painter.drawEllipse(QPointF(size / 2 - diameter * 0.16, size / 2 - diameter * 0.18),
                            diameter * 0.18, diameter * 0.14)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class _ToggleRow(QWidget):
    """Menu row with a label and a checkbox on the right (no check column for other items)."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._hover = Tween(self, self.update)
        self.checkbox = CheckBox()
        self.checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        label = QLabel(text)
        label.setStyleSheet(f"color: {THEME.colors.ink}; font-size: {THEME.px(13)}px; background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(THEME.px(14), THEME.px(5), THEME.px(10), THEME.px(5))
        layout.setSpacing(THEME.px(18))
        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(self.checkbox)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def enterEvent(self, event) -> None:
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.checkbox.toggle()
        event.accept()

    def paintEvent(self, _event) -> None:
        if self._hover.value <= 0.01:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(THEME.colors.raised_hover)
        color.setAlphaF(self._hover.value)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(self.rect()), THEME.px(6), THEME.px(6))


class TrayController(QObject):
    showRequested = Signal()
    hideRequested = Signal()
    quitRequested = Signal()
    closeToTrayToggled = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icons = {status: status_icon(status) for status in HealthStatus}
        self._status = HealthStatus.UNKNOWN
        self.tray = QSystemTrayIcon(self._icons[self._status], self)
        self.tray.setToolTip(APP_NAME)

        self.menu = FadeMenu()
        self._show = QAction("Show", self.menu)
        self._hide = QAction("Hide", self.menu)
        self._close_row = _ToggleRow("Close to tray")
        self._close_row.setToolTip("Closing the window keeps Ping Monitor running in the tray.")
        self._close_to_tray = QWidgetAction(self.menu)
        self._close_to_tray.setDefaultWidget(self._close_row)
        self._exit = QAction("Exit", self.menu)
        self._show.triggered.connect(self.showRequested)
        self._hide.triggered.connect(self.hideRequested)
        self._close_row.checkbox.toggled.connect(self.closeToTrayToggled)
        self._exit.triggered.connect(self.quitRequested)
        for action in (self._show, self._hide, self._close_to_tray):
            self.menu.addAction(action)
        self.menu.addSeparator()
        self.menu.addAction(self._exit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_window_visible(self, visible: bool) -> None:
        self._show.setEnabled(not visible)
        self._hide.setEnabled(visible)

    def set_close_to_tray(self, enabled: bool) -> None:
        checkbox = self._close_row.checkbox
        checkbox.blockSignals(True)
        checkbox.setChecked(enabled)
        checkbox.blockSignals(False)

    def set_status(self, status: HealthStatus, lines: list[str]) -> None:
        if status != self._status:
            self._status = status
            self.tray.setIcon(self._icons[status])
        title = APP_NAME if status is HealthStatus.UNKNOWN else f"{APP_NAME}: {status.label}"
        text = title
        for line in lines:
            candidate = f"{text}\n{line}"
            if len(candidate) > WINDOWS_TOOLTIP_LIMIT:
                break
            text = candidate
        if self.tray.toolTip() != text:
            self.tray.setToolTip(text)

    def notify(self, title: str, message: str, warning: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, message, icon, 4000)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._hide.isEnabled():
                self.hideRequested.emit()
            else:
                self.showRequested.emit()
