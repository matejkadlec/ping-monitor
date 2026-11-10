"""
The live ping stream: one row per ping, newest at the bottom.

A virtualized list (only visible rows are painted, fixed row height), so long
sessions stay smooth. New rows fade in from a soft highlight, the view follows the newest
row only while you are at the bottom, and a "Latest" pill brings you back.
"""

import time
from collections import OrderedDict, deque

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from src.core.models import LatencyLevel, PingResult, PingStatus, classify_latency
from src.ui.controls import TextButton, fade
from src.ui.fast_list import FastListView
from src.ui.scrollbar import SmoothScrollBar
from src.ui.theme import THEME, mix

RESULT_ROLE = Qt.ItemDataRole.UserRole + 1
FRESH_MS = 900.0
FRESH_FRAME_MS = 33  # the highlight is subtle: 30 fps is plenty


def format_line(result: PingResult) -> str:
    """Plain-text form used for copying (same format as the old app)."""
    stamp = result.timestamp.strftime("%H:%M:%S")
    if result.status is PingStatus.OK:
        return f"[{stamp}] {result.server}: {result.rtt_ms}ms"
    if result.status is PingStatus.GAP:
        return f"[{stamp}] {result.server}: no samples for {result.gap_seconds:g} s"
    if result.status is PingStatus.TIMEOUT:
        return f"[{stamp}] {result.server}: Request timeout"
    return f"[{stamp}] {result.server}: {result.detail or result.status.value}"


def describe(result: PingResult) -> str:
    """Short human text for non-OK rows."""
    if result.status is PingStatus.TIMEOUT:
        return "Request timed out"
    if result.status is PingStatus.UNREACHABLE:
        return result.detail or "Unreachable"
    if result.status is PingStatus.ERROR:
        return f"Error: {result.detail}" if result.detail else "Error"
    if result.status is PingStatus.GAP:
        cause = "a ping call hung or the PC was asleep" if result.detail == "slow-call" else "the PC was busy or asleep"
        return f"No samples for {result.gap_seconds:g} s ({cause})"
    return ""


class PingStreamModel(QAbstractListModel):
    # Emitted before the oldest ``count`` rows are dropped (Preserved Minutes).
    rowsAboutToBeEvicted = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: deque[PingResult] = deque()
        # id(result) -> time it was added, oldest first (rows are only appended).
        self._fresh: OrderedDict[int, float] = OrderedDict()
        self.thresholds = (40, 60)

    # Qt API
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        result = self._rows[index.row()]
        if role == RESULT_ROLE:
            return result
        if role == Qt.ItemDataRole.DisplayRole:
            return format_line(result)
        return None

    # updates
    def append(self, result: PingResult, evicted: int = 0) -> None:
        row = len(self._rows)
        self.prune_fresh()  # also while hidden, when nothing else prunes
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(result)
        self._fresh[id(result)] = time.monotonic()
        self.endInsertRows()
        if evicted:
            self.remove_front(evicted)

    def remove_front(self, count: int) -> None:
        count = min(count, len(self._rows))
        if count <= 0:
            return
        self.rowsAboutToBeEvicted.emit(count)
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        for _ in range(count):
            self._fresh.pop(id(self._rows.popleft()), None)
        self.endRemoveRows()

    def reset_rows(self, results) -> None:
        self.beginResetModel()
        self._rows = deque(results)
        self._fresh.clear()
        self.endResetModel()

    def set_thresholds(self, healthy: int, degraded: int) -> None:
        self.thresholds = (healthy, degraded)
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1))

    def freshness(self, result: PingResult) -> float:
        started = self._fresh.get(id(result))
        if started is None:
            return 0.0
        age = (time.monotonic() - started) * 1000
        if age >= FRESH_MS:
            del self._fresh[id(result)]
            return 0.0
        return 1.0 - age / FRESH_MS

    def prune_fresh(self) -> int:
        """Forget expired highlights (also of rows that were never painted, e.g.
        added while hidden); returns how many of the newest rows are still fresh."""
        fresh = self._fresh
        now = time.monotonic()
        while fresh:
            oldest = next(iter(fresh))
            if (now - fresh[oldest]) * 1000 < FRESH_MS:
                break
            del fresh[oldest]
        return len(fresh)

    def has_fresh_rows(self) -> bool:
        return self.prune_fresh() > 0


class PingStreamDelegate(QStyledItemDelegate):
    def __init__(self, model: PingStreamModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

    def row_height(self) -> int:
        return THEME.px(26)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), self.row_height())

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        result: PingResult = index.data(RESULT_ROLE)
        if result is None:
            return
        c = THEME.colors
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        fresh = self._model.freshness(result) if THEME.ambient_active else 0.0
        background = None
        if selected:
            background = QColor(c.accent)
            background.setAlphaF(0.20)
        elif fresh > 0:
            background = QColor(c.accent)
            background.setAlphaF(0.16 * fresh * fresh)
        elif hovered:
            background = QColor(c.raised_hover)
            background.setAlphaF(0.55)
        if background is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            radius = THEME.px(6)
            painter.drawRoundedRect(rect.adjusted(THEME.px(4), 1, -THEME.px(4), -1), radius, radius)

        mono = THEME.font(12.5, mono=True)
        mono_bold = THEME.font(12.5, QFont.Weight.Medium, mono=True)
        metrics = QFontMetrics(mono)
        x = rect.left() + THEME.px(16)
        center_rect = QRectF(x, rect.top(), rect.width() - x, rect.height())

        painter.setFont(mono)
        painter.setPen(QColor(c.ink3))
        stamp = result.timestamp.strftime("%H:%M:%S")
        time_width = metrics.horizontalAdvance("00:00:00")
        painter.drawText(center_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, stamp)
        x += time_width + THEME.px(22)

        healthy, degraded = self._model.thresholds
        level = classify_latency(result, healthy, degraded)
        if result.status is PingStatus.OK:
            value_width = metrics.horizontalAdvance("9999 ms")
            value_rect = QRectF(x, rect.top(), value_width, rect.height())
            text = "<1 ms" if result.rtt_ms == 0 else f"{result.rtt_ms} ms"
            painter.setFont(mono_bold)
            painter.setPen(THEME.level_color(level, text=True))
            painter.drawText(value_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            bar_x = x + value_width + THEME.px(16)
            bar_max = min(max(THEME.px(220), rect.width() * 0.34), rect.right() - bar_x - THEME.px(16))
            if bar_max > THEME.px(20):
                scale = max(1, degraded * 2)
                ratio = min(1.0, (result.rtt_ms or 0) / scale)
                bar_height = THEME.px(6)
                track = QRectF(bar_x, rect.center().y() - bar_height / 2, bar_max, bar_height)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c.grid))
                painter.drawRoundedRect(track, bar_height / 2, bar_height / 2)
                fill = QRectF(track)
                fill.setWidth(max(bar_height, bar_max * ratio))
                bar_color = THEME.level_color(level)
                if fresh > 0:
                    bar_color = mix(bar_color, QColor(bar_color).lighter(135), fresh)
                painter.setBrush(bar_color)
                painter.drawRoundedRect(fill, bar_height / 2, bar_height / 2)
        else:
            text_rect = QRectF(x, rect.top(), rect.right() - x - THEME.px(12), rect.height())
            painter.setFont(mono_bold if level is LatencyLevel.LOST else mono)
            painter.setPen(THEME.level_color(level, text=True))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(describe(result), Qt.TextElideMode.ElideRight,
                                                int(text_rect.width())))
        painter.restore()


class PingStreamView(FastListView):
    """List view with smooth wheel scrolling and follow-the-latest behaviour."""

    followChanged = Signal(bool)

    def __init__(self, model: PingStreamModel, parent=None) -> None:
        self._delegate = PingStreamDelegate(model)
        super().__init__(self._delegate.row_height, parent)
        self._delegate.setParent(self)
        self._model = model
        self._scrollbar = SmoothScrollBar(self)
        self._scrollbar.wheel_handler = self.wheelEvent
        self._following = True
        self._follow_on_show = True
        self._fresh_rows_painted = 0
        self.setModel(model)
        self.setItemDelegate(self._delegate)
        self.setVerticalScrollBar(self._scrollbar)
        # Always reserve the bar's space (it fades in when needed) so rows never shift.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.viewport().setAutoFillBackground(False)

        self._fresh_timer = QTimer(self)
        self._fresh_timer.setInterval(FRESH_FRAME_MS)
        self._fresh_timer.timeout.connect(self._tick_fresh)

        model.rowsAboutToBeEvicted.connect(self._before_evict)
        model.rowsAboutToBeInserted.connect(self._before_insert)
        model.rowsInserted.connect(self._after_insert)
        model.rowsAboutToBeRemoved.connect(self._before_remove)
        model.rowsRemoved.connect(self._after_remove)
        model.modelReset.connect(lambda: QTimer.singleShot(0, self, self.scroll_to_latest_instantly))
        self._scrollbar.valueChanged.connect(self._on_scrolled)
        self._scrollbar.glideFinished.connect(lambda: self._set_following(self._at_bottom()))
        self._scrollbar.rangeChanged.connect(self._on_range_changed)
        THEME.changed.connect(self._theme_changed)

    # --------------------------------------------------------------- follow
    @property
    def following(self) -> bool:
        return self._following

    def _set_following(self, value: bool) -> None:
        if value != self._following:
            self._following = value
            self.followChanged.emit(value)

    def _at_bottom(self) -> bool:
        bar = self._scrollbar
        return bar.glide_target >= bar.maximum() - self._delegate.row_height() // 2

    def _on_scrolled(self, _value: int) -> None:
        if self._scrollbar.isSliderDown() or not self._scrollbar.is_gliding():
            self._set_following(self._at_bottom())

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        if self._following and not self._scrollbar.isSliderDown():
            if self.isVisible():
                self._scrollbar.glide_to(maximum, 180)
            else:
                self._scrollbar.setValue(maximum)

    def scroll_to_latest(self) -> None:
        self._set_following(True)
        self._scrollbar.glide_to(self._scrollbar.maximum(), 360)

    def scroll_to_latest_instantly(self) -> None:
        self._set_following(True)
        self._scrollbar.stop_glide()
        self._scrollbar.setValue(self._scrollbar.maximum())

    # ---------------------------------------------------------- model hooks
    def _before_insert(self, *_args) -> None:
        self._was_following = self._following

    def _animations_allowed(self) -> bool:
        return self.isVisible() and THEME.ambient_active and not self.window().isMinimized()

    def _after_insert(self, *_args) -> None:
        if not self._fresh_timer.isActive() and self._animations_allowed():
            self._fresh_timer.start()

    def _before_evict(self, count: int) -> None:
        # Qt would make the next row current and scroll to it (right away, or
        # when the view is shown again): forget a current row that drops off.
        current = self.currentIndex()
        if current.isValid() and current.row() < count:
            self.selectionModel().clearCurrentIndex()

    def _before_remove(self, _parent, first: int, last: int) -> None:
        self._removed_rows = last - first + 1

    def _after_remove(self, *_args) -> None:
        # Keep what you are reading in place while old rows drop off the top.
        if not self._following:
            removed = getattr(self, "_removed_rows", 0)
            bar = self._scrollbar
            bar.stop_glide()
            bar.setValue(max(0, bar.value() - removed * self._delegate.row_height()))

    def _tick_fresh(self) -> None:
        model = self._model
        fresh = model.prune_fresh()
        # Fresh rows are always the newest ones; repaint only those (plus the
        # ones that just expired, to clear their last highlight frame).
        span = max(fresh, self._fresh_rows_painted)
        self._fresh_rows_painted = fresh
        rows = model.rowCount()
        if span and rows:
            first = self.visualRect(model.index(max(0, rows - span)))
            last = self.visualRect(model.index(rows - 1))
            self.viewport().update(first.united(last))
        if not fresh or not self._animations_allowed():
            self._fresh_timer.stop()

    def _theme_changed(self) -> None:
        self.apply_row_height()
        self.viewport().update()

    # ---------------------------------------------------------------- input
    def wheelEvent(self, event) -> None:  # also used for the wheel over the scrollbar
        bar = self._scrollbar
        # Faster with more rows (1 % of them per notch), within 3..25 rows.
        rows = max(3, min(25, round(self._model.rowCount() * 0.01)))
        bar.scroll_wheel(event, rows * self._delegate.row_height())
        self._set_following(bar.glide_target >= bar.maximum() - self._delegate.row_height() // 2)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            rows = sorted(index.row() for index in self.selectionModel().selectedIndexes())
            lines = [self._model.data(self._model.index(row)) for row in rows]
            if lines:
                QApplication.clipboard().setText("\n".join(lines))
            event.accept()
            return
        if event.key() == Qt.Key.Key_End:
            self.scroll_to_latest()
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        self._follow_on_show = self._following
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Qt may scroll while showing (pending layout / current item); whoever
        # followed the newest ping when the view was hidden keeps following it.
        if self._following or self._follow_on_show:
            QTimer.singleShot(0, self, self.scroll_to_latest_instantly)


class PingStream(QFrame):
    """Rounded panel with the stream view, an empty state and a "Latest" pill."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StreamPanel")
        self.model = PingStreamModel(self)
        self.view = PingStreamView(self.model, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(THEME.px(4), THEME.px(6), THEME.px(2), THEME.px(6))
        layout.addWidget(self.view)

        self._latest = TextButton("Latest", "secondary", self, icon_name="arrow-down", min_width=0)
        self._latest.setToolTip("Jump to the newest ping (End)")
        self._latest.clicked.connect(self.view.scroll_to_latest)
        self._latest.hide()
        self.view.followChanged.connect(self._on_follow_changed)
        self.model.rowsInserted.connect(self._update_empty_state)
        self.model.rowsRemoved.connect(self._update_empty_state)
        self.model.modelReset.connect(self._update_empty_state)
        self._empty_text = "Waiting for the first ping…"
        self.setStyleSheet(
            f"#StreamPanel {{ background: {THEME.colors.deep}; border: 1px solid {THEME.colors.hairline};"
            f" border-radius: {THEME.px(12)}px; }}"
        )

    def _update_empty_state(self, *_args) -> None:
        empty = self.model.rowCount() == 0
        if empty != getattr(self, "_was_empty", None):
            self._was_empty = empty
            self.update()

    def _on_follow_changed(self, following: bool) -> None:
        if following:
            if self._latest.isVisible():
                fade(self._latest, False, THEME.FAST)
        elif self.model.rowCount():
            self._place_latest()
            self._latest.raise_()
            fade(self._latest, True, THEME.NORMAL)

    def _place_latest(self) -> None:
        hint = self._latest.sizeHint()
        margin = THEME.px(16)
        self._latest.setGeometry(
            QRect(self.width() - hint.width() - margin - THEME.px(14),
                  self.height() - hint.height() - margin, hint.width(), hint.height())
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_latest()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.model.rowCount() == 0:
            painter = QPainter(self)
            painter.setFont(THEME.font(13))
            painter.setPen(QColor(THEME.colors.ink3))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
