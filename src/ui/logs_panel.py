"""
The Logs overlay: ping spikes and lost pings of the current session and of
previous sessions, newest first.

A host that is down logs one entry per second (~86,400 a day), so the lists
show the newest ``MAX_ROWS`` entries and everything else stays in the log
files. All rows have one height, so a new entry costs the same with 10 or
5,000 rows on screen.
"""

import time
from collections import OrderedDict
from datetime import date, datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from src.core.models import LatencyLevel
from src.core.spike_log import SessionMarker, SpikeEntry, SpikeLog
from src.ui.controls import TextButton, Tween, fade
from src.ui.fast_list import FastListView
from src.ui.overlay import Panel
from src.ui.scrollbar import SmoothScrollBar
from src.ui.theme import THEME

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1
FRESH_MS = 1200.0
FRESH_FRAME_MS = 33
MAX_ROWS = 5000

_KIND_TEXT = {"timeout": "Timed out", "unreachable": "Unreachable", "error": "Error"}


def entry_text(entry: SpikeEntry) -> str:
    if entry.kind == "spike":
        return f"{entry.rtt_ms} ms"
    return _KIND_TEXT.get(entry.kind, entry.kind.title())


class EarlierEntries:
    """Header for entries written before session markers existed."""

    def to_line(self) -> str:
        return "=== Earlier entries ==="


class MoreInFile:
    """Last row when older entries are left out of the list."""

    def __init__(self, text: str) -> None:
        self.text = text

    def to_line(self) -> str:
        return self.text


class SegmentedControl(QWidget):
    """Two or more options with a highlight that glides to the selected one.
    Keyboard: Tab to focus it, Left / Right to switch."""

    currentChanged = Signal(int)

    def __init__(self, options: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options
        self._current = 0
        self._hovered = -1
        self._position = Tween(self, self.update, value=0.0, duration=240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._apply_theme()
        THEME.changed.connect(self._apply_theme)

    def _apply_theme(self) -> None:
        self.setFixedHeight(THEME.px(36))
        self.updateGeometry()
        self.update()

    def current(self) -> int:
        return self._current

    def set_current(self, index: int, animate: bool = True) -> None:
        if index == self._current or not 0 <= index < len(self._options):
            return
        self._current = index
        if animate:
            self._position.to(float(index))
        else:
            self._position.jump(float(index))
        self.currentChanged.emit(index)

    def _segment(self) -> float:
        return (self.width() - THEME.px(8)) / max(1, len(self._options))

    def _index_at(self, x: float) -> int:
        index = int((x - THEME.px(4)) // self._segment())
        return index if 0 <= index < len(self._options) else -1

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(THEME.font(13, QFont.Weight.DemiBold))
        widest = max(metrics.horizontalAdvance(option) for option in self._options)
        return QSize((widest + THEME.px(36)) * len(self._options) + THEME.px(8), THEME.px(36))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Right:
            self.set_current(min(len(self._options) - 1, self._current + 1))
        elif event.key() == Qt.Key.Key_Left:
            self.set_current(max(0, self._current - 1))
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position().x())
        if index != self._hovered:
            self._hovered = index
            self.setCursor(Qt.CursorShape.PointingHandCursor if index not in (-1, self._current)
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        index = self._index_at(event.position().x())
        if index >= 0:
            self.set_current(index)
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, _event) -> None:
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QColor(c.hairline))
        painter.setBrush(QColor(c.abyss))
        painter.drawRoundedRect(rect, THEME.px(10), THEME.px(10))
        segment = self._segment()
        highlight = QRectF(THEME.px(4) + segment * self._position.value, THEME.px(4), segment,
                           self.height() - THEME.px(8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.raised_hover))
        painter.drawRoundedRect(highlight, THEME.px(7), THEME.px(7))
        if self.hasFocus():
            pen = QPen(QColor(c.accent))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(highlight, THEME.px(7), THEME.px(7))
        painter.setFont(THEME.font(13, QFont.Weight.DemiBold))
        for index, option in enumerate(self._options):
            area = QRectF(THEME.px(4) + segment * index, 0, segment, self.height())
            if index == self._current:
                painter.setPen(QColor(c.ink))
            else:
                painter.setPen(QColor(c.ink2 if index == self._hovered else c.ink3))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, option)


class LogModel(QAbstractListModel):
    def __init__(self, headers: bool, limit: int = MAX_ROWS, overflow_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._headers = headers
        self._limit = limit
        self._overflow_text = overflow_text
        self._items: list = []
        self._counts: dict[int, int] = {}
        self._partial: set[int] = set()
        self._entries = 0
        # id(entry) -> time it was added, oldest first (entries are only prepended).
        self._fresh: OrderedDict[int, float] = OrderedDict()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == ITEM_ROLE:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item.to_line()
        return None

    def set_items(self, items, more_in_file: str | None = None, partial_first: bool = False) -> None:
        """``items`` in file order (oldest first); shown newest first (file order
        is the real order, also across midnight and DST), each session under
        its header."""
        sessions: list[tuple[object | None, list[SpikeEntry]]] = []
        for item in items:
            if isinstance(item, SessionMarker):
                sessions.append((item, []))
            else:
                if not sessions:
                    sessions.append((EarlierEntries() if self._headers else None, []))
                sessions[-1][1].append(item)
        rows: list = []
        counts: dict[int, int] = {}
        partial: set[int] = set()
        for position, (header, entries) in enumerate(reversed(sessions)):
            if header is not None:
                counts[id(header)] = len(entries)
                if partial_first and position == len(sessions) - 1:
                    partial.add(id(header))
                rows.append(header)
            rows.extend(reversed(entries))
        if more_in_file:
            rows.append(MoreInFile(more_in_file))
        self.beginResetModel()
        self._items = rows
        self._counts = counts
        self._partial = partial
        self._entries = sum(len(entries) for _, entries in sessions)
        self._fresh.clear()
        self.endResetModel()

    def prepend(self, entry: SpikeEntry) -> None:
        self.prune_fresh()  # also while hidden, when nothing else prunes
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._items.insert(0, entry)
        self._fresh[id(entry)] = time.monotonic()
        self.endInsertRows()
        self._entries += 1
        if self._entries > self._limit:
            self._drop_oldest_entry()

    def _drop_oldest_entry(self) -> None:
        row = len(self._items) - 1
        while row >= 0 and not isinstance(self._items[row], SpikeEntry):
            row -= 1
        if row < 0:
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        removed = self._items.pop(row)
        self.endRemoveRows()
        self._fresh.pop(id(removed), None)
        self._entries -= 1
        if self._overflow_text and not (self._items and isinstance(self._items[-1], MoreInFile)):
            end = len(self._items)
            self.beginInsertRows(QModelIndex(), end, end)
            self._items.append(MoreInFile(self._overflow_text))
            self.endInsertRows()

    def entry_count(self) -> int:
        return self._entries

    def session_count(self, header) -> tuple[int, bool]:
        """Entries under ``header`` and whether older ones were left out."""
        return self._counts.get(id(header), 0), id(header) in self._partial

    def freshness(self, item) -> float:
        started = self._fresh.get(id(item))
        if started is None:
            return 0.0
        age = (time.monotonic() - started) * 1000
        if age >= FRESH_MS:
            del self._fresh[id(item)]
            return 0.0
        return 1.0 - age / FRESH_MS

    def prune_fresh(self) -> int:
        """Forget expired highlights (also of rows never painted); returns how many
        of the newest rows (at the top) are still fresh."""
        fresh = self._fresh
        now = time.monotonic()
        while fresh:
            oldest = next(iter(fresh))
            if (now - fresh[oldest]) * 1000 < FRESH_MS:
                break
            del fresh[oldest]
        return len(fresh)


class LogDelegate(QStyledItemDelegate):
    def __init__(self, model: LogModel, show_dates: bool, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.show_dates = show_dates

    @staticmethod
    def row_height() -> int:
        return THEME.px(30)

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.row_height())

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        c = THEME.colors
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect)
        if isinstance(item, (SessionMarker, EarlierEntries)):
            self._paint_header(painter, rect, item)
        elif isinstance(item, MoreInFile):
            painter.setFont(THEME.font(12))
            painter.setPen(QColor(c.ink3))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, item.text)
        else:
            self._paint_entry(painter, rect, item, option)
        painter.restore()

    def _paint_header(self, painter: QPainter, rect: QRectF, item) -> None:
        c = THEME.colors
        count, partial = self._model.session_count(item)
        if isinstance(item, SessionMarker):
            title = f"Session started {item.started_at.strftime('%d %b %Y, %H:%M')}"
        else:
            title = "Earlier entries"
        events = f"{count:,}{'+' if partial else ''} " + ("event" if count == 1 and not partial else "events")
        text_rect = rect.adjusted(THEME.px(14), THEME.px(4), -THEME.px(14), 0)
        painter.setFont(THEME.font(12, QFont.Weight.DemiBold))
        painter.setPen(QColor(c.ink2))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        painter.setFont(THEME.font(12))
        painter.setPen(QColor(c.ink3))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, events)
        painter.fillRect(QRectF(rect.left() + THEME.px(14), rect.bottom() - 1,
                                rect.width() - THEME.px(28), 1), QColor(c.hairline))

    def _paint_entry(self, painter: QPainter, rect: QRectF, item: SpikeEntry, option) -> None:
        c = THEME.colors
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        fresh = self._model.freshness(item) if THEME.motion else 0.0
        background = None
        if selected:
            background = QColor(c.accent)
            background.setAlphaF(0.20)
        elif fresh > 0:
            background = QColor(c.bad)
            background.setAlphaF(0.18 * fresh * fresh)
        elif hovered:
            background = QColor(c.raised_hover)
            background.setAlphaF(0.6)
        if background is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(rect.adjusted(THEME.px(4), 1, -THEME.px(4), -1), THEME.px(6), THEME.px(6))

        mono = THEME.font(12.5, mono=True)
        metrics = QFontMetrics(mono)
        x = rect.left() + THEME.px(14)
        stamp_format = "%Y-%m-%d %H:%M:%S" if self.show_dates else "%H:%M:%S"
        painter.setFont(mono)
        painter.setPen(QColor(c.ink3))
        painter.drawText(QRectF(x, rect.top(), rect.width(), rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         item.timestamp.strftime(stamp_format))
        x += metrics.horizontalAdvance(datetime(2000, 1, 1).strftime(stamp_format)) + THEME.px(22)
        server_font = THEME.font(13, QFont.Weight.Medium)
        painter.setFont(server_font)
        painter.setPen(QColor(c.ink2))
        server_width = THEME.px(190)
        painter.drawText(QRectF(x, rect.top(), server_width, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(server_font).elidedText(item.server, Qt.TextElideMode.ElideRight,
                                                              server_width - THEME.px(8)))
        x += server_width
        painter.setFont(THEME.font(12.5, QFont.Weight.Medium, mono=True))
        painter.setPen(THEME.level_color(LatencyLevel.BAD, text=True))
        painter.drawText(QRectF(x, rect.top(), rect.right() - x - THEME.px(14), rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, entry_text(item))


class _LogList(FastListView):
    def __init__(self, show_dates: bool, empty_text: str, headers: bool, overflow_text: str = "",
                 parent=None) -> None:
        super().__init__(LogDelegate.row_height, parent)
        self.model_ = LogModel(headers, overflow_text=overflow_text, parent=self)
        self._delegate = LogDelegate(self.model_, show_dates, self)
        self.setModel(self.model_)
        self.setItemDelegate(self._delegate)
        bar = SmoothScrollBar(self)
        bar.wheel_handler = self.wheelEvent
        self.setVerticalScrollBar(bar)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.empty_text = empty_text
        self._fresh_rows_painted = 0
        self._fresh_timer = QTimer(self)
        self._fresh_timer.setInterval(FRESH_FRAME_MS)
        self._fresh_timer.timeout.connect(self._tick)
        self.model_.rowsInserted.connect(self._inserted)
        THEME.changed.connect(self._theme_changed)

    def _theme_changed(self) -> None:
        self.apply_row_height()
        self.viewport().update()

    def _animations_allowed(self) -> bool:
        return THEME.motion and self.isVisible() and not self.window().isMinimized()

    def _inserted(self, _parent, first: int, last: int) -> None:
        if first != 0:
            return  # e.g. the "older entries" row at the end
        bar: SmoothScrollBar = self.verticalScrollBar()  # type: ignore[assignment]
        at_top = bar.glide_target <= THEME.px(30)
        self.executeDelayedItemsLayout()  # the scroll range must include the new rows now
        bar.stop_glide()
        # Keep what is on screen in place; when you are at the top, the new
        # entry then glides in instead of everything jumping down a row.
        bar.setValue(bar.value() + (last - first + 1) * self._delegate.row_height())
        if at_top:
            bar.glide_to(0, 260)
        if not self._fresh_timer.isActive() and self._animations_allowed():
            self._fresh_timer.start()

    def _tick(self) -> None:
        model = self.model_
        fresh = model.prune_fresh()
        span = min(max(fresh, self._fresh_rows_painted), model.rowCount())
        self._fresh_rows_painted = fresh
        if span:
            first = self.visualRect(model.index(0))
            last = self.visualRect(model.index(span - 1))
            self.viewport().update(first.united(last))
        if not fresh or not self._animations_allowed():
            self._fresh_timer.stop()

    def wheelEvent(self, event) -> None:  # also used for the wheel over the scrollbar
        bar: SmoothScrollBar = self.verticalScrollBar()  # type: ignore[assignment]
        bar.scroll_wheel(event, 3 * self._delegate.row_height())

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            rows = sorted(index.row() for index in self.selectionModel().selectedIndexes())
            lines = [self.model_.data(self.model_.index(row)) for row in rows]
            if lines:
                QApplication.clipboard().setText("\n".join(lines))
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.model_.rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setFont(THEME.font(13))
            painter.setPen(QColor(THEME.colors.ink3))
            painter.drawText(self.viewport().rect().adjusted(THEME.px(24), 0, -THEME.px(24), 0),
                             int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), self.empty_text)


class LogsPanel(Panel):
    _last_tab = 0  # the tab you looked at last, kept while the app runs

    def __init__(self, spike_log: SpikeLog, degraded_ms: int, folder) -> None:
        super().__init__("Logs", width=760)
        self._spike_log = spike_log
        self._folder = folder
        self._previous_loaded = False

        self.tabs = SegmentedControl(["Current session", "Previous sessions"])
        top = QHBoxLayout()
        top.addWidget(self.tabs)
        top.addStretch(1)
        self.outer.addLayout(top)

        self._frame = QFrame()
        self._frame.setObjectName("LogsFrame")
        started = spike_log.session_started_at
        # A session can run for days in the tray: then the times need dates.
        multi_day = started is not None and started.date() != date.today()
        self.current_list = _LogList(
            multi_day,
            f"No ping spikes in this session yet.\nPings above {degraded_ms} ms and lost pings show up here.",
            headers=False, overflow_text="Older entries of this session are in the log folder.")
        self.previous_list = _LogList(
            True, "No ping spikes from previous sessions in the last 24 hours.", headers=True)
        # Both lists share the space and cross-fade when switching tabs.
        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self.current_list)
        stack.addWidget(self.previous_list)
        self._frame_layout = QVBoxLayout(self._frame)
        self._frame_layout.addLayout(stack)
        self.outer.addWidget(self._frame, 1)

        footer = QHBoxLayout()
        self.folder_button = TextButton("Open log folder", "secondary", icon_name="folder-open", min_width=0)
        self.folder_button.clicked.connect(self._open_folder)
        footer.addWidget(self.folder_button)
        footer.addStretch(1)
        self.outer.addLayout(footer)

        total = spike_log.session_entry_count()
        self.current_list.model_.set_items(
            spike_log.current_entries(MAX_ROWS),
            more_in_file="Older entries of this session are in the log folder." if total > MAX_ROWS else None)
        self._apply_theme()
        THEME.changed.connect(self._apply_theme)

        index = LogsPanel._last_tab
        self.tabs.set_current(index, animate=False)
        self._show_list(index, animate=False)
        self.tabs.currentChanged.connect(self._tab_changed)

    def _apply_theme(self) -> None:
        c = THEME.colors
        self._frame.setStyleSheet(f"#LogsFrame {{ background: {c.deep}; border: 1px solid {c.hairline};"
                                  f" border-radius: {THEME.px(12)}px; }}")
        self._frame_layout.setContentsMargins(THEME.px(2), THEME.px(6), THEME.px(2), THEME.px(6))

    def sizeHint(self) -> QSize:
        return QSize(self.preferred_width(), THEME.px(620))

    def add_entry(self, entry: SpikeEntry) -> None:
        self.current_list.model_.prepend(entry)

    def _tab_changed(self, index: int) -> None:
        LogsPanel._last_tab = index
        self._show_list(index, animate=True)

    def _show_list(self, index: int, animate: bool) -> None:
        showing, hiding = ((self.current_list, self.previous_list) if index == 0
                           else (self.previous_list, self.current_list))
        if index == 1 and not self._previous_loaded:
            self._load_previous()
        showing.raise_()
        if animate:
            fade(hiding, False, THEME.FAST)
            fade(showing, True, THEME.NORMAL)
        else:
            hiding.hide()
            showing.show()
        showing.setFocus()

    def _load_previous(self) -> None:
        try:
            recent = self._spike_log.recent_previous_items(MAX_ROWS)
        except OSError as error:
            # E.g. a sync client or antivirus holds the file: try again next time.
            self.previous_list.empty_text = f"Could not read the log file ({error.strerror or error})."
            self.previous_list.model_.set_items([])
            return
        self._previous_loaded = True
        self.previous_list.model_.set_items(
            recent.items, more_in_file="Older entries are in the log folder." if recent.truncated else None,
            partial_first=recent.partial_first)

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._folder)))

    def on_shown(self) -> None:
        (self.previous_list if self.tabs.current() == 1 else self.current_list).setFocus()
