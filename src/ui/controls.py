"""
Small custom-painted controls with smooth (never instant) state transitions.
"""

from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QGraphicsOpacityEffect, QWidget

from src.ui import icons
from src.ui.theme import THEME, mix


def connect_running(animation: QVariantAnimation, slot: Callable[[float], None]) -> None:
    """Connect ``slot`` to ``animation.valueChanged``, ignoring the values Qt emits
    while a stopped animation is being reconfigured (setDuration / setStartValue /
    setEndValue re-interpolate the old curve and would make the next run start
    from a stale value)."""

    def forward(value) -> None:
        if animation.state() == QVariantAnimation.State.Running:
            slot(value)

    animation.valueChanged.connect(forward)


class Tween(QObject):
    """Animated float in [0, 1] (or any range) that calls ``on_update`` per frame."""

    def __init__(self, parent: QObject, on_update: Callable[[], None], value: float = 0.0,
                 duration: int | None = None,
                 easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic) -> None:
        super().__init__(parent)
        self.value = value
        self._target = value
        self._on_update = on_update
        self._duration = duration
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(easing)
        connect_running(self._animation, self._step)

    def _step(self, value: float) -> None:
        self.value = float(value)
        self._on_update()

    def to(self, target: float, duration: int | None = None) -> None:
        if target == self._target and (self._animation.state() == QVariantAnimation.State.Running
                                       or self.value == target):
            return
        self._target = target
        start = float(self.value)
        self._animation.stop()
        ms = THEME.duration(duration if duration is not None else (self._duration or THEME.FAST))
        if ms <= 0:
            self.value = target
            self._on_update()
            return
        self._animation.setDuration(ms)
        self._animation.setStartValue(start)
        self._animation.setEndValue(float(target))
        self._animation.start()

    def jump(self, value: float) -> None:
        self._animation.stop()
        self._target = value
        self.value = value
        self._on_update()

    @property
    def running(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running


def press_on_enter(button: QAbstractButton, event) -> bool:
    """Enter / Return clicks a focused button (Qt buttons only react to Space)."""
    if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and button.isEnabled():
        button.click()
        event.accept()
        return True
    return False


def _ancestor_has_effect(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if parent.graphicsEffect() is not None:
            return True
        parent = parent.parentWidget()
    return False


def fade(widget: QWidget, visible: bool, duration: int | None = None,
         on_finished: Callable[[], None] | None = None) -> None:
    """Fade a widget in or out with an opacity effect (no instant pop)."""
    if _ancestor_has_effect(widget) and not isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
        # Qt cannot nest graphics effects (e.g. inside the blurred background):
        # switch directly there; it is hidden behind the overlay anyway.
        animation = getattr(widget, "_fade_animation", None)
        if animation is not None:
            animation.stop()
        widget.setVisible(visible)
        if on_finished:
            on_finished()
        return
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0 if visible else 1.0)
        widget.setGraphicsEffect(effect)
    animation = getattr(widget, "_fade_animation", None)
    if animation is None:
        animation = QVariantAnimation(widget)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        connect_running(animation, lambda value, w=widget: _apply_fade(w, value))
        animation.finished.connect(lambda w=widget: _fade_finished(w))
        widget._fade_animation = animation  # type: ignore[attr-defined]
    widget._fade_visible = visible  # type: ignore[attr-defined]
    widget._fade_callback = on_finished  # type: ignore[attr-defined]
    start = effect.opacity()
    animation.stop()
    if visible:
        widget.show()
    ms = THEME.duration(duration if duration is not None else THEME.NORMAL)
    animation.setDuration(max(1, ms))
    animation.setStartValue(start)
    animation.setEndValue(1.0 if visible else 0.0)
    animation.start()


def settle_fades(root: QWidget) -> None:
    """Finish every running fade below ``root`` right away (before a graphics
    effect is put on ``root``: Qt cannot render nested effects reliably)."""
    for widget in root.findChildren(QWidget):
        animation = getattr(widget, "_fade_animation", None)
        if animation is not None and animation.state() == QVariantAnimation.State.Running:
            animation.stop()
            _fade_finished(widget)
        elif isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
            _fade_finished(widget)


def _apply_fade(widget: QWidget, value) -> None:
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        effect.setOpacity(float(value))


def _fade_finished(widget: QWidget) -> None:
    callback = getattr(widget, "_fade_callback", None)
    widget._fade_callback = None  # type: ignore[attr-defined]
    # Drop the effect once done: keeps text crisp and avoids nested effects later.
    if isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
        widget.setGraphicsEffect(None)
    if not getattr(widget, "_fade_visible", True):
        widget.hide()
    if callback:
        callback()


class IconButton(QAbstractButton):
    """Square ghost button with a Lucide icon and a softly fading hover background."""

    def __init__(self, icon_name: str, tooltip: str = "", parent: QWidget | None = None,
                 size: int = 34, icon_size: int = 18) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._size = size
        self._icon_size = icon_size
        self._hover = Tween(self, self.update)
        self._press = Tween(self, self.update)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip or icon_name)
        THEME.changed.connect(self.updateGeometry)

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.update()

    def sizeHint(self) -> QSize:
        side = THEME.px(self._size)
        return QSize(side, side)

    def enterEvent(self, event) -> None:
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._press.to(1.0, 60)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press.to(0.0)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if not press_on_enter(self, event):
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self._hover.value
        if self.isChecked():
            hover = max(hover, 0.6)
        if hover > 0.001 or self.hasFocus():
            background = mix(QColor(c.raised_hover).darker(100), QColor(c.raised_hover), hover)
            background.setAlphaF(0.95 * max(hover, 0.5 if self.hasFocus() else 0.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            radius = THEME.px(9)
            painter.drawRoundedRect(rect, radius, radius)
        if self.hasFocus():
            pen = QPen(QColor(c.accent))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius = THEME.px(9)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
        color = mix(c.ink2, c.ink, hover)
        if not self.isEnabled():
            color = QColor(c.ink3)
        size = THEME.px(self._icon_size) * (1.0 - 0.06 * self._press.value)
        icon_rect = QRectF(0, 0, size, size)
        icon_rect.moveCenter(rect.center())
        icons.paint(painter, self._icon_name, icon_rect, color)


class TextButton(QAbstractButton):
    """Rounded text button: ``primary`` (accent fill), ``secondary`` or ``danger``."""

    def __init__(self, text: str, kind: str = "secondary", parent: QWidget | None = None,
                 icon_name: str | None = None, min_width: int = 88) -> None:
        super().__init__(parent)
        self.setText(text)
        self._kind = kind
        self._icon_name = icon_name
        self._min_width = min_width
        self._hover = Tween(self, self.update)
        self._enabled = Tween(self, self.update, value=1.0)
        self._busy = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        THEME.changed.connect(self.updateGeometry)

    def set_busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        if text is not None:
            self.setText(text)
        self.update()

    def changeEvent(self, event) -> None:
        if event.type() == event.Type.EnabledChange:
            self._enabled.to(1.0 if self.isEnabled() else 0.0, THEME.NORMAL)
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled()
                           else Qt.CursorShape.ArrowCursor)
        super().changeEvent(event)

    def _font(self) -> QFont:
        return THEME.font(13, QFont.Weight.DemiBold)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font())
        width = fm.horizontalAdvance(self.text()) + THEME.px(32)
        if self._icon_name:
            width += THEME.px(24)
        return QSize(max(THEME.px(self._min_width), width), THEME.px(36))

    def enterEvent(self, event) -> None:
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if not press_on_enter(self, event):
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = THEME.px(9)
        hover = self._hover.value * (1.0 if self.isEnabled() else 0.0)
        enabled = self._enabled.value

        if self._kind == "primary":
            fill = mix(c.accent, c.accent_strong, hover)
            text_color = QColor(c.on_accent)
            border = None
        elif self._kind == "danger":
            fill = mix(c.bad, QColor(c.bad).lighter(115), hover)
            text_color = QColor("#ffffff")
            border = None
        else:
            fill = mix(c.raised, c.raised_hover, hover)
            text_color = QColor(c.ink)
            border = mix(c.hairline, "#2A3F63", hover)

        disabled_fill = QColor(c.raised)
        fill = mix(disabled_fill, fill, enabled)
        text_color = mix(c.ink3, text_color, enabled)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, fill)
        if border is not None or enabled < 1:
            pen = QPen(border if border is not None else QColor(c.hairline))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)
        if self.hasFocus():
            pen = QPen(QColor(c.accent_strong))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), radius + 1, radius + 1)

        painter.setFont(self._font())
        painter.setPen(text_color)
        text = self.text()
        if self._icon_name:
            fm = QFontMetrics(self._font())
            icon_size = THEME.px(16)
            gap = THEME.px(8)
            total = icon_size + gap + fm.horizontalAdvance(text)
            x = rect.center().x() - total / 2
            icon_rect = QRectF(x, rect.center().y() - icon_size / 2, icon_size, icon_size)
            icons.paint(painter, self._icon_name, icon_rect, text_color)
            painter.drawText(QRectF(x + icon_size + gap, rect.top(), total, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        else:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class Dot(QWidget):
    """Status dot whose color cross-fades on change."""

    def __init__(self, parent: QWidget | None = None, diameter: int = 8) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._from = QColor(THEME.colors.neutral)
        self._to = QColor(THEME.colors.neutral)
        self._tween = Tween(self, self.update, value=1.0, duration=THEME.SLOW)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        THEME.changed.connect(self.updateGeometry)

    def color(self) -> QColor:
        return mix(self._from, self._to, self._tween.value)

    def set_color(self, color: QColor) -> None:
        if QColor(color) == self._to:
            return
        self._from = self.color()
        self._to = QColor(color)
        self._tween.jump(0.0)
        self._tween.to(1.0)

    def sizeHint(self) -> QSize:
        side = THEME.px(self._diameter) + 2
        return QSize(side, side)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = THEME.px(self._diameter)
        rect = QRectF(0, 0, diameter, diameter)
        rect.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color())
        painter.drawEllipse(rect)


class CheckBox(QAbstractButton):
    """Rounded checkbox with an animated fill; optional text label to its right."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self._hover = Tween(self, self.update)
        self._checked = Tween(self, self.update, duration=THEME.NORMAL)
        self.toggled.connect(lambda on: self._checked.to(1.0 if on else 0.0))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        THEME.changed.connect(self.updateGeometry)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt naming
        self.set_checked(checked, animate=False)

    def set_checked(self, checked: bool, animate: bool = True) -> None:
        if checked == self.isChecked():
            return  # keep a running toggle animation going
        super().setChecked(checked)  # emits toggled, which starts the animation
        if not animate:
            self._checked.jump(1.0 if checked else 0.0)

    def sizeHint(self) -> QSize:
        box = THEME.px(18)
        width = box
        if self.text():
            width += THEME.px(10) + QFontMetrics(THEME.font(13)).horizontalAdvance(self.text())
        return QSize(width + 2, max(box, THEME.px(22)) + 2)

    def hitButton(self, pos) -> bool:  # noqa: N802 - whole widget is clickable
        return self.rect().contains(pos)

    def enterEvent(self, event) -> None:
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        c = THEME.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = THEME.px(18)
        rect = QRectF(1, (self.height() - box) / 2, box, box)
        t = self._checked.value
        border = mix(mix(c.ink3, c.ink2, self._hover.value), c.accent, t)
        fill = QColor(c.accent)
        fill.setAlphaF(t)
        painter.setPen(QPen(border, 1.5))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, THEME.px(5), THEME.px(5))
        if t > 0.01:
            check = QColor(c.on_accent)
            check.setAlphaF(t)
            inner = rect.adjusted(THEME.px(3), THEME.px(3), -THEME.px(3), -THEME.px(3))
            icons.paint(painter, "check", inner, check, stroke=3.2)
        if self.hasFocus():
            painter.setPen(QPen(QColor(c.accent_strong), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-2.5, -2.5, 2.5, 2.5), THEME.px(7), THEME.px(7))
        if self.text():
            painter.setFont(THEME.font(13))
            painter.setPen(QColor(c.ink if self.isEnabled() else c.ink3))
            painter.drawText(QRectF(rect.right() + THEME.px(10), 0, self.width(), self.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
