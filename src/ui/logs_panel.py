"""
The Logs overlay: ping spikes and lost pings of the current session and of
previous sessions, newest first.
"""

import time
from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from src.core.models import LatencyLevel
from src.core.spike_log import SessionMarker, SpikeEntry, SpikeLog
from src.ui.controls import TextButton, Tween
from src.ui.overlay import Panel
from src.ui.scrollbar import SmoothScrollBar
from src.ui.theme import THEME

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1
FRESH_MS = 1200.0

_KIND_TEXT = {"timeout": "Timed out", "unreachable": "Unreachable", "error": "Error"}


def entry_text(entry: SpikeEntry) -> str:
    if entry.kind == "spike":
        return f"{entry.rtt_ms} ms"
    return _KIND_TEXT.get(entry.kind, entry.kind.title())


class SegmentedControl(QWidget):
    """Two or more options with a highlight that glides to the selected one."""

    currentChanged = Signal(int)

    def __init__(self, options: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options
        self._current = 0
        self._hovered = -1
        self._position = Tween(self, self.update, value=0.0, duration=240)
        self.setMouseTracking(True)
        self.setFixedHeight(THEME.px(36))

    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        if index == self._current or not 0 <= index < len(self._options):
            return
        self._current = index
        self._position.to(float(index))
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
        painter.setFont(THEME.font(13, QFont.Weight.DemiBold))
        for index, option in enumerate(self._options):
            area = QRectF(THEME.px(4) + segment * index, 0, segment, self.height())
            if index == self._current:
                painter.setPen(QColor(c.ink))
            else:
                painter.setPen(QColor(c.ink2 if index == self._hovered else c.ink3))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, option)


class LogModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[SpikeEntry | SessionMarker] = []
        self._counts: dict[int, int] = {}
        self._fresh: dict[int, float] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == ITEM_ROLE:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item.to_line()
        return None

    def set_items(self, items: list[SpikeEntry | SessionMarker]) -> None:
        """``items`` in file order (oldest first); shown newest first, each session under its header."""
        sessions: list[tuple[SessionMarker | None, list[SpikeEntry]]] = []
        for item in items:
            if isinstance(item, SessionMarker):
                sessions.append((item, []))
            else:
                if not sessions:
                    sessions.append((None, []))
                sessions[-1][1].append(item)
        rows: list[SpikeEntry | SessionMarker] = []
        counts: dict[int, int] = {}
        for marker, entries in reversed(sessions):
            if marker is not None:
                counts[id(marker)] = len(entries)
                rows.append(marker)
            rows.extend(sorted(entries, key=lambda entry: entry.timestamp, reverse=True))
        self.beginResetModel()
        self._items = rows
        self._counts = counts
        self._fresh.clear()
        self.endResetModel()

    def prepend(self, entry: SpikeEntry) -> None:
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._items.insert(0, entry)
        self._fresh[id(entry)] = time.monotonic()
        self.endInsertRows()

    def session_count(self, marker: SessionMarker) -> int:
        return self._counts.get(id(marker), 0)

    def freshness(self, item) -> float:
        started = self._fresh.get(id(item))
        if started is None:
            return 0.0
        age = (time.monotonic() - started) * 1000
        if age >= FRESH_MS:
            del self._fresh[id(item)]
            return 0.0
        return 1.0 - age / FRESH_MS

    def has_fresh(self) -> bool:
        return bool(self._fresh)


class LogDelegate(QStyledItemDelegate):
    def __init__(self, model: LogModel, show_dates: bool, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.show_dates = show_dates

    def sizeHint(self, option, index) -> QSize:
        item = index.data(ITEM_ROLE)
        height = THEME.px(40) if isinstance(item, SessionMarker) else THEME.px(28)
        return QSize(option.rect.width(), height)

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(ITEM_ROLE)
        c = THEME.colors
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect)
        if isinstance(item, SessionMarker):
            count = self._model.session_count(item)
            painter.setFont(THEME.font(12, QFont.Weight.DemiBold))
            painter.setPen(QColor(c.ink2))
            started = item.started_at.strftime("%d %b %Y, %H:%M")
            events = "1 event" if count == 1 else f"{count} events"
            text_rect = rect.adjusted(THEME.px(14), THEME.px(12), -THEME.px(14), 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"Session started {started}")
            painter.setPen(QColor(c.ink3))
            painter.setFont(THEME.font(12))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, events)
            painter.fillRect(QRectF(rect.left() + THEME.px(14), rect.bottom() - 1,
                                    rect.width() - THEME.px(28), 1), QColor(c.hairline))
            painter.restore()
            return

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
        stamp = item.timestamp.strftime(stamp_format)
        painter.setFont(mono)
        painter.setPen(QColor(c.ink3))
        painter.drawText(QRectF(x, rect.top(), rect.width(), rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, stamp)
        x += metrics.horizontalAdvance(datetime(2000, 1, 1).strftime(stamp_format)) + THEME.px(22)
        painter.setFont(THEME.font(13, QFont.Weight.Medium))
        painter.setPen(QColor(c.ink2))
        server_width = THEME.px(190)
        painter.drawText(QRectF(x, rect.top(), server_width, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(THEME.font(13, QFont.Weight.Medium)).elidedText(
                             item.server, Qt.TextElideMode.ElideRight, server_width - THEME.px(8)))
        x += server_width
        painter.setFont(THEME.font(12.5, QFont.Weight.Medium, mono=True))
        painter.setPen(THEME.level_color(LatencyLevel.BAD, text=True))
        painter.drawText(QRectF(x, rect.top(), rect.right() - x - THEME.px(14), rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, entry_text(item))
        painter.restore()


class _LogList(QListView):
    def __init__(self, show_dates: bool, empty_text: str, parent=None) -> None:
        super().__init__(parent)
        self.model_ = LogModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(LogDelegate(self.model_, show_dates, self))
        self.setVerticalScrollBar(SmoothScrollBar(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setStyleSheet("QListView { background: transparent; border: none; outline: none; }")
        self.empty_text = empty_text
        self._fresh_timer = QTimer(self)
        self._fresh_timer.setInterval(16)
        self._fresh_timer.timeout.connect(self._tick)
        self.model_.rowsInserted.connect(self._inserted)

    def _inserted(self, *_args) -> None:
        bar = self.verticalScrollBar()
        if bar.value() <= THEME.px(30):
            QTimer.singleShot(0, lambda: bar.setValue(0))
        if not self._fresh_timer.isActive():
            self._fresh_timer.start()

    def _tick(self) -> None:
        if not self.model_.has_fresh():
            self._fresh_timer.stop()
        self.viewport().update()

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

        frame = QFrame()
        frame.setObjectName("LogsFrame")
        frame.setStyleSheet(f"#LogsFrame {{ background: {THEME.colors.deep}; border: 1px solid "
                            f"{THEME.colors.hairline}; border-radius: {THEME.px(12)}px; }}")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(THEME.px(2), THEME.px(6), THEME.px(2), THEME.px(6))
        self.current_list = _LogList(
            False, f"No ping spikes in this session yet.\nPings above {degraded_ms} ms and lost pings show up here.")
        self.previous_list = _LogList(
            True, "No ping spikes from previous sessions in the last 24 hours.")
        frame_layout.addWidget(self.current_list)
        frame_layout.addWidget(self.previous_list)
        self.previous_list.hide()
        self.outer.addWidget(frame, 1)

        footer = QHBoxLayout()
        self.folder_button = TextButton("Open log folder", "secondary", icon_name="folder-open", min_width=0)
        self.folder_button.clicked.connect(self._open_folder)
        footer.addWidget(self.folder_button)
        footer.addStretch(1)
        self.outer.addLayout(footer)

        self.tabs.currentChanged.connect(self._tab_changed)
        self.current_list.model_.set_items(spike_log.current_entries())

    def sizeHint(self) -> QSize:
        return QSize(self.preferred_width(), THEME.px(620))

    def add_entry(self, entry: SpikeEntry) -> None:
        self.current_list.model_.prepend(entry)

    def _tab_changed(self, index: int) -> None:
        showing, hiding = ((self.current_list, self.previous_list) if index == 0
                           else (self.previous_list, self.current_list))
        if index == 1 and not self._previous_loaded:
            self._previous_loaded = True
            self.previous_list.model_.set_items(self._spike_log.previous_items())
        hiding.hide()
        showing.show()
        showing.setFocus()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._folder)))

    def on_shown(self) -> None:
        self.current_list.setFocus()

