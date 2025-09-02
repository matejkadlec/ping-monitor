"""
Statistics utilities for ping monitoring.
"""

from collections import deque
from datetime import datetime, timedelta


class PingStatistics:
    """Handles calculation and tracking of ping statistics"""

    def __init__(self, max_samples=600):
        self.max_samples = max_samples
        self.ping_times = {}
        self.deviation_counts = {}
        self.last_reset = datetime.now()

    def initialize_server(self, server_name):
        """Initialize statistics tracking for a server"""
        if server_name not in self.ping_times:
            self.ping_times[server_name] = deque(maxlen=self.max_samples)
            self.deviation_counts[server_name] = 0

    def add_ping_time(self, server_name, ping_time, is_deviation=False):
        """Add a ping time sample for a server"""
        self.initialize_server(server_name)

        if ping_time is not None:
            self.ping_times[server_name].append(ping_time)

        if is_deviation:
            self.deviation_counts[server_name] += 1

    def get_average_ping(self, server_name):
        """Get average ping time for a server"""
        if server_name not in self.ping_times or not self.ping_times[server_name]:
            return 0.0

        ping_times = list(self.ping_times[server_name])
        return sum(ping_times) / len(ping_times)

    def get_deviation_count(self, server_name):
        """Get deviation count for a server"""
        return self.deviation_counts.get(server_name, 0)

    def get_statistics(self, server_name):
        """Get comprehensive statistics for a server"""
        self.initialize_server(server_name)

        return {
            "avg": self.get_average_ping(server_name),
            "deviations": self.get_deviation_count(server_name),
            "sample_count": len(self.ping_times[server_name]),
        }

    def reset_daily_stats(self):
        """Reset daily statistics if needed"""
        now = datetime.now()
        if now.date() > self.last_reset.date():
            for server_name in self.deviation_counts:
                self.deviation_counts[server_name] = 0
            self.last_reset = now
