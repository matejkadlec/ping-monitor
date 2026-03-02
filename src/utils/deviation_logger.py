"""Backward-compatible aliases for ping spike logging utilities."""

from src.core.config import PING_SPIKES_FILE
from src.utils.ping_spike_logger import PingSpikeLogger


class DeviationLogger(PingSpikeLogger):
    """Backward-compatible class alias for historical imports."""

    def __init__(self, deviations_file=PING_SPIKES_FILE, retention_hours=24):
        super().__init__(
            ping_spikes_file=deviations_file, retention_hours=retention_hours
        )

    def log_deviation(self, server_name, result):
        self.log_ping_spike(server_name, result)

    def cleanup_deviations_file(self):
        self.cleanup_ping_spikes_file()

    def get_recent_deviations_count(self, server_name, hours=24):
        return self.get_recent_ping_spikes_count(server_name, hours)
