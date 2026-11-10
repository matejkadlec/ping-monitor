"""
The pulse: a live latency line for one server.

Static layers (grid, thresholds, area, line, spikes, losses) are rendered into
a cached pixmap once per new ping; animation frames only blit that pixmap and
draw the sonar ring that ripples out of the newest point.
"""

import bisect
import math

from PySide6.QtCore import QElapsedTimer, QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.core.models import LatencyLevel, PingResult, PingStatus, classify_latency
from src.core.stats import ServerHistory
from src.ui.theme import THEME

RING_MS = 900  # shorter than the usual 1 s interval, so the chart rests between pings
RING_FRAME_MS = 33  # a soft ripple: 30 fps is plenty

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
        self._ring_clock = QElapsedTimer()
        self._ring_curve = QEasingCurve(QEasingCurve.Type.OutCubic)
        self._ring = QTimer(self)
        self._ring.setInterval(RING_FRAME_MS)
        self._ring.timeout.connect(self._ring_tick)
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
            self._ring_clock.start()
            self._ring.start()

    def _ring_progress(self) -> float:
        if not self._ring.isActive():
            return 1.0
        return self._ring_curve.valueForProgress(min(1.0, self._ring_clock.elapsed() / RING_MS))

    def _ring_tick(self) -> None:
        if self._ring_clock.elapsed() >= RING_MS:
            self._ring.stop()
        self._update_head()

    def _update_head(self) -> None:
        """Animation frames only repaint the area around the newest point."""
        if self._head is None:
            self.update()
            return
        reach = THEME.px(5) + THEME.px(20) + 3
        point = self._head[0]
        self.update(QRectF(point.x() - reach, point.y() - reach, 2 * reach, 2 * reach).toAlignedRect())

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
        self.setFixedHeight(max(self.height(), THEME.px(160)))
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

        # Plain floats: this runs once per ping over up to an hour of results.
        plot_left, plot_top = plot.left(), plot.top()
        plot_width, plot_height, plot_bottom = plot.width(), plot.height(), plot.bottom()
        x_scale = plot_width / span
        y_scale = plot_height / top

        def x_of(epoch: float) -> float:
            return plot_left + (epoch - start) * x_scale

        def y_of(value: float) -> float:
            return plot_bottom - min(value, top) * y_scale

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

        # One pass: loss/gap bands, line segments decimated to one point per
        # pixel column (keeping the worst value) and the hover targets.
        gap_color = QColor(c.neutral)
        gap_color.setAlphaF(0.16)
        loss_color = QColor(c.bad)
        loss_color.setAlphaF(0.30)
        slot = max(1.5, plot_width / max(1, len(results)))
        loss_band: list[float] | None = None  # [x0, x1] of consecutive losses
        segments: list[list[tuple[float, float]]] = []
        segment: list[tuple[float, float]] | None = None
        columns: dict[int, tuple[float, PingResult]] = {}
        last_column = None
        ok, gap = PingStatus.OK, PingStatus.GAP
        for result in results:
            status, rtt = result.status, result.rtt_ms
            x = plot_left + (result.epoch - start) * x_scale
            if status is not ok or rtt is None:
                segment = None
                if status is gap:
                    painter.fillRect(QRectF(x, plot_top, max(1.5, result.gap_seconds * x_scale), plot_height),
                                     gap_color)
                elif status.is_lost:
                    x0, x1 = x - slot / 2, x - slot / 2 + max(2.0, slot)
                    if loss_band is not None and x0 <= loss_band[1] + 1.0:
                        loss_band[1] = x1
                    else:
                        if loss_band is not None:
                            painter.fillRect(QRectF(loss_band[0], plot_top, loss_band[1] - loss_band[0],
                                                    plot_height), loss_color)
                        loss_band = [x0, x1]
                continue
            y = plot_bottom - (rtt if rtt < top else top) * y_scale
            column = int(x)
            if segment is None:
                segment = [(x, y)]
                segments.append(segment)
            elif column == last_column:
                if y < segment[-1][1]:
                    segment[-1] = (segment[-1][0], y)
            else:
                segment.append((x, y))
            last_column = column
            best = columns.get(column)
            if best is None or y < best[0]:
                columns[column] = (y, result)
        if loss_band is not None:
            painter.fillRect(QRectF(loss_band[0], plot_top, loss_band[1] - loss_band[0], plot_height), loss_color)

        accent = QColor(c.accent)
        gradient = QLinearGradient(0, plot_top, 0, plot_bottom)
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
            if len(points) == 1:
                x, y = points[0]
                points = [(x, y), (x + 1.5, y)]
            line = QPolygonF([QPointF(x, y) for x, y in points])
            area = QPolygonF(line)
            area.append(QPointF(points[-1][0], plot_bottom))
            area.append(QPointF(points[0][0], plot_bottom))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPolygon(area)
            painter.setPen(line_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(line)

        # One hover target per pixel column (the worst ping in it).
        for column in sorted(columns):
            y, result = columns[column]
            self._points.append((x_of(result.epoch), y, result))
        self._xs = [point[0] for point in self._points]

        # Spikes: red dots with a ring in the surface color.
        dot = THEME.px(3.5)
        spike_pen = QPen(QColor(c.deep), 2)
        for y, result in columns.values():
            if result.rtt_ms is not None and result.rtt_ms > degraded:
                painter.setPen(spike_pen)
                painter.setBrush(QColor(c.bad))
                painter.drawEllipse(QPointF(x_of(result.epoch), y), dot, dot)

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
            progress = self._ring_progress()
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
