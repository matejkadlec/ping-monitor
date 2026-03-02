"""
System tray icon functionality for the Ping Monitor application.
"""

import os
import pystray
from PIL import Image, ImageDraw


class SystemTray:
    """Handles system tray icon and menu functionality"""

    def __init__(self, app_instance, icon_path=None):
        self.app = app_instance
        self.icon_path = icon_path
        self.tray_icon = None
        self.current_status = "neutral"
        self.icon_images = {
            "healthy": None,
            "degraded": None,
            "failing": None,
            "green": None,
            "yellow": None,
            "red": None,
            "neutral": None,
        }

        self._setup_tray()

    def _setup_tray(self):
        """Setup system tray icon"""
        # Create dynamic circle icons as requested
        self._create_circle_icons()

        # Set initial icon image to neutral
        self.icon_image = self.icon_images["neutral"]

        # Create tray icon with dynamic menu
        self.tray_icon = pystray.Icon(
            "PingMonitor", self.icon_image, "Ping Monitor", self._create_menu()
        )

    def _create_menu(self):
        """Create a dynamic menu based on current window state"""
        return pystray.Menu(
            lambda: [
                # Show option - enabled only when window is hidden
                pystray.MenuItem(
                    "Show",
                    self.app.show_window,
                    enabled=not self.app.window_visible,
                    default=not self.app.window_visible,
                ),
                # Hide option - enabled only when window is visible
                pystray.MenuItem(
                    "Hide",
                    self.app.hide_window,
                    enabled=self.app.window_visible,
                    default=self.app.window_visible,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self.app.quit_application),
            ]
        )

    def _create_circle_icons(self):
        """Create simple colored circles for tray icon"""
        size = (32, 32)

        # Neutral (Grey) - Initial state
        neutral_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(neutral_img)
        # Draw circle
        draw.ellipse(
            [4, 4, 28, 28], fill=(128, 128, 128, 255), outline=(80, 80, 80, 255)
        )
        self.icon_images["neutral"] = neutral_img

        # Green - Good connection
        green_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(green_img)
        draw.ellipse([4, 4, 28, 28], fill=(0, 255, 0, 255), outline=(0, 150, 0, 255))
        self.icon_images["green"] = green_img
        self.icon_images["healthy"] = green_img

        # Yellow - Degraded connection
        yellow_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(yellow_img)
        draw.ellipse(
            [4, 4, 28, 28], fill=(255, 200, 0, 255), outline=(170, 130, 0, 255)
        )
        self.icon_images["yellow"] = yellow_img
        self.icon_images["degraded"] = yellow_img

        # Red - Failing connection
        red_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(red_img)
        draw.ellipse([4, 4, 28, 28], fill=(255, 0, 0, 255), outline=(150, 0, 0, 255))
        self.icon_images["red"] = red_img
        self.icon_images["failing"] = red_img

    def update_health_status(self, health_status):
        """Update tray icon and tooltip for Healthy/Degraded/Failing states."""
        if health_status not in {"healthy", "degraded", "failing"}:
            health_status = "neutral"

        if health_status != self.current_status:
            self.current_status = health_status
            if self.tray_icon and self.icon_images.get(health_status):
                self.tray_icon.icon = self.icon_images[health_status]
                self.refresh_menu()

        if self.tray_icon:
            if health_status == "neutral":
                self.tray_icon.title = "Ping Monitor"
            else:
                self.tray_icon.title = f"Ping Monitor - {health_status.title()}"

    def refresh_menu(self):
        """Refresh the tray menu to reflect current state"""
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception as e:
                print(f"Error refreshing tray menu: {e}")

    def run(self):
        """Start the system tray icon"""
        if self.tray_icon:
            self.tray_icon.run()

    def stop(self):
        """Stop the system tray icon"""
        if self.tray_icon:
            self.tray_icon.stop()
