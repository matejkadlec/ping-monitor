"""
Ping spike logging utilities for tracking high ping events.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path


LOGGER = logging.getLogger(__name__)


class PingSpikeLogger:
    """Handles logging and management of ping spikes."""

    def __init__(self, ping_spikes_file="ping_spikes.log", retention_hours=24):
        self.ping_spikes_file = self._resolve_path(ping_spikes_file)
        self.retention_hours = retention_hours
        os.makedirs(os.path.dirname(self.ping_spikes_file), exist_ok=True)
        self._migrate_legacy_files()
        self.cleanup_ping_spikes_file()

    def _project_root(self):
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _resolve_path(self, ping_spikes_file):
        target_path = Path(ping_spikes_file)
        if target_path.is_absolute():
            return str(target_path)
        return str((self._project_root() / target_path).resolve())

    def _migrate_legacy_files(self):
        """Move legacy log files to the current target log filename."""
        try:
            target_name = os.path.basename(self.ping_spikes_file).lower()
            if target_name != "ping_spikes.log":
                return

            project_root = str(self._project_root())
            log_dir = os.path.dirname(self.ping_spikes_file)

            legacy_candidates = ["ping_spikes.txt", "deviations.txt"]
            target_path = self.ping_spikes_file

            source_candidates = []
            for legacy_name in legacy_candidates:
                source_candidates.append(os.path.join(log_dir, legacy_name))
                source_candidates.append(os.path.join(project_root, legacy_name))

            source_candidates.append(os.path.join(project_root, "ping_spikes.log"))

            if not os.path.exists(target_path):
                for legacy_path in source_candidates:
                    if os.path.exists(legacy_path):
                        os.replace(legacy_path, target_path)
                        LOGGER.info(
                            "Migrated ping log file from %s to %s",
                            legacy_path,
                            target_path,
                        )
                        break
            else:
                for legacy_path in source_candidates:
                    if os.path.exists(legacy_path) and legacy_path != target_path:
                        legacy_content = self._read_text_file(legacy_path).strip()
                        if legacy_content:
                            with open(
                                target_path, "a", encoding="utf-8"
                            ) as target_handle:
                                target_handle.write("\n" + legacy_content + "\n")
                        os.remove(legacy_path)
                        LOGGER.info(
                            "Merged legacy ping log from %s into %s",
                            legacy_path,
                            target_path,
                        )
        except Exception as error:
            LOGGER.exception("Error migrating legacy ping logs: %s", error)

    def log_ping_spike(self, server_name, result):
        """Log a ping spike (high ping) to the ping spikes file."""
        try:
            timestamp = result["timestamp"].strftime("%Y-%m-%d %H:%M:%S")

            if result["status"] == "success":
                ping_time = result["time"]
                log_entry = f"[{timestamp}] {server_name}: {ping_time}ms\n"
            else:
                log_entry = f"[{timestamp}] {server_name}: {result['status']}\n"

            with open(self.ping_spikes_file, "a", encoding="utf-8") as file_handle:
                file_handle.write(log_entry)

        except Exception as error:
            LOGGER.exception("Error logging ping spike: %s", error)

    def cleanup_ping_spikes_file(self):
        """Clean up old entries from the ping spikes file."""
        try:
            if not os.path.exists(self.ping_spikes_file):
                return

            content = self._read_text_file(self.ping_spikes_file)
            lines = content.splitlines(keepends=True)

            cutoff_time = datetime.now() - timedelta(hours=self.retention_hours)
            filtered_lines = []

            for line in lines:
                try:
                    if line.startswith("[") and "] " in line:
                        timestamp_str = line[1 : line.index("] ")]
                        line_time = datetime.strptime(
                            timestamp_str, "%Y-%m-%d %H:%M:%S"
                        )

                        if line_time > cutoff_time:
                            filtered_lines.append(line)
                except (ValueError, IndexError):
                    filtered_lines.append(line)

            with open(self.ping_spikes_file, "w", encoding="utf-8") as file_handle:
                file_handle.writelines(filtered_lines)

        except Exception as error:
            LOGGER.exception("Error during ping spike file cleanup: %s", error)

    def get_recent_ping_spikes_count(self, server_name, hours=24):
        """Get count of recent ping spikes for a specific server."""
        try:
            if not os.path.exists(self.ping_spikes_file):
                return 0

            count = 0
            cutoff_time = datetime.now() - timedelta(hours=hours)

            content = self._read_text_file(self.ping_spikes_file)
            for line in content.splitlines():
                try:
                    if server_name in line and line.startswith("["):
                        timestamp_str = line[1 : line.index("] ")]
                        line_time = datetime.strptime(
                            timestamp_str, "%Y-%m-%d %H:%M:%S"
                        )

                        if line_time > cutoff_time:
                            count += 1
                except (ValueError, IndexError):
                    continue

            return count

        except Exception as error:
            LOGGER.exception("Error counting recent ping spikes: %s", error)
            return 0

    def _read_text_file(self, file_path):
        """Read text with encoding fallbacks for legacy Windows/BOM log files."""
        encodings = ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "cp1250", "cp1252")
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as file_handle:
                    return file_handle.read()
            except UnicodeDecodeError:
                continue

        with open(file_path, "r", encoding="utf-8", errors="replace") as file_handle:
            return file_handle.read()
