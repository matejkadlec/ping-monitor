"""
Server tabs: name, live health dot and latest ping, with an underline that
glides between tabs and hover colors that fade instead of snapping.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.core.models import HealthStatus
from src.ui.controls import Tween
from src.ui.theme import THEME, mix


@dataclass
class _Tab:
    name: str
    health: HealthStatus = HealthStatus.UNKNOWN
    value: str = ""
    hover: Tween | None = None
    color_from: QColor = field(default_factory=lambda: QColor(THEME.colors.neutral))
    color_to: QColor = field(default_factory=lambda: QColor(THEME.colors.neutral))
    color_tween: Tween | None = None


class TabStrip(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tabs: list[_Tab] = []
        self._current = -1
        self._hovered = -1
        self._rects: list[QRectF] = []
        self._show_values = True
        self._indicator = QRectF()
        self._indicator_from = QRectF()
        self._indicator_to = QRectF()
        self._indicator_anim = QVariantAnimation(self)
        self._indicator_anim.setStartValue(0.0)
        self._indicator_anim.setEndValue(1.0)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._indicator_anim.valueChanged.connect(self._step_indicator)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        THEME.changed.connect(self._relayout)

    # ------------------------------------------------------------------ data
    def set_tabs(self, names: list[str], current: int = 0) -> None:
        self._tabs = []
        for name in names:
            tab = _Tab(name)
            tab.hover = Tween(self, self.update)
            tab.color_tween = Tween(self, self.update, value=1.0, duration=THEME.SLOW)
            self._tabs.append(tab)
        self._current = min(max(0, current), len(names) - 1) if names else -1
        self._hovered = -1
        self._relayout(animate=False)

    def names(self) -> list[str]:
        return [tab.name for tab in self._tabs]

    def count(self) -> int:
        return len(self._tabs)

    def current_index(self) -> int:
        return self._current

    def set_current(self, index: int, animate: bool = True) -> None:
        if not 0 <= index < len(self._tabs) or index == self._current:
            return
        self._current = index
        self._move_indicator(animate)
        self.update()
        self.currentChanged.emit(index)

    def update_tab(self, index: int, health: HealthStatus, value: str) -> None:
        if not 0 <= index < len(self._tabs):
            return
        tab = self._tabs[index]
        relayout = (value == "") != (tab.value == "")
        if health != tab.health:
            tab.color_from = mix(tab.color_from, tab.color_to, tab.color_tween.value)
            tab.color_to = THEME.health_color(health)
            tab.health = health
            tab.color_tween.jump(0.0)
            tab.color_tween.to(1.0)
        tab.value = value
        if relayout:
            self._relayout(animate=False)
        else:
            self.update()

    # ---------------------------------------------------------------- layout
    def sizeHint(self) -> QSize:
        return QSize(THEME.px(400), THEME.px(48))

    def minimumSizeHint(self) -> QSize:
        return QSize(THEME.px(120), THEME.px(48))

    def _fonts(self) -> tuple[QFont, QFont]:
        return THEME.font(13.5, QFont.Weight.DemiBold), THEME.font(12, QFont.Weight.Medium, tabular=True)

    def _natural_widths(self, with_values: bool) -> list[float]:
        name_font, value_font = self._fonts()
        name_metrics, value_metrics = QFontMetrics(name_font), QFontMetrics(value_font)
        widths = []
        for tab in self._tabs:
            width = (THEME.px(14) + THEME.px(8) + THEME.px(10) + name_metrics.horizontalAdvance(tab.name)
                     + THEME.px(14) + THEME.px(4))
            if with_values:
                width += THEME.px(8) + value_metrics.horizontalAdvance("9999 ms")
            widths.append(width)
        return widths

    def _relayout(self, animate: bool = False) -> None:
        self.setFixedHeight(THEME.px(48))
        gap = THEME.px(4)
        available = max(1, self.width())
        widths = self._natural_widths(True)
        self._show_values = sum(widths) + gap * max(0, len(widths) - 1) <= available
        if not self._show_values:
            widths = self._natural_widths(False)
            total = sum(widths) + gap * max(0, len(widths) - 1)
            if total > available and widths:
                each = (available - gap * (len(widths) - 1)) / len(widths)
                widths = [max(THEME.px(60), each)] * len(widths)
        x = 0.0
        self._rects = []
        for width in widths:
            self._rects.append(QRectF(x, 0, width, self.height()))
            x += width + gap
        self._move_indicator(animate)
        self.update()

    def _indicator_rect(self) -> QRectF:
        if not 0 <= self._current < len(self._rects):
            return QRectF()
        rect = self._rects[self._current]
        height = THEME.px(2.5)
        return QRectF(rect.left() + THEME.px(12), rect.bottom() - height, rect.width() - THEME.px(24), height)

    def _move_indicator(self, animate: bool) -> None:
        target = self._indicator_rect()
        if not animate or self._indicator.isNull() or not THEME.motion:
            self._indicator_anim.stop()
            self._indicator = target
            return
        self._indicator_from = QRectF(self._indicator)
        self._indicator_to = target
        self._indicator_anim.stop()
        self._indicator_anim.setDuration(THEME.duration(260))
        self._indicator_anim.start()

    def _step_indicator(self, value) -> None:
        t = float(value)
        a, b = self._indicator_from, self._indicator_to
        self._indicator = QRectF(
            a.left() + (b.left() - a.left()) * t,
            a.top() + (b.top() - a.top()) * t,
            a.width() + (b.width() - a.width()) * t,
            a.height() + (b.height() - a.height()) * t,
        )
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout(animate=False)

    # ----------------------------------------------------------------- input
    def _index_at(self, point: QPointF) -> int:
        for index, rect in enumerate(self._rects):
            if rect.contains(point):
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position())
        if index != self._hovered:
            if 0 <= self._hovered < len(self._tabs):
                self._tabs[self._hovered].hover.to(0.0)
            self._hovered = index
            if index >= 0:
                self._tabs[index].hover.to(1.0)
                tab = self._tabs[index]
                self.setToolTip(f"{tab.name}: {tab.health.label}")
            else:
                self.setToolTip("")
            self.setCursor(Qt.CursorShape.PointingHandCursor if index >= 0 and index != self._current
                           else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:
        if 0 <= self._hovered < len(self._tabs):
            self._tabs[self._hovered].hover.to(0.0)
        self._hovered = -1
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(event.position())
            if index >= 0:
                self.set_current(index)
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Right:
            self.set_current((self._current + 1) % max(1, len(self._tabs)))
        elif event.key() == Qt.Key.Key_Left:
            self.set_current((self._current - 1) % max(1, len(self._tabs)))
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        name_font, value_font = self._fonts()
        name_metrics = QFontMetrics(name_font)
        for index, (tab, rect) in enumerate(zip(self._tabs, self._rects)):
            selected = index == self._current
            hover = tab.hover.value if tab.hover else 0.0
            if hover > 0.01 and not selected:
                background = QColor(c.raised_hover)
                background.setAlphaF(0.45 * hover)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(background)
                painter.drawRoundedRect(rect.adjusted(2, THEME.px(7), -2, -THEME.px(7)), THEME.px(8), THEME.px(8))

            x = rect.left() + THEME.px(14)
            dot_color = mix(tab.color_from, tab.color_to, tab.color_tween.value)
            radius = THEME.px(4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_color)
            painter.drawEllipse(QPointF(x + radius, rect.center().y()), radius, radius)
            x += 2 * radius + THEME.px(10)

            painter.setFont(name_font)
            painter.setPen(QColor(c.ink) if selected else mix(c.ink2, c.ink, hover))
            value_space = (THEME.px(8) + QFontMetrics(value_font).horizontalAdvance("9999 ms")) if self._show_values else 0
            name_width = rect.right() - THEME.px(14) - value_space - x
            name = name_metrics.elidedText(tab.name, Qt.TextElideMode.ElideRight, int(max(10, name_width)))
            painter.drawText(QRectF(x, rect.top(), name_width + 2, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            if self._show_values and tab.value:
                painter.setFont(value_font)
                painter.setPen(QColor(c.ink3))
                value_rect = QRectF(rect.right() - THEME.px(14) - value_space + THEME.px(8), rect.top(),
                                    value_space - THEME.px(8), rect.height())
                painter.drawText(value_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, tab.value)

        if not self._indicator.isNull():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.accent))
            painter.drawRoundedRect(self._indicator, self._indicator.height() / 2, self._indicator.height() / 2)
