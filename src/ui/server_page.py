"""
One server: header with status, the pulse chart, the ping stream and stats.
"""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from src.core.models import HealthStatus, PingResult
from src.core.stats import STATUS_HIT_THRESHOLD, STATUS_WINDOW_SECONDS, ServerHistory
from src.ui.controls import Tween, fade
from src.ui.latency_chart import LatencyChart, window_label
from src.ui.ping_stream import PingStream
from src.ui.theme import THEME, mix


def format_ms(value: float | None) -> str:
    if value is None:
        return "–"
    if value < 1:
        return "<1 ms"
    return f"{round(value)} ms"


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 120:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min"


class StatusPill(QWidget):
    """Dot + label (never color alone); cross-fades between states."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = HealthStatus.UNKNOWN
        self._previous = HealthStatus.UNKNOWN
        self._tween = Tween(self, self.update, value=1.0, duration=THEME.SLOW)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        THEME.changed.connect(self.updateGeometry)

    def set_status(self, status: HealthStatus, thresholds: tuple[int, int]) -> None:
        healthy, degraded = thresholds
        minutes = STATUS_WINDOW_SECONDS // 60
        self.setToolTip(
            f"Healthy: fewer than {STATUS_HIT_THRESHOLD} pings above {healthy} ms in the last {minutes} minutes.\n"
            f"Degraded: {STATUS_HIT_THRESHOLD}+ pings above {healthy} ms.\n"
            f"Failing: {STATUS_HIT_THRESHOLD}+ pings above {degraded} ms or lost."
        )
        if status == self._status:
            return
        self._previous = self._status
        self._status = status
        self._tween.jump(0.0)
        self._tween.to(1.0)
        self.updateGeometry()

    def _font(self) -> QFont:
        return THEME.font(12.5, QFont.Weight.DemiBold)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self._font())
        width = THEME.px(12) + THEME.px(8) + THEME.px(8) + metrics.horizontalAdvance(self._status.label) + THEME.px(14)
        return QSize(width, THEME.px(28))

    def paintEvent(self, _event) -> None:
        t = self._tween.value
        fill = mix(THEME.health_color(self._previous), THEME.health_color(self._status), t)
        ink = mix(THEME.health_color(self._previous, True), THEME.health_color(self._status, True), t)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        background = QColor(fill)
        background.setAlphaF(0.14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        radius = THEME.px(4)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(rect.left() + THEME.px(12), rect.center().y() - radius, 2 * radius, 2 * radius))
        painter.setFont(self._font())
        painter.setPen(ink)
        painter.drawText(rect.adjusted(THEME.px(12) + 2 * radius + THEME.px(8), 0, 0, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status.label)


class StatsBar(QWidget):
    """Window statistics (label above value) and the session summary on the right."""

    ITEMS = ("Best", "Average", "Worst", "Jitter", "Loss", "Spikes")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values = {name: "–" for name in self.ITEMS}
        self._session_label = "Session"
        self._session_value = "–"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        THEME.changed.connect(self._theme_changed)
        self._theme_changed()

    def _theme_changed(self) -> None:
        self.setFixedHeight(THEME.px(46))
        self.update()

    def set_values(self, values: dict[str, str], session_label: str, session_value: str) -> None:
        if values == self._values and session_value == self._session_value and session_label == self._session_label:
            return
        self._values = values
        self._session_label = session_label
        self._session_value = session_value
        self.update()

    def paintEvent(self, _event) -> None:
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        label_font = THEME.font(11.5, QFont.Weight.Medium)
        value_font = THEME.font(15, QFont.Weight.DemiBold, tabular=True)
        label_metrics = QFontMetrics(label_font)
        value_metrics = QFontMetrics(value_font)
        top = (self.height() - label_metrics.height() - value_metrics.height() - THEME.px(2)) / 2
        x = float(THEME.px(4))
        column = THEME.px(92)
        session_width = max(value_metrics.horizontalAdvance(self._session_value),
                            label_metrics.horizontalAdvance(self._session_label)) + THEME.px(6)
        limit = self.width() - session_width - THEME.px(24)
        for name in self.ITEMS:
            if x + column > limit:
                break
            painter.setFont(label_font)
            painter.setPen(QColor(c.ink3))
            painter.drawText(QRectF(x, top, column, label_metrics.height()), Qt.AlignmentFlag.AlignLeft, name)
            painter.setFont(value_font)
            painter.setPen(QColor(c.ink))
            painter.drawText(QRectF(x, top + label_metrics.height() + THEME.px(2), column, value_metrics.height()),
                             Qt.AlignmentFlag.AlignLeft, self._values.get(name, "–"))
            x += column

        right = QRectF(self.width() - session_width, top, session_width, self.height() - top)
        painter.setFont(label_font)
        painter.setPen(QColor(c.ink3))
        painter.drawText(QRectF(right.left(), top, right.width(), label_metrics.height()),
                         Qt.AlignmentFlag.AlignRight, self._session_label)
        painter.setFont(value_font)
        painter.setPen(QColor(c.ink2))
        painter.drawText(QRectF(right.left(), top + label_metrics.height() + THEME.px(2), right.width(),
                                value_metrics.height()), Qt.AlignmentFlag.AlignRight, self._session_value)


class ServerPage(QWidget):
    def __init__(self, name: str, host: str, history: ServerHistory, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.host = host
        self.history = history

        self._title = QLabel(name, self)
        self._address = QLabel(host, self)
        self._paused = QLabel("Paused", self)
        self._paused_state = False
        self._paused.setToolTip("Pinging is paused. Resume with the play button or Ctrl+P.")
        self._paused.hide()
        self._pill = StatusPill(self)
        self.chart = LatencyChart(self)
        self.stream = PingStream(self)
        self.stats = StatsBar(self)

        header = QHBoxLayout()
        header.setSpacing(THEME.px(12))
        header.addWidget(self._title, 0, Qt.AlignmentFlag.AlignBaseline)
        header.addWidget(self._address, 0, Qt.AlignmentFlag.AlignBaseline)
        header.addStretch(1)
        header.addWidget(self._paused, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._pill, 0, Qt.AlignmentFlag.AlignVCenter)

        self._layout = QVBoxLayout(self)
        self._layout.addLayout(header)
        self._layout.addWidget(self.chart)
        self._layout.addWidget(self.stream, 1)
        self._layout.addWidget(self.stats)

        THEME.changed.connect(self._apply_theme)
        self._apply_theme()
        self.reload()

    def _apply_theme(self) -> None:
        c = THEME.colors
        self._layout.setContentsMargins(THEME.px(24), THEME.px(18), THEME.px(24), THEME.px(14))
        self._layout.setSpacing(THEME.px(12))
        self._title.setFont(THEME.font(20, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {c.ink};")
        self._address.setFont(THEME.font(13, QFont.Weight.Medium))
        self._address.setStyleSheet(f"color: {c.ink3};")
        self._paused.setFont(THEME.font(12.5, QFont.Weight.DemiBold))
        self._paused.setStyleSheet(
            f"color: {c.ink2}; background: {c.raised}; border: 1px solid {c.hairline};"
            f" border-radius: {THEME.px(14)}px; padding: {THEME.px(4)}px {THEME.px(12)}px;")
        self._fit_chart()

    def _fit_chart(self) -> None:
        """A taller window gives the chart some of the extra room (the stream gets
        the rest); text keeps its size."""
        height = max(THEME.px(160), min(THEME.px(300), round(self.height() * 0.22)))
        if height != self.chart.height():
            self.chart.setFixedHeight(height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_chart()

    def set_paused(self, paused: bool) -> None:
        # Compare with the wanted state: isVisible() is False on hidden tabs and
        # still True while the badge fades out.
        if paused != self._paused_state:
            self._paused_state = paused
            fade(self._paused, paused, THEME.NORMAL)

    # -------------------------------------------------------------- updates
    def reload(self) -> None:
        """Rebuild everything from the history (after reset / settings change)."""
        healthy, degraded = self.history.thresholds
        self.stream.model.set_thresholds(healthy, degraded)
        self.stream.model.reset_rows(self.history.results)
        self.chart.set_history(self.history)
        self.refresh_summary()

    def append(self, result: PingResult, evicted: int) -> None:
        self.stream.model.append(result, evicted)
        if self.isVisible():
            self.chart.notify_new_result()
            self.refresh_summary()
        else:
            self.chart.invalidate()

    def refresh_summary(self) -> None:
        history = self.history
        self._pill.set_status(history.health(), history.thresholds)
        stats = history.window_stats()
        loss = "–" if not stats.samples else (f"{stats.loss_percent:.1f} %" if stats.lost else "0 %")
        values = {
            "Best": format_ms(stats.best),
            "Average": format_ms(stats.average),
            "Worst": format_ms(stats.worst),
            "Jitter": format_ms(stats.jitter) if stats.jitter is not None else "–",
            "Loss": loss,
            "Spikes": format_count(stats.spikes) if stats.samples else "–",
        }
        counters = history.counters
        if counters.pings:
            noun = "ping" if counters.pings == 1 else "pings"
            session = f"{format_count(counters.pings)} {noun} in {format_duration(counters.elapsed_seconds)}"
        else:
            session = "No pings yet"
        self.stats.set_values(values, "This session", session)
        self.stats.setToolTip(f"Best, average, worst, jitter, loss and spikes cover: "
                              f"{window_label(history.preserved_minutes).lower()}.")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.chart.invalidate()
        self.refresh_summary()
