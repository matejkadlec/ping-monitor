"""
Toast notifications: slide in from the right edge of the window, stay for a
few seconds (paused while hovered), then glide out. Types: success, warning,
error, info.
"""

from PySide6.QtCore import QElapsedTimer, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from src.ui import icons
from src.ui.controls import Tween
from src.ui.theme import THEME

KINDS = {
    "success": ("circle-check", "good"),
    "warning": ("triangle-alert", "warn"),
    "error": ("circle-x", "bad"),
    "info": ("info", "accent"),
}
DEFAULT_DURATION_MS = 3200
MAX_TOASTS = 4


class Toast(QWidget):
    def __init__(self, manager: "ToastManager", message: str, kind: str, duration_ms: int) -> None:
        super().__init__(manager.host)
        self.manager = manager
        self.message = message
        self.kind = kind if kind in KINDS else "info"
        self.duration_ms = duration_ms
        self._elapsed_before_pause = 0
        self._clock = QElapsedTimer()
        self._closing = False
        self._presence = Tween(self, self._presence_changed, value=0.0, duration=260)
        self._y = Tween(self, self._reposition, value=0.0, duration=THEME.NORMAL)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to dismiss")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(THEME.px(32))
        shadow.setOffset(0, THEME.px(8))
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)
        self.resize(self.sizeHint())

    # -------------------------------------------------------------- layout
    def _font(self) -> QFont:
        return THEME.font(13, QFont.Weight.Medium)

    def sizeHint(self) -> QSize:
        width = THEME.px(340)
        text_width = width - THEME.px(16 + 20 + 12 + 16)
        metrics = QFontMetrics(self._font())
        text_rect = metrics.boundingRect(0, 0, text_width, 1000, int(Qt.TextFlag.TextWordWrap), self.message)
        return QSize(width, max(THEME.px(52), text_rect.height() + THEME.px(30)))

    def target_y(self) -> float:
        return self._y.value

    def move_to_slot(self, y: float, animate: bool = True) -> None:
        if animate:
            self._y.to(y)
        else:
            self._y.jump(y)

    def _reposition(self) -> None:
        host = self.manager.host
        margin = THEME.px(18)
        slide = (1.0 - self._presence.value) * THEME.px(36)
        x = host.width() - self.width() - margin + round(slide)
        self.move(QPoint(x, round(self._y.value)))

    def _presence_changed(self) -> None:
        self._reposition()
        self.update()
        if self._closing and self._presence.value <= 0.001:
            self.manager._remove(self)

    # ------------------------------------------------------------ lifetime
    def appear(self) -> None:
        self.show()
        self.raise_()
        self._presence.to(1.0)
        self._clock.start()
        self._timer.start()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._presence.to(0.0, 180)
        if THEME.duration(180) <= 0:
            self.manager._remove(self)

    def _remaining_fraction(self) -> float:
        elapsed = self._elapsed_before_pause + (self._clock.elapsed() if self._clock.isValid() else 0)
        return max(0.0, 1.0 - elapsed / max(1, self.duration_ms))

    def _tick(self) -> None:
        if self._remaining_fraction() <= 0:
            self.dismiss()
        self.update()

    def enterEvent(self, event) -> None:
        if self._clock.isValid():
            self._elapsed_before_pause += self._clock.elapsed()
            self._clock.invalidate()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._closing:
            self._clock.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.dismiss()
        event.accept()

    # --------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        c = THEME.colors
        icon_name, color_key = KINDS[self.kind]
        tone = QColor(getattr(c, color_key))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._presence.value)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = THEME.px(12)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(c.raised))
        painter.setPen(QPen(QColor("#253A5E"), 1))
        painter.drawPath(path)

        painter.save()
        painter.setClipPath(path)
        accent = QRectF(rect.left(), rect.top(), THEME.px(4), rect.height())
        painter.fillRect(accent, tone)
        remaining = self._remaining_fraction()
        bar = QColor(tone)
        bar.setAlphaF(0.45)
        painter.fillRect(QRectF(rect.left(), rect.bottom() - THEME.px(2), rect.width() * remaining, THEME.px(2)), bar)
        painter.restore()

        icon_size = THEME.px(20)
        icon_rect = QRectF(rect.left() + THEME.px(16), rect.center().y() - icon_size / 2, icon_size, icon_size)
        icons.paint(painter, icon_name, icon_rect, tone)
        painter.setFont(self._font())
        painter.setPen(QColor(c.ink))
        text_rect = QRectF(icon_rect.right() + THEME.px(12), rect.top(),
                           rect.right() - icon_rect.right() - THEME.px(28), rect.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                         | int(Qt.TextFlag.TextWordWrap), self.message)


class ToastManager:
    """Stacks toasts in the top-right corner of ``host`` (newest on top)."""

    def __init__(self, host: QWidget) -> None:
        self.host = host
        self._toasts: list[Toast] = []

    def show(self, message: str, kind: str = "info", duration_ms: int = DEFAULT_DURATION_MS) -> None:
        for toast in self._toasts:  # avoid stacking duplicates of the same message
            if toast.message == message and not toast._closing:
                toast._elapsed_before_pause = 0
                if toast._clock.isValid():  # not paused by the mouse: count again from now
                    toast._clock.start()
                toast.update()
                return
        toast = Toast(self, message, kind, duration_ms)
        self._toasts.insert(0, toast)
        toast.move_to_slot(THEME.px(18), animate=False)
        self._relayout(skip=toast)
        toast.appear()
        while len([t for t in self._toasts if not t._closing]) > MAX_TOASTS:
            [t for t in self._toasts if not t._closing][-1].dismiss()

    def success(self, message: str) -> None:
        self.show(message, "success")

    def warning(self, message: str) -> None:
        self.show(message, "warning")

    def error(self, message: str) -> None:
        self.show(message, "error", 4200)

    def raise_all(self) -> None:
        for toast in self._toasts:
            toast.raise_()

    def _relayout(self, skip: Toast | None = None) -> None:
        y = THEME.px(18)
        for toast in self._toasts:
            if toast is not skip:
                toast.move_to_slot(y)
            y += toast.height() + THEME.px(10)

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            toast.hide()
            toast.deleteLater()
            self._relayout()

    def reposition(self) -> None:
        for toast in self._toasts:
            toast._reposition()
