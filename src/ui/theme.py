"""
Design tokens (colors, type, spacing, motion) and the global stylesheet.

Everything visual reads from the single ``THEME`` instance, so the UI scale
(window vs. full screen) and motion preferences are applied in one place.
"""

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase

from src.core.models import HealthStatus, LatencyLevel
from src.core.paths import asset_path

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Colors:
    abyss: str = "#08111F"  # window background
    deep: str = "#0C1729"  # chart and stream panels
    raised: str = "#122039"  # overlays, menus, toasts, inputs
    raised_hover: str = "#192B4B"
    hairline: str = "#1C2C48"  # borders
    grid: str = "#16253E"  # chart gridlines
    ink: str = "#E8EEF9"  # primary text
    ink2: str = "#A9B6CE"  # secondary text
    ink3: str = "#7A8AA6"  # muted text
    accent: str = "#7AA2FF"  # interaction + the pulse line
    accent_strong: str = "#A2BEFF"
    on_accent: str = "#08111F"
    good: str = "#4A964F"
    good_text: str = "#6CC071"
    warn: str = "#D4A72C"
    warn_text: str = "#E2BD55"
    bad: str = "#C73C3C"
    bad_text: str = "#EF6B6B"
    neutral: str = "#5C6B86"
    scrim: str = "#04080F"  # overlay dimming base


COLORS = Colors()

UI_FAMILY_PREFERRED = "Montserrat"
MONO_FAMILY_PREFERRED = "JetBrains Mono"
_FONT_FILES = (
    "Montserrat-Regular.ttf",
    "Montserrat-Medium.ttf",
    "Montserrat-SemiBold.ttf",
    "Montserrat-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Medium.ttf",
    "JetBrainsMono-Bold.ttf",
)


def qcolor(value: str, alpha: float | None = None) -> QColor:
    color = QColor(value)
    if alpha is not None:
        color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


def mix(a: QColor | str, b: QColor | str, t: float) -> QColor:
    """Linear blend of two colors (t=0 -> a, t=1 -> b), alpha included."""
    ca, cb = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(
        ca.redF() + (cb.redF() - ca.redF()) * t,
        ca.greenF() + (cb.greenF() - ca.greenF()) * t,
        ca.blueF() + (cb.blueF() - ca.blueF()) * t,
        ca.alphaF() + (cb.alphaF() - ca.alphaF()) * t,
    )


class Theme(QObject):
    """Runtime theme state. ``changed`` fires when the UI scale changes."""

    changed = Signal()

    # Motion (ms). Set to zero when the OS asks for reduced motion.
    FAST = 120
    NORMAL = 200
    SLOW = 320

    def __init__(self) -> None:
        super().__init__()
        self.colors = COLORS
        self.scale = 1.0
        self.ui_family = UI_FAMILY_PREFERRED
        self.mono_family = MONO_FAMILY_PREFERRED
        self.motion = True
        # Ambient motion (sonar ring, row highlights) pauses while an overlay is
        # open, so the blurred background only re-renders when data changes.
        self.ambient = True

    # ------------------------------------------------------------- set-up
    def load_fonts(self) -> None:
        loaded: set[str] = set()
        for name in _FONT_FILES:
            font_id = QFontDatabase.addApplicationFont(str(asset_path("fonts", name)))
            if font_id < 0:
                LOGGER.warning("Could not load font %s", name)
                continue
            loaded.update(QFontDatabase.applicationFontFamilies(font_id))
        if UI_FAMILY_PREFERRED not in loaded:
            self.ui_family = "Segoe UI"
        if MONO_FAMILY_PREFERRED not in loaded:
            self.mono_family = "Consolas"

    def set_motion(self, enabled: bool) -> None:
        self.motion = enabled

    def duration(self, ms: int) -> int:
        return ms if self.motion else 0

    def set_ambient_motion(self, enabled: bool) -> None:
        self.ambient = enabled

    @property
    def ambient_active(self) -> bool:
        return self.motion and self.ambient

    def set_scale(self, scale: float) -> None:
        scale = round(max(0.85, min(1.4, scale)), 2)
        if abs(scale - self.scale) > 1e-3:
            self.scale = scale
            self.changed.emit()

    # ------------------------------------------------------------- helpers
    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def font(self, size: float, weight: QFont.Weight = QFont.Weight.Normal,
             mono: bool = False, tabular: bool = False) -> QFont:
        font = QFont(self.mono_family if mono else self.ui_family)
        font.setPixelSize(self.px(size))
        font.setWeight(weight)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        if tabular and not mono:
            font.setFeature(QFont.Tag("tnum"), 1)
        return font

    def level_color(self, level: LatencyLevel, text: bool = False) -> QColor:
        c = self.colors
        mapping = {
            LatencyLevel.EXCELLENT: (c.good, c.good_text),
            LatencyLevel.GOOD: (c.warn, c.warn_text),
            LatencyLevel.BAD: (c.bad, c.bad_text),
            LatencyLevel.LOST: (c.bad, c.bad_text),
            LatencyLevel.GAP: (c.neutral, c.ink3),
        }
        fill, ink = mapping[level]
        return QColor(ink if text else fill)

    def health_color(self, status: HealthStatus, text: bool = False) -> QColor:
        c = self.colors
        mapping = {
            HealthStatus.UNKNOWN: (c.neutral, c.ink2),
            HealthStatus.HEALTHY: (c.good, c.good_text),
            HealthStatus.DEGRADED: (c.warn, c.warn_text),
            HealthStatus.FAILING: (c.bad, c.bad_text),
        }
        fill, ink = mapping[status]
        return QColor(ink if text else fill)

    # ---------------------------------------------------------- stylesheet
    def stylesheet(self) -> str:
        c = self.colors
        px = self.px
        return f"""
        QWidget {{ color: {c.ink}; }}
        QMainWindow, #Root {{ background: {c.abyss}; }}
        QToolTip {{
            background: {c.raised};
            color: {c.ink};
            border: 1px solid {c.hairline};
            border-radius: {px(6)}px;
            padding: {px(6)}px {px(9)}px;
            font-family: "{self.ui_family}";
            font-size: {px(12)}px;
        }}
        QMenu {{
            background: {c.raised};
            border: 1px solid {c.hairline};
            border-radius: {px(10)}px;
            padding: {px(5)}px;
        }}
        QMenu::item {{
            padding: {px(7)}px {px(14)}px;
            border-radius: {px(6)}px;
            color: {c.ink};
            font-family: "{self.ui_family}";
            font-size: {px(13)}px;
        }}
        QMenu::item:selected {{ background: {c.raised_hover}; }}
        QMenu::item:disabled {{ color: {c.ink3}; }}
        QMenu::separator {{
            height: 1px;
            background: {c.hairline};
            margin: {px(5)}px {px(8)}px;
        }}
        QMenu::indicator {{ width: 0px; height: 0px; }}
        QMenu::icon {{ padding-left: {px(4)}px; }}
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
        QLineEdit {{
            background: {c.abyss};
            border: 1px solid {c.hairline};
            border-radius: {px(8)}px;
            padding: {px(6)}px {px(10)}px;
            color: {c.ink};
            selection-background-color: {c.accent};
            selection-color: {c.on_accent};
        }}
        QLineEdit:hover {{ border-color: #2A3F63; }}
        QLineEdit:focus {{ border-color: {c.accent}; }}
        QLineEdit[invalid="true"] {{ border-color: {c.bad}; }}
        QLineEdit:disabled {{ color: {c.ink3}; }}
        """


THEME = Theme()
