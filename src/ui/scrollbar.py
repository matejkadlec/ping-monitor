"""
Slim, custom-painted vertical scrollbar.

* As soon as there is something to scroll, the whole bar fades in with both
  arrows visible; clicking an arrow glides all the way to the top / bottom,
  with a pointer cursor while hovering it. Its space is always reserved, so
  the rows never jump sideways when it appears.
* The handle widens softly on hover and is drawn the same from the very first
  frame (no native Windows overlay-scrollbar quirks).
* Programmatic scrolling can glide (``glide_to``) instead of jumping.
* The mouse wheel over the bar scrolls like the wheel over the list
  (``wheel_handler``).
"""

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QScrollBar, QWidget

from src.ui import icons
from src.ui.controls import Tween, connect_running
from src.ui.theme import THEME, mix


class SmoothScrollBar(QScrollBar):
    glideFinished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._hover = Tween(self, self.update)
        self._presence = Tween(self, self.update, duration=THEME.NORMAL)
        self._zone: str | None = None
        self._drag_offset: float | None = None
        self._glide_target: int | None = None
        self._glide = QVariantAnimation(self)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        connect_running(self._glide, lambda v: self.setValue(round(float(v))))
        self._glide.finished.connect(self._glide_finished)
        self.wheel_handler = None  # set by the view: same wheel speed over the bar
        self.rangeChanged.connect(self._range_changed)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        THEME.changed.connect(self.updateGeometry)

    def has_range(self) -> bool:
        return self.maximum() > self.minimum()

    def _range_changed(self, minimum: int, maximum: int) -> None:
        self._presence.to(1.0 if maximum > minimum else 0.0)
        if maximum <= minimum and self._zone is not None:
            self._zone = None
            self.unsetCursor()

    # -------------------------------------------------------------- geometry
    def sizeHint(self) -> QSize:
        return QSize(THEME.px(14), THEME.px(120))

    def _arrow_height(self) -> float:
        return THEME.px(16)

    def _rects(self) -> tuple[QRectF, QRectF, QRectF, QRectF]:
        width, height = float(self.width()), float(self.height())
        arrow = self._arrow_height()
        up = QRectF(0, 0, width, arrow)
        down = QRectF(0, height - arrow, width, arrow)
        track = QRectF(0, arrow + 2, width, max(0.0, height - 2 * arrow - 4))
        span = self.maximum() - self.minimum()
        if span <= 0 or track.height() <= 0:
            return up, down, track, QRectF(track)
        length = max(THEME.px(28), track.height() * self.pageStep() / (span + self.pageStep()))
        length = min(length, track.height())
        position = track.top() + (track.height() - length) * (self.value() - self.minimum()) / span
        return up, down, track, QRectF(0, position, width, length)

    def _zone_at(self, point: QPointF) -> str | None:
        if not self.has_range():
            return None  # nothing to scroll: the bar is invisible and inert
        up, down, track, handle = self._rects()
        if up.contains(point):
            return "up"
        if down.contains(point):
            return "down"
        if handle.contains(point):
            return "handle"
        if track.contains(point):
            return "track"
        return None

    # --------------------------------------------------------------- gliding
    @property
    def glide_target(self) -> int:
        return self._glide_target if self._glide_target is not None else self.value()

    def glide_to(self, value: int, duration: int | None = None) -> None:
        value = max(self.minimum(), min(self.maximum(), int(value)))
        start = self.value()
        self._glide.stop()
        ms = THEME.duration(duration if duration is not None else 240)
        if ms <= 0 or value == start:
            self._glide_target = None
            self.setValue(value)
            return
        self._glide_target = value
        self._glide.setDuration(ms)
        self._glide.setStartValue(float(start))
        self._glide.setEndValue(float(value))
        self._glide.start()

    def stop_glide(self) -> None:
        self._glide.stop()
        self._glide_target = None

    def is_gliding(self) -> bool:
        return self._glide.state() == QVariantAnimation.State.Running

    def _glide_finished(self) -> None:
        self._glide_target = None
        self.glideFinished.emit()

    # ----------------------------------------------------------------- input
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        zone = self._zone_at(point)
        if zone == "up":
            self.glide_to(self.minimum(), 320)
        elif zone == "down":
            self.glide_to(self.maximum(), 320)
        elif zone == "handle":
            self.stop_glide()
            _, _, _, handle = self._rects()
            self._drag_offset = point.y() - handle.top()
            self.setSliderDown(True)
        elif zone == "track":
            _, _, _, handle = self._rects()
            step = self.pageStep() if point.y() > handle.bottom() else -self.pageStep()
            self.glide_to(self.glide_target + step)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        point = event.position()
        if self._drag_offset is not None:
            _, _, track, handle = self._rects()
            free = track.height() - handle.height()
            if free > 0:
                ratio = (point.y() - self._drag_offset - track.top()) / free
                ratio = max(0.0, min(1.0, ratio))
                self.setValue(round(self.minimum() + ratio * (self.maximum() - self.minimum())))
            event.accept()
            return
        zone = self._zone_at(point)
        if zone != self._zone:
            self._zone = zone
            self.setCursor(Qt.CursorShape.PointingHandCursor if zone in ("up", "down")
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.setSliderDown(False)
        event.accept()

    def wheelEvent(self, event) -> None:
        if self.wheel_handler is not None:
            self.wheel_handler(event)
        else:
            super().wheelEvent(event)

    def enterEvent(self, event) -> None:
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        self._zone = None
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        presence = self._presence.value
        if presence <= 0.001:
            return
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(presence)
        up, down, track, handle = self._rects()
        hover = self._hover.value
        dragging = self._drag_offset is not None

        arrow_size = THEME.px(12)
        for rect, name, zone, enabled in (
            (up, "chevron-up", "up", self.value() > self.minimum()),
            (down, "chevron-down", "down", self.value() < self.maximum()),
        ):
            color = QColor(c.ink if self._zone == zone else c.ink3)
            if not enabled:
                color.setAlphaF(0.35)
            icon_rect = QRectF(0, 0, arrow_size, arrow_size)
            icon_rect.moveCenter(rect.center())
            icons.paint(painter, name, icon_rect, color, stroke=2.4)

        width = THEME.px(5) + (THEME.px(8) - THEME.px(5)) * max(hover, 1.0 if dragging else 0.0)
        bar = QRectF(0, handle.top(), width, handle.height())
        bar.moveCenter(QPointF(handle.center().x(), handle.center().y()))
        active = self._zone == "handle" or dragging
        color = mix("#2A3D5E", "#3D5683", 1.0 if active else hover * 0.6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(bar, width / 2, width / 2)
