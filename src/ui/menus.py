"""
Popup menus that fade in (instead of popping) with rounded, compact styling.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QMenu, QWidget

from src.ui.theme import THEME


class FadeMenu(QMenu):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Everything in these menus is an action, so the whole popup is "clickable".
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event) -> None:
        duration = THEME.duration(140)
        if duration:
            self.setWindowOpacity(0.0)
        super().showEvent(event)
        if duration:
            self._fade.stop()
            self._fade.setDuration(duration)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
