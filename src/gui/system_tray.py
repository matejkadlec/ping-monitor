"""
System tray icon functionality for the Ping Monitor application.
"""

import os
import pystray
from PIL import Image, ImageDraw
from collections import deque


class SystemTray:
    """Handles system tray icon and menu functionality"""

    def __init__(self, app_instance, icon_path=None):
        self.app = app_instance
        self.icon_path = icon_path
        self.tray_icon = None
        self.current_status = "neutral"  # 'green', 'red', or 'neutral'
        self.icon_images = {
            "green": None,
            "red": None,
            "neutral": None,
        }  # Cache for icon images

        # For tracking first server status (used for tray icon color)
        self.first_server_ping_history = deque(maxlen=10)
        self.first_ping_received = False

        self._setup_tray()

    def _setup_tray(self):
        """Setup system tray icon"""
        # Try to use icon.ico if available, otherwise create fallback
        if self.icon_path and os.path.exists(self.icon_path):
            try:
                self._load_icon_states()
            except Exception as e:
                print(f"Error loading icon states: {e}")
                self._create_fallback_icons()
        else:
            if self.icon_path:
                print(f"Icon file not found at: {self.icon_path}")
            self._create_fallback_icons()

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

    def _load_icon_states(self):
        """Load and cache all icon states"""
        if not self.icon_path:
            return

        try:
            # Load base icon
            base_image = Image.open(self.icon_path)
            if base_image.mode != "RGBA":
                base_image = base_image.convert("RGBA")

            # Create different colored states
            self.icon_images["neutral"] = base_image.copy()

            # Create green tinted version
            green_overlay = Image.new("RGBA", base_image.size, (0, 255, 0, 60))
            self.icon_images["green"] = Image.alpha_composite(base_image, green_overlay)

            # Create red tinted version
            red_overlay = Image.new("RGBA", base_image.size, (255, 0, 0, 60))
            self.icon_images["red"] = Image.alpha_composite(base_image, red_overlay)

        except Exception as e:
            print(f"Error in load_icon_states: {e}")
            self._create_fallback_icons()

    def _create_fallback_icons(self):
        """Create simple fallback icons if main icon is not available"""
        # Create simple 32x32 colored circles as fallback icons
        size = (32, 32)

        # Neutral (white/gray)
        neutral_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(neutral_img)
        draw.ellipse(
            [4, 4, 28, 28], fill=(200, 200, 200, 255), outline=(100, 100, 100, 255)
        )
        self.icon_images["neutral"] = neutral_img

        # Green
        green_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(green_img)
        draw.ellipse([4, 4, 28, 28], fill=(0, 255, 0, 255), outline=(0, 150, 0, 255))
        self.icon_images["green"] = green_img

        # Red
        red_img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(red_img)
        draw.ellipse([4, 4, 28, 28], fill=(255, 0, 0, 255), outline=(150, 0, 0, 255))
        self.icon_images["red"] = red_img

    def update_icon_status(self, server_results, first_server_name):
        """Update tray icon color based on server results"""
        if not server_results or first_server_name not in server_results:
            return

        first_server_result = server_results[first_server_name]

        # Record ping result for the first server
        if (
            first_server_result["status"] == "success"
            and first_server_result["time"] is not None
        ):
            self.first_server_ping_history.append(first_server_result["time"])
            self.first_ping_received = True

        # Don't change icon until we have some ping data
        if not self.first_ping_received:
            return

        # Determine new status based on recent ping history
        new_status = self._calculate_status()

        # Update icon if status changed
        if new_status != self.current_status:
            self.current_status = new_status
            if self.tray_icon and self.icon_images.get(new_status):
                self.tray_icon.icon = self.icon_images[new_status]
                self.refresh_menu()

    def _calculate_status(self):
        """Calculate status based on ping history"""
        if not self.first_server_ping_history:
            return "neutral"

        # Count how many of the recent pings are above threshold (60ms)
        recent_pings = list(self.first_server_ping_history)
        high_pings = sum(1 for ping in recent_pings if ping > 60)
        total_pings = len(recent_pings)

        # If more than 30% of recent pings are high, show red
        if total_pings > 0 and (high_pings / total_pings) > 0.3:
            return "red"
        else:
            return "green"

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
