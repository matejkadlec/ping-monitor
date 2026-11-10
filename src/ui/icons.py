"""
Lucide line icons (ISC license, see assets/icons/LICENSE-lucide.txt) rendered
from SVG in any color and size, crisp on high-DPI screens.
"""

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.core.paths import asset_path


@lru_cache(maxsize=64)
def _svg_source(name: str) -> str:
    return asset_path("icons", f"{name}.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=256)
def _renderer(name: str, rgb: str, stroke: float) -> QSvgRenderer:
    svg = _svg_source(name).replace("currentColor", rgb)
    svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke:g}"')
    return QSvgRenderer(QByteArray(svg.encode("utf-8")))


def _device_ratio() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app else None
    return max(1.0, screen.devicePixelRatio() if screen else 1.0)


def paint(painter: QPainter, name: str, rect: QRectF, color: QColor | str, stroke: float = 2.0) -> None:
    """Draw an icon straight into ``rect`` (vector quality at any scale)."""
    color = QColor(color)
    renderer = _renderer(name, color.name(QColor.NameFormat.HexRgb), round(stroke, 2))
    painter.save()
    painter.setOpacity(painter.opacity() * color.alphaF())
    renderer.render(painter, rect)
    painter.restore()


@lru_cache(maxsize=512)
def _cached_pixmap(name: str, argb: str, size: int, stroke: float, ratio: float) -> QPixmap:
    image = QPixmap(max(1, round(size * ratio)), max(1, round(size * ratio)))
    image.fill(Qt.GlobalColor.transparent)
    image.setDevicePixelRatio(ratio)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint(painter, name, QRectF(0, 0, size, size), QColor(argb), stroke)
    painter.end()
    return image


def pixmap(name: str, color: QColor | str, size: int, stroke: float = 2.0,
           ratio: float | None = None) -> QPixmap:
    ratio = round(ratio or _device_ratio(), 2)
    return _cached_pixmap(name, QColor(color).name(QColor.NameFormat.HexArgb), size, round(stroke, 2), ratio)


def icon(name: str, color: QColor | str, size: int = 18, stroke: float = 2.0) -> QIcon:
    result = QIcon()
    for ratio in (1.0, 1.25, 1.5, 2.0):
        result.addPixmap(pixmap(name, color, size, stroke, ratio))
    return result
