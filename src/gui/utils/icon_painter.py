from PIL import Image, ImageDraw
import math


class IconPainter:
    """
    Utility class to draw high-quality icons using PIL.
    This avoids external dependencies like pygame or lxml which fail on Python 3.14.
    """

    @staticmethod
    def draw_icon(name, color, size=24):
        """Draw an icon by name"""
        # Create image with transparent background
        # Draw at 4x resolution and downscale for anti-aliasing
        scale = 4
        actual_size = size * scale
        img = Image.new("RGBA", (actual_size, actual_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Set stroke width (scaled)
        width = int(2 * scale)

        if name == "config":
            IconPainter._draw_settings(draw, actual_size, color, width)
        elif name == "logs":
            IconPainter._draw_file_description(draw, actual_size, color, width)
        elif name == "reset":
            IconPainter._draw_rotate_clockwise(draw, actual_size, color, width)

        # Resize down with high quality resampling
        return img.resize((size, size), Image.Resampling.LANCZOS)

    @staticmethod
    def _draw_settings(draw, size, color, width):
        """Draw a gear/settings icon"""
        center = size / 2
        radius_outer = size * 0.4
        radius_inner = size * 0.25

        # Draw the main ring
        draw.ellipse(
            [
                center - radius_inner,
                center - radius_inner,
                center + radius_inner,
                center + radius_inner,
            ],
            outline=color,
            width=width,
        )

        # Draw teeth
        num_teeth = 8
        tooth_depth = size * 0.12

        for i in range(num_teeth):
            angle = (360 / num_teeth) * i
            rad = math.radians(angle)

            # Tooth center position on outer circle
            x = center + (radius_inner + width / 2) * math.cos(rad)
            y = center + (radius_inner + width / 2) * math.sin(rad)

            # Draw tooth as a thick line
            end_x = center + (radius_inner + tooth_depth) * math.cos(rad)
            end_y = center + (radius_inner + tooth_depth) * math.sin(rad)

            draw.line([(x, y), (end_x, end_y)], fill=color, width=width * 2)

    @staticmethod
    def _draw_file_description(draw, size, color, width):
        """Draw a file description icon"""
        padding = size * 0.2
        w = size - 2 * padding
        h = size - 2 * padding
        x = padding
        y = padding

        # Document outline (with folded corner effect simplified)
        # Main rectangle
        draw.rectangle([x, y, x + w, y + h], outline=color, width=width)

        # Lines inside
        line_x_start = x + w * 0.25
        line_x_end = x + w * 0.75
        line_gap = h * 0.2

        # Top line
        draw.line(
            [line_x_start, y + h * 0.3, line_x_end, y + h * 0.3],
            fill=color,
            width=width,
        )
        # Middle line
        draw.line(
            [line_x_start, y + h * 0.5, line_x_end, y + h * 0.5],
            fill=color,
            width=width,
        )
        # Bottom line
        draw.line(
            [line_x_start, y + h * 0.7, line_x_end, y + h * 0.7],
            fill=color,
            width=width,
        )

    @staticmethod
    def _draw_rotate_clockwise(draw, size, color, width):
        """Draw a rotate clockwise icon"""
        center = size / 2
        radius = size * 0.35

        # Draw arc (almost full circle)
        # Start at -45 deg (top right), go clockwise to 225 deg
        bbox = [center - radius, center - radius, center + radius, center + radius]
        draw.arc(bbox, start=30, end=330, fill=color, width=width)

        # Draw arrow head at the end (330 degrees)
        # Position on circle at 330 degrees
        angle_rad = math.radians(330)
        arrow_tip_x = center + radius * math.cos(angle_rad)
        arrow_tip_y = center + radius * math.sin(angle_rad)

        # Arrow head points
        head_size = size * 0.15

        # Calculate direction vector tangent to circle
        # Tangent at angle theta is (-sin(theta), cos(theta))
        tan_x = -math.sin(angle_rad)
        tan_y = math.cos(angle_rad)

        # Back up a bit along the tangent
        base_x = arrow_tip_x - tan_x * head_size
        base_y = arrow_tip_y - tan_y * head_size

        # Perpendicular to tangent
        perp_x = -tan_y
        perp_y = tan_x

        # Triangle points
        p1 = (
            arrow_tip_x + tan_x * head_size * 0.5,
            arrow_tip_y + tan_y * head_size * 0.5,
        )  # Tip slightly forward
        p2 = (base_x + perp_x * head_size * 0.6, base_y + perp_y * head_size * 0.6)
        p3 = (base_x - perp_x * head_size * 0.6, base_y - perp_y * head_size * 0.6)

        draw.polygon([p1, p2, p3], fill=color)
