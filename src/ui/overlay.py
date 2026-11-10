"""
In-window overlays: the app behind gets blurred and dimmed (and keeps updating
live), panels fade and rise into place. Overlays can stack (a confirmation on
top of the config panel); Escape or a click on the dimmed area asks the top
panel to close. While a panel is open, Tab keeps the focus inside it.
"""

from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsBlurEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.ui.controls import IconButton, TextButton, Tween, connect_running, fade, settle_fades
from src.ui.theme import THEME


class Panel(QFrame):
    """Base class for overlay panels (rounded card with an optional title + close button)."""

    closeRequested = Signal()

    def __init__(self, title: str = "", parent: QWidget | None = None, closable: bool = True,
                 width: int = 560) -> None:
        super().__init__(parent)
        self.setObjectName("OverlayPanel")
        self._width = width
        self._themed: list[tuple[QObject, Callable[[], None]]] = []
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.outer = QVBoxLayout(self)
        self.themed(self, lambda: (
            self.outer.setSpacing(THEME.px(14)),
            self.outer.setContentsMargins(THEME.px(24), THEME.px(20), THEME.px(24), THEME.px(22))))
        if title:
            header = QHBoxLayout()
            header.setSpacing(THEME.px(8))
            self.title_label = QLabel(title)
            self.themed(self.title_label, lambda: self.title_label.setFont(THEME.font(17, QFont.Weight.Bold)))
            self.title_label.setStyleSheet(f"color: {THEME.colors.ink}; background: transparent;")
            header.addWidget(self.title_label)
            header.addStretch(1)
            if closable:
                close = IconButton("x", "Close (Esc)", self, size=30, icon_size=18)
                close.clicked.connect(self.request_close)
                header.addWidget(close)
            self.outer.addLayout(header)
        THEME.changed.connect(self._retheme)

    def themed(self, owner: QObject, apply: Callable[[], object]) -> None:
        """Run ``apply`` now and again whenever the UI scale changes (fonts and
        sizes come from THEME.px); dropped once ``owner`` is deleted."""
        apply()
        self._themed.append((owner, apply))

    def _retheme(self) -> None:
        alive = []
        for owner, apply in self._themed:
            if shiboken6.isValid(owner):
                apply()
                alive.append((owner, apply))
        self._themed = alive
        self.updateGeometry()

    def preferred_width(self) -> int:
        return THEME.px(self._width)

    def focusNextPrevChild(self, next_: bool) -> bool:  # noqa: N802 - Qt naming
        """Tab / Shift+Tab cycle through this panel only (the app behind is blurred)."""
        chain: list[QWidget] = []
        widget = self.nextInFocusChain()
        while widget is not None and widget is not self and len(chain) < 500:
            if (self.isAncestorOf(widget) and widget.isVisible() and widget.isEnabled()
                    and widget.focusPolicy() & Qt.FocusPolicy.TabFocus):
                chain.append(widget)
            widget = widget.nextInFocusChain()
        if not chain:
            return True
        focused = self.window().focusWidget()
        if focused in chain:
            index = (chain.index(focused) + (1 if next_ else -1)) % len(chain)
        else:
            index = 0 if next_ else len(chain) - 1
        chain[index].setFocus(Qt.FocusReason.TabFocusReason if next_ else Qt.FocusReason.BacktabFocusReason)
        return True

    def request_close(self) -> None:
        """Override to confirm (e.g. unsaved changes) before emitting ``closeRequested``."""
        self.closeRequested.emit()

    def on_shown(self) -> None:
        """Called once the panel is fully visible (focus the first field, ...)."""

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = THEME.px(16)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(THEME.colors.raised))
        painter.setPen(QPen(QColor("#253A5E"), 1))
        painter.drawPath(path)


class _Layer(QWidget):
    """Full-size layer: dims what is below and centers one panel."""

    def __init__(self, host: "OverlayHost", panel: Panel, dim: float) -> None:
        super().__init__(host)
        self.host = host
        self.panel = panel
        self._dim = dim
        self._rise = Tween(self, self._place_panel, value=1.0, duration=THEME.SLOW)
        # Size changes of the panel (rows added or removed) glide from this size.
        self._resize = Tween(self, self._place_panel, value=1.0, duration=THEME.NORMAL)
        self._resize_from: tuple[int, int] | None = None
        panel.setParent(self)
        panel.installEventFilter(self)
        self.setGeometry(host.rect())
        THEME.changed.connect(self._place_panel)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        # The panel's content changed size (rows added, scale changed): re-place it.
        if watched is self.panel and event.type() == QEvent.Type.LayoutRequest:
            QTimer.singleShot(0, self, self._content_resized)
        return False

    def _target_size(self) -> tuple[int, int]:
        margin = THEME.px(28)
        width = min(self.panel.preferred_width(), self.width() - 2 * margin)
        height = min(self.panel.sizeHint().height(), self.height() - 2 * margin)
        return width, height

    def _content_resized(self) -> None:
        current = (self.panel.width(), self.panel.height())
        if self._target_size() == current:
            return
        if self._rise.running or not THEME.motion or not self.isVisible():
            self._place_panel()
            return
        self._resize_from = current
        self._resize.jump(0.0)
        self._resize.to(1.0)

    def _place_panel(self) -> None:
        width, height = self._target_size()
        progress = self._resize.value
        if self._resize_from is not None and progress < 1.0:
            width = round(self._resize_from[0] + (width - self._resize_from[0]) * progress)
            height = round(self._resize_from[1] + (height - self._resize_from[1]) * progress)
        x = (self.width() - width) // 2
        y = (self.height() - height) // 2 + round(THEME.px(14) * self._rise.value)
        self.panel.setGeometry(QRect(x, y, width, height))
        self.update()

    def rise_in(self) -> None:
        self._rise.jump(1.0)
        self._rise.to(0.0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_panel()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        color = QColor(THEME.colors.scrim)
        color.setAlphaF(self._dim)
        painter.fillRect(self.rect(), color)
        # Soft shadow under the panel, painted here (a QGraphicsDropShadowEffect
        # would nest with the layer's fade effect, which Qt renders unreliably).
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.panel.geometry()).translated(0, THEME.px(10))
        radius = THEME.px(16)
        steps = 10
        for step in range(steps, 0, -1):
            spread = THEME.px(3) * step
            shade = QColor(0, 0, 0)
            shade.setAlphaF(0.045 * (1 - step / (steps + 1)) + 0.01)
            painter.setBrush(shade)
            painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread),
                                    radius + spread, radius + spread)

    def mousePressEvent(self, event) -> None:
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.panel.request_close()
        event.accept()


class OverlayHost(QWidget):
    """Covers the whole window; owns the stacked layers and the background blur."""

    opened = Signal()  # a panel was put on top (toasts raise themselves above it)

    def __init__(self, root: QWidget, blurred: QWidget) -> None:
        super().__init__(root)
        self._blurred = blurred
        self._layers: list[_Layer] = []
        self._blur_effect: QGraphicsBlurEffect | None = None
        self._blur_anim = QVariantAnimation(self)
        self._blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        connect_running(self._blur_anim, self._set_blur)
        self._blur_anim.finished.connect(self._blur_finished)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), root)
        self._escape.setContext(Qt.ShortcutContext.WindowShortcut)
        self._escape.activated.connect(self._escape_pressed)
        self._escape.setEnabled(False)
        self.hide()

    # ---------------------------------------------------------------- state
    def is_open(self) -> bool:
        return bool(self._layers)

    def top_panel(self) -> Panel | None:
        return self._layers[-1].panel if self._layers else None

    def contains_panel(self, kind: type) -> Panel | None:
        for layer in self._layers:
            if isinstance(layer.panel, kind):
                return layer.panel
        return None

    # --------------------------------------------------------------- opening
    def open(self, panel: Panel) -> None:
        first = not self._layers
        layer = _Layer(self, panel, dim=0.50 if first else 0.35)
        panel.closeRequested.connect(lambda p=panel: self.close(p))
        self._layers.append(layer)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        layer.show()
        layer.raise_()
        layer._place_panel()
        if first:
            self._escape.setEnabled(True)
            THEME.set_ambient_motion(False)
            settle_fades(self._blurred)
            self._animate_blur(THEME.px(7))
        fade(layer, True, THEME.NORMAL, on_finished=panel.on_shown)
        layer.rise_in()
        self.opened.emit()

    def close(self, panel: Panel, on_closed: Callable[[], None] | None = None) -> None:
        layer = next((item for item in self._layers if item.panel is panel), None)
        if layer is None:
            return
        self._layers.remove(layer)
        last = not self._layers
        # While it fades out it takes no clicks or keys any more.
        layer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        focused = QApplication.focusWidget()
        if focused is not None and layer.isAncestorOf(focused):
            if self._layers:
                self._layers[-1].panel.setFocus()
            else:
                focused.clearFocus()

        def finished() -> None:
            layer.deleteLater()
            if last and not self._layers:
                self.hide()
            elif self._layers:
                top = self._layers[-1]
                focused = self.window().focusWidget()
                if focused is None or not top.isAncestorOf(focused):
                    top.panel.setFocus()  # but never take it back from a field clicked meanwhile
            if on_closed:
                on_closed()

        settle_fades(layer)  # no fades inside a fading layer (Qt cannot nest effects)
        fade(layer, False, THEME.FAST, on_finished=finished)
        if last:
            self._escape.setEnabled(False)
            THEME.set_ambient_motion(True)
            self._animate_blur(0)

    def _escape_pressed(self) -> None:
        panel = self.top_panel()
        if panel is not None:
            panel.request_close()

    # ------------------------------------------------------------------ blur
    def _animate_blur(self, target: float) -> None:
        if self._blur_effect is None and target > 0:
            self._blur_effect = QGraphicsBlurEffect(self._blurred)
            self._blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
            self._blur_effect.setBlurRadius(0)
            self._blurred.setGraphicsEffect(self._blur_effect)
        if self._blur_effect is None:
            return
        start = float(self._blur_effect.blurRadius())
        self._blur_anim.stop()
        duration = THEME.duration(THEME.NORMAL if target else THEME.FAST)
        if duration <= 0:
            self._set_blur(target)
            self._blur_finished()
            return
        self._blur_anim.setDuration(duration)
        self._blur_anim.setStartValue(start)
        self._blur_anim.setEndValue(float(target))
        self._blur_anim.start()

    def _set_blur(self, value) -> None:
        if self._blur_effect is not None:
            self._blur_effect.setBlurRadius(float(value))

    def _blur_finished(self) -> None:
        if self._blur_effect is not None and self._blur_effect.blurRadius() <= 0.01 and not self._layers:
            self._blurred.setGraphicsEffect(None)  # deletes the effect
            self._blur_effect = None

    # ---------------------------------------------------------------- layout
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for layer in self._layers:
            layer.setGeometry(self.rect())


class ConfirmDialog(Panel):
    """Yes/No question in the app style (used instead of native message boxes)."""

    def __init__(self, title: str, message: str, on_answer: Callable[[bool], None],
                 yes_text: str = "Yes", no_text: str = "No", danger: bool = False) -> None:
        super().__init__(title, closable=False, width=440)
        self._on_answer = on_answer
        self._answered = False
        text = QLabel(message)
        text.setWordWrap(True)
        self.themed(text, lambda: text.setFont(THEME.font(13.5)))
        text.setStyleSheet(f"color: {THEME.colors.ink2}; background: transparent;")
        self.outer.addWidget(text)
        buttons = QHBoxLayout()
        buttons.setSpacing(THEME.px(10))
        buttons.addStretch(1)
        self.no_button = TextButton(no_text, "secondary")
        self.yes_button = TextButton(yes_text, "danger" if danger else "primary")
        self.no_button.clicked.connect(lambda: self._answer(False))
        self.yes_button.clicked.connect(lambda: self._answer(True))
        buttons.addWidget(self.no_button)
        buttons.addWidget(self.yes_button)
        self.outer.addSpacing(THEME.px(4))
        self.outer.addLayout(buttons)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(self.preferred_width(), hint.height())

    def on_shown(self) -> None:
        self.yes_button.setFocus()

    def request_close(self) -> None:
        self._answer(False)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            self._answer(focused is not self.no_button)
            return
        super().keyPressEvent(event)

    def _answer(self, value: bool) -> None:
        if self._answered:
            return
        self._answered = True
        self.closeRequested.emit()
        self._on_answer(value)
