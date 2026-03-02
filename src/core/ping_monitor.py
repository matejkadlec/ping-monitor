"""
Main Ping Monitor application class.
"""

import threading
import time
import os
import logging
from collections import deque
from datetime import timedelta

from src.core.config import (
    SERVERS,
    PING_THRESHOLD_HEALTHY,
    PING_THRESHOLD_DEGRADED,
    PING_INTERVAL,
    PRESERVED_MINUTES,
    ICON_FILE,
    PING_SPIKES_FILE,
)
from src.core.ping_service import PingService
from src.gui.main_window import MainWindow
from src.gui.system_tray import SystemTray
from src.utils.ping_spike_logger import PingSpikeLogger


class PingMonitor:
    """Main application class that coordinates all components"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Configuration
        self.servers = SERVERS
        self.ping_threshold_healthy = PING_THRESHOLD_HEALTHY
        self.ping_threshold_degraded = PING_THRESHOLD_DEGRADED
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
        self.ping_spike_logger = None

        # Statistics tracking
        self.ping_times = {}
        self.ping_time_history = {}
        self.ping_spike_counts = {}
        self.pinged_counts = {}
        self.first_ping_timestamps = {}
        for server_name in self.servers.keys():
            self.ping_times[server_name] = deque(
                maxlen=self.max_display_lines_per_server
            )
            self.ping_time_history[server_name] = deque(
                maxlen=self.max_display_lines_per_server
            )
            self.ping_spike_counts[server_name] = 0
            self.pinged_counts[server_name] = 0
            self.first_ping_timestamps[server_name] = None

        self._initialize_components()

    def _initialize_components(self):
        """Initialize all application components"""
        # Initialize ping service
        self.ping_service = PingService(
            servers=self.servers,
            ping_interval=self.ping_interval,
            ping_threshold_healthy=self.ping_threshold_healthy,
            ping_threshold_degraded=self.ping_threshold_degraded,
            max_display_lines=self.max_display_lines_per_server,
        )

        # Initialize ping spike logger
        self.ping_spike_logger = PingSpikeLogger(ping_spikes_file=PING_SPIKES_FILE)

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
            self.logger.info("Starting Ping Monitor main loop")
            # Start main GUI loop
            # The GUI will call start_services() when ready (after first run config if needed)
            self.main_window.mainloop()

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received, shutting down")
        finally:
            self._shutdown()

    def start_services(self):
        """Start background services (ping, tray, cleanup)"""
        self.logger.info("Starting background services")
        # Start ping service
        self.ping_service.perform_warmup_pings()
        self.ping_service.start_ping_thread()

        # Start system tray in a separate thread
        tray_thread = threading.Thread(target=self.system_tray.run, daemon=True)
        tray_thread.start()

        # Start periodic cleanup
        self._start_periodic_cleanup()

    def _start_periodic_cleanup(self):
        """Start periodic cleanup of ping spike logs"""

        def cleanup_worker():
            while self.running:
                try:
                    self.ping_spike_logger.cleanup_ping_spikes_file()
                    time.sleep(3600)  # Run cleanup every hour
                except Exception as e:
                    self.logger.exception("Error in cleanup worker: %s", e)

        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()

    def _process_ping_result(self, result):
        """Process a ping result and update displays"""
        server_name = result["server"]

        # Format result for display
        formatted_result = self.ping_service.format_ping_result(server_name, result)

        # Update statistics
        self.pinged_counts[server_name] += 1
        if self.first_ping_timestamps[server_name] is None:
            self.first_ping_timestamps[server_name] = result["timestamp"]

        if formatted_result["ping_time"] is not None:
            self.ping_times[server_name].append(formatted_result["ping_time"])
            self.ping_time_history[server_name].append(
                (result["timestamp"], formatted_result["ping_time"])
            )

        # Check for ping spikes and log them
        if self.ping_service.is_ping_spike(result):
            self.ping_spike_counts[server_name] += 1
            self.ping_spike_logger.log_ping_spike(server_name, result)

        # Calculate statistics
        statistics = self._calculate_statistics(server_name, result["timestamp"])

        # Update GUI display
        if self.main_window:
            self.main_window.update_display(server_name, formatted_result, statistics)

        # Update system tray icon based on first server status
        if server_name == self.first_server:
            self.system_tray.update_health_status(statistics["overall_status"])

    def _calculate_statistics(self, server_name, now_timestamp):
        """Calculate statistics for a server"""
        elapsed_minutes = self._calculate_elapsed_minutes(server_name, now_timestamp)
        overall_status = self._calculate_overall_status(server_name, now_timestamp)

        if not self.ping_times[server_name]:
            return {
                "avg": 0,
                "best": 0,
                "worst": 0,
                "ping_spikes": 0,
                "overall_status": overall_status,
                "pinged_count": self.pinged_counts[server_name],
                "elapsed_minutes": elapsed_minutes,
            }

        ping_times = list(self.ping_times[server_name])
        avg_ping = sum(ping_times) / len(ping_times)
        best_ping = min(ping_times)
        worst_ping = max(ping_times)

        return {
            "avg": avg_ping,
            "best": best_ping,
            "worst": worst_ping,
            "ping_spikes": self.ping_spike_counts[server_name],
            "overall_status": overall_status,
            "pinged_count": self.pinged_counts[server_name],
            "elapsed_minutes": elapsed_minutes,
        }

    def _calculate_overall_status(self, server_name, now_timestamp):
        """Calculate Healthy/Degraded/Failing for the last 5 minutes of data."""
        ping_history = self.ping_time_history[server_name]
        if not ping_history:
            return "healthy"

        window_start = now_timestamp - timedelta(minutes=5)
        recent_pings = [
            ping_time
            for ping_timestamp, ping_time in ping_history
            if ping_timestamp >= window_start
        ]

        if not recent_pings:
            recent_pings = [ping_time for _, ping_time in ping_history]

        if any(ping_time > self.ping_threshold_degraded for ping_time in recent_pings):
            return "failing"
        if any(ping_time > self.ping_threshold_healthy for ping_time in recent_pings):
            return "degraded"
        return "healthy"

    def _calculate_elapsed_minutes(self, server_name, now_timestamp):
        """Calculate elapsed minutes for display with midpoint rounding behavior."""
        first_timestamp = self.first_ping_timestamps[server_name]
        if first_timestamp is None:
            return 1

        elapsed_seconds = max(0, (now_timestamp - first_timestamp).total_seconds())
        return max(1, int((elapsed_seconds + 30) // 60))

    def reset_server_statistics(self, server_name):
        """Reset monitor-side statistics for one server."""
        if server_name not in self.servers:
            return

        self.ping_times[server_name].clear()
        self.ping_time_history[server_name].clear()
        self.ping_spike_counts[server_name] = 0
        self.pinged_counts[server_name] = 0
        self.first_ping_timestamps[server_name] = None

    def reset_all_statistics(self):
        """Reset monitor-side statistics for all servers."""
        for server_name in self.servers.keys():
            self.reset_server_statistics(server_name)

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
        self.logger.info("Shutting down Ping Monitor")
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
