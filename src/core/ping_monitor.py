"""
Main Ping Monitor application class.
"""

import threading
import time
import os
from collections import deque

from src.core.config import (
    SERVERS,
    PING_THRESHOLD,
    PING_INTERVAL,
    PRESERVED_MINUTES,
    ICON_FILE,
)
from src.core.ping_service import PingService
from src.gui.main_window import MainWindow
from src.gui.system_tray import SystemTray
from src.utils.deviation_logger import DeviationLogger


class PingMonitor:
    """Main application class that coordinates all components"""

    def __init__(self):
        # Configuration
        self.servers = SERVERS
        self.ping_threshold = PING_THRESHOLD
        self.ping_interval = PING_INTERVAL
        self.preserved_minutes = PRESERVED_MINUTES
        self.max_display_lines_per_server = int(
            self.preserved_minutes * (60 / self.ping_interval)
        )

        # Get first server for tray icon status
        self.first_server = list(self.servers.keys())[0]

        # Application state
        self.running = True
        self.window_visible = True  # Start visible now

        # Initialize components
        self.ping_service = None
        self.main_window = None
        self.system_tray = None
        self.deviation_logger = None

        # Statistics tracking
        self.ping_times = {}
        self.deviation_counts = {}
        for server_name in self.servers.keys():
            self.ping_times[server_name] = deque(
                maxlen=self.max_display_lines_per_server
            )
            self.deviation_counts[server_name] = 0

        self._initialize_components()

    def _initialize_components(self):
        """Initialize all application components"""
        # Initialize ping service
        self.ping_service = PingService(
            servers=self.servers,
            ping_interval=self.ping_interval,
            ping_threshold=self.ping_threshold,
            max_display_lines=self.max_display_lines_per_server,
        )

        # Initialize deviation logger
        self.deviation_logger = DeviationLogger()

        # Initialize GUI
        self.main_window = MainWindow(self.servers, self)

        # Initialize system tray
        icon_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            ICON_FILE,
        )
        self.system_tray = SystemTray(self, icon_path)

    def run(self):
        """Start the application"""
        try:
            # Start main GUI loop
            # The GUI will call start_services() when ready (after first run config if needed)
            self.main_window.mainloop()

        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self._shutdown()

    def start_services(self):
        """Start background services (ping, tray, cleanup)"""
        # Start ping service
        self.ping_service.perform_warmup_pings()
        self.ping_service.start_ping_thread()

        # Start system tray in a separate thread
        tray_thread = threading.Thread(target=self.system_tray.run, daemon=True)
        tray_thread.start()

        # Start periodic cleanup
        self._start_periodic_cleanup()

    def _start_periodic_cleanup(self):
        """Start periodic cleanup of deviation logs"""

        def cleanup_worker():
            while self.running:
                try:
                    self.deviation_logger.cleanup_deviations_file()
                    time.sleep(3600)  # Run cleanup every hour
                except Exception as e:
                    print(f"Error in cleanup worker: {e}")

        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()

    def _process_ping_result(self, result):
        """Process a ping result and update displays"""
        server_name = result["server"]

        # Format result for display
        formatted_result = self.ping_service.format_ping_result(server_name, result)

        # Update statistics
        if formatted_result["ping_time"] is not None:
            self.ping_times[server_name].append(formatted_result["ping_time"])

        # Check for deviations and log them
        if self.ping_service.is_deviation(result):
            self.deviation_counts[server_name] += 1
            self.deviation_logger.log_deviation(server_name, result)

        # Calculate statistics
        statistics = self._calculate_statistics(server_name)

        # Update GUI display
        if self.main_window:
            self.main_window.update_display(server_name, formatted_result, statistics)

        # Update system tray icon based on all server results
        self.system_tray.update_icon_status({server_name: result}, self.first_server)

    def _calculate_statistics(self, server_name):
        """Calculate statistics for a server"""
        if not self.ping_times[server_name]:
            return {"avg": 0, "best": 0, "worst": 0, "deviations": 0}

        ping_times = list(self.ping_times[server_name])
        avg_ping = sum(ping_times) / len(ping_times)
        best_ping = min(ping_times)
        worst_ping = max(ping_times)

        return {
            "avg": avg_ping,
            "best": best_ping,
            "worst": worst_ping,
            "deviations": self.deviation_counts[server_name],
        }

    def show_window(self, icon=None, item=None):
        """Show the main window"""
        if self.main_window:
            self.main_window.show()
            self.window_visible = True
            if self.system_tray:
                self.system_tray.refresh_menu()

    def hide_window(self, icon=None, item=None):
        """Hide the main window"""
        if self.main_window:
            self.main_window.hide()
            self.window_visible = False
            if self.system_tray:
                self.system_tray.refresh_menu()

    def quit(self):
        """Quit the application (called from window close button)"""
        self.quit_application()

    def quit_application(self, icon=None, item=None):
        """Quit the entire application"""
        self._shutdown()

    def _shutdown(self):
        """Clean shutdown of all components"""
        print("Shutting down Ping Monitor...")
        self.running = False

        # Stop ping service
        if self.ping_service:
            self.ping_service.stop()

        # Stop system tray
        if self.system_tray:
            self.system_tray.stop()

        # Destroy GUI
        if self.main_window:
            try:
                self.main_window.destroy()
            except:
                pass
