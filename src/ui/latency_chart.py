"""
The pulse: a live latency line for one server.

Static layers (grid, thresholds, area, line, spikes, losses) are rendered into
a cached pixmap once per new ping; animation frames only blit that pixmap and
draw the sonar ring that ripples out of the newest point.
"""

import bisect
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, QEasingCurve
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.core.models import LatencyLevel, PingResult, PingStatus, classify_latency
from src.core.stats import ServerHistory
from src.ui.theme import THEME

_NICE_STEPS = (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000)


def nice_ceiling(value: float) -> tuple[int, int]:
    """Top of the y axis and the gridline step for a maximum ``value``."""
    for step in _NICE_STEPS:
        top = step * math.ceil(value / step)
        if top / step <= 4:
            return int(top), step
    step = _NICE_STEPS[-1]
    return int(step * math.ceil(value / step)), step


# The chart never shows more than an hour, so "keep everything" stays fast.
CHART_MAX_MINUTES = 60


def chart_minutes(preserved_minutes: int) -> int:
    if preserved_minutes <= 0:
        return CHART_MAX_MINUTES
    return min(preserved_minutes, CHART_MAX_MINUTES)


def window_label(minutes: int) -> str:
    if minutes <= 0:
        return "Whole session"
    if minutes == 1:
        return "Last minute"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "Last hour" if hours == 1 else f"Last {hours} hours"
    return f"Last {minutes} minutes"


class LatencyChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history: ServerHistory | None = None
        self._cache: QPixmap | None = None
        self._points: list[tuple[float, float, PingResult]] = []  # x, y, result
        self._xs: list[float] = []
        self._head: tuple[QPointF, PingResult] | None = None
        self._hover_x: float | None = None
        self._plot = QRectF()
        self._ring = QVariantAnimation(self)
        self._ring.setStartValue(0.0)
        self._ring.setEndValue(1.0)
        self._ring.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._ring.valueChanged.connect(lambda _v: self.update())
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(THEME.px(120))
        THEME.changed.connect(self._theme_changed)

    # --------------------------------------------------------------- public
    def set_history(self, history: ServerHistory | None) -> None:
        self._history = history
        self.invalidate()

    def invalidate(self) -> None:
        self._cache = None
        self.update()

    def notify_new_result(self) -> None:
        self.invalidate()
        if self.isVisible() and not self.window().isMinimized() and THEME.ambient_active \
                and self._history and self._history.last_result \
                and self._history.last_result.status is PingStatus.OK:
            self._ring.stop()
            self._ring.setDuration(1100)
            self._ring.start()

    def sizeHint(self) -> QSize:
        return QSize(THEME.px(800), THEME.px(160))

    # ---------------------------------------------------------------- input
    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        self._hover_x = x if self._plot.left() <= x <= self._plot.right() else None
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        self._cache = None
        super().resizeEvent(event)

    def _theme_changed(self) -> None:
        self.setFixedHeight(THEME.px(160))
        self.invalidate()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        ratio = self.devicePixelRatioF()
        if self._cache is None or self._cache.size() != self.size() * ratio:
            self._cache = self._render_static(ratio)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._cache)
        self._paint_head(painter)
        self._paint_hover(painter)

    def _render_static(self, ratio: float) -> QPixmap:
        c = THEME.colors
        pixmap = QPixmap(self.size() * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = THEME.px(12)
        painter.setPen(QPen(QColor(c.hairline), 1))
        painter.setBrush(QColor(c.deep))
        painter.drawRoundedRect(panel, radius, radius)

        history = self._history
        minutes = chart_minutes(history.preserved_minutes if history else 10)
        title_font = THEME.font(12, QFont.Weight.Medium)
        painter.setFont(title_font)
        painter.setPen(QColor(c.ink3))
        title_rect = QRectF(THEME.px(16), THEME.px(10), self.width() / 2, THEME.px(18))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         window_label(minutes))

        axis_font = THEME.font(11, tabular=True)
        axis_metrics = QFontMetrics(axis_font)
        left = THEME.px(16) + axis_metrics.horizontalAdvance("1000") + THEME.px(8)
        plot = QRectF(left, THEME.px(38), self.width() - left - THEME.px(84),
                      self.height() - THEME.px(38) - THEME.px(14))
        self._plot = plot
        self._points = []
        self._xs = []
        self._head = None

        results: list[PingResult] = []
        if history and history.results:
            # Only walk the visible window (newest first), never the whole history.
            window_start = history.results[-1].epoch - minutes * 60
            for result in reversed(history.results):
                if result.epoch < window_start:
                    break
                results.append(result)
            results.reverse()
        if not results or plot.width() <= 10 or plot.height() <= 10:
            painter.setFont(THEME.font(13))
            painter.setPen(QColor(c.ink3))
            painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, "Waiting for the first ping…")
            painter.end()
            return pixmap

        healthy, degraded = history.thresholds
        end = results[-1].epoch
        start = end - minutes * 60
        span = max(1.0, end - start)

        rtts = sorted(r.rtt_ms for r in results if r.status is PingStatus.OK and r.rtt_ms is not None)
        reference = rtts[int(0.98 * (len(rtts) - 1))] if rtts else 0
        top, step = nice_ceiling(max(degraded * 1.4, reference * 1.15, 10))

        def x_of(epoch: float) -> float:
            return plot.left() + plot.width() * ((epoch - start) / span)

        def y_of(value: float) -> float:
            return plot.bottom() - plot.height() * min(value, top) / top

        # Gridlines + axis labels (solid hairlines).
        painter.setFont(axis_font)
        for value in range(0, top + 1, step):
            y = y_of(value)
            painter.setPen(QPen(QColor(c.grid), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(c.ink3))
            painter.drawText(QRectF(THEME.px(8), y - THEME.px(8), left - THEME.px(16), THEME.px(16)),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(value))

        # Threshold lines are real thresholds, so they are dashed and labelled.
        for value, color in ((healthy, c.warn), (degraded, c.bad)):
            if value >= top:
                continue
            y = y_of(value)
            pen = QPen(QColor(color))
            pen.setWidthF(1.0)
            pen.setDashPattern([3, 4])
            line_color = QColor(color)
            line_color.setAlphaF(0.55)
            pen.setColor(line_color)
            painter.setPen(pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(c.ink3))
            painter.drawText(QRectF(plot.right() + THEME.px(8), y - THEME.px(8), THEME.px(70), THEME.px(16)),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{value} ms")

        # Losses and gaps as vertical bands.
        slot = max(1.5, plot.width() / max(1, len(results)))
        for result in results:
            if result.status is PingStatus.GAP:
                x0 = x_of(result.epoch)
                x1 = x_of(result.epoch + result.gap_seconds)
                band = QColor(c.neutral)
                band.setAlphaF(0.16)
                painter.fillRect(QRectF(x0, plot.top(), max(1.5, x1 - x0), plot.height()), band)
            elif result.status.is_lost:
                band = QColor(c.bad)
                band.setAlphaF(0.30)
                x = x_of(result.epoch)
                painter.fillRect(QRectF(x - slot / 2, plot.top(), max(2.0, slot), plot.height()), band)

        # Decimate to one point per pixel column (keeping the worst value).
        columns: dict[int, tuple[float, PingResult]] = {}
        segments: list[list[QPointF]] = [[]]
        last_column = None
        for result in results:
            if result.status is not PingStatus.OK or result.rtt_ms is None:
                if segments[-1]:
                    segments.append([])
                last_column = None
                continue
            x = x_of(result.epoch)
            column = int(x)
            if column == last_column and segments[-1]:
                previous = segments[-1][-1]
                if y_of(result.rtt_ms) < previous.y():
                    segments[-1][-1] = QPointF(previous.x(), y_of(result.rtt_ms))
            else:
                segments[-1].append(QPointF(x, y_of(result.rtt_ms)))
            last_column = column
            if column not in columns or y_of(result.rtt_ms) < columns[column][0]:
                columns[column] = (y_of(result.rtt_ms), result)

        accent = QColor(c.accent)
        gradient = QLinearGradient(0, plot.top(), 0, plot.bottom())
        top_color = QColor(accent)
        top_color.setAlphaF(0.22)
        bottom_color = QColor(accent)
        bottom_color.setAlphaF(0.0)
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bottom_color)
        line_pen = QPen(accent)
        line_pen.setWidthF(2.0)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for points in segments:
            if not points:
                continue
            if len(points) == 1:
                points = [points[0], QPointF(points[0].x() + 1.5, points[0].y())]
            line = QPainterPath(points[0])
            for point in points[1:]:
                line.lineTo(point)
            area = QPainterPath(line)
            area.lineTo(points[-1].x(), plot.bottom())
            area.lineTo(points[0].x(), plot.bottom())
            area.closeSubpath()
            painter.fillPath(area, gradient)
            painter.setPen(line_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(line)

        # One hover target per pixel column (the worst ping in it).
        for column in sorted(columns):
            y, result = columns[column]
            self._points.append((x_of(result.epoch), y, result))
        self._xs = [point[0] for point in self._points]

        # Spikes: red dots with a ring in the surface color.
        dot = THEME.px(3.5)
        for y, result in columns.values():
            if result.rtt_ms is not None and result.rtt_ms > degraded:
                x = x_of(result.epoch)
                painter.setPen(QPen(QColor(c.deep), 2))
                painter.setBrush(QColor(c.bad))
                painter.drawEllipse(QPointF(x, y), dot, dot)

        last = results[-1]
        if last.status is PingStatus.OK and last.rtt_ms is not None:
            self._head = (QPointF(x_of(last.epoch), y_of(last.rtt_ms)), last)
        elif last.status is not PingStatus.GAP:
            self._head = (QPointF(x_of(last.epoch), plot.bottom()), last)
        painter.end()
        return pixmap

    def _paint_head(self, painter: QPainter) -> None:
        if self._head is None or self._history is None:
            return
        c = THEME.colors
        point, result = self._head
        healthy, degraded = self._history.thresholds
        level = classify_latency(result, healthy, degraded)
        color = THEME.level_color(level)
        if result.status is PingStatus.OK:
            progress = float(self._ring.currentValue() or 0.0) if self._ring.state() else 1.0
            if progress < 1.0:
                ring = QColor(color)
                ring.setAlphaF(0.55 * (1.0 - progress) ** 1.5)
                pen = QPen(ring)
                pen.setWidthF(1.6)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                radius = THEME.px(5) + THEME.px(20) * progress
                painter.drawEllipse(point, radius, radius)
            painter.setPen(QPen(QColor(c.deep), 2.5))
            painter.setBrush(color)
            radius = THEME.px(5)
            painter.drawEllipse(point, radius, radius)
            text = "<1 ms" if result.rtt_ms == 0 else f"{result.rtt_ms} ms"
            ink = QColor(c.ink)
        else:
            text = "Timeout" if result.status is PingStatus.TIMEOUT else "Lost"
            ink = THEME.level_color(LatencyLevel.LOST, text=True)
        font = THEME.font(15, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(ink)
        metrics = QFontMetrics(font)
        label_rect = QRectF(point.x() + THEME.px(12), point.y() - metrics.height() / 2,
                            metrics.horizontalAdvance(text) + 4, metrics.height())
        label_rect.moveTop(max(self._plot.top() - THEME.px(14),
                               min(label_rect.top(), self._plot.bottom() - label_rect.height())))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_hover(self, painter: QPainter) -> None:
        if self._hover_x is None or not self._points:
            return
        c = THEME.colors
        index = bisect.bisect_left(self._xs, self._hover_x)
        candidates = [i for i in (index - 1, index) if 0 <= i < len(self._points)]
        x, y, result = min((self._points[i] for i in candidates), key=lambda item: abs(item[0] - self._hover_x))
        hair = QColor(c.ink2)
        hair.setAlphaF(0.45)
        painter.setPen(QPen(hair, 1))
        painter.drawLine(QPointF(x, self._plot.top()), QPointF(x, self._plot.bottom()))
        healthy, degraded = self._history.thresholds if self._history else (40, 60)
        level = classify_latency(result, healthy, degraded)
        painter.setPen(QPen(QColor(c.deep), 2))
        painter.setBrush(THEME.level_color(level))
        painter.drawEllipse(QPointF(x, y), THEME.px(4.5), THEME.px(4.5))

        value = "<1 ms" if result.rtt_ms == 0 else f"{result.rtt_ms} ms"
        stamp = result.timestamp.strftime("%H:%M:%S")
        value_font = THEME.font(13, QFont.Weight.DemiBold)
        time_font = THEME.font(11.5, tabular=True)
        vm, tm = QFontMetrics(value_font), QFontMetrics(time_font)
        width = max(vm.horizontalAdvance(value), tm.horizontalAdvance(stamp)) + THEME.px(20)
        height = vm.height() + tm.height() + THEME.px(12)
        box = QRectF(x + THEME.px(10), self._plot.top(), width, height)
        if box.right() > self.width() - THEME.px(6):
            box.moveRight(x - THEME.px(10))
        painter.setPen(QPen(QColor(c.hairline), 1))
        painter.setBrush(QColor(c.raised))
        painter.drawRoundedRect(box, THEME.px(7), THEME.px(7))
        painter.setFont(value_font)
        painter.setPen(QColor(c.ink))
        painter.drawText(box.adjusted(THEME.px(10), THEME.px(6), 0, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, value)
        painter.setFont(time_font)
        painter.setPen(QColor(c.ink3))
        painter.drawText(box.adjusted(THEME.px(10), 0, 0, -THEME.px(6)),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, stamp)
