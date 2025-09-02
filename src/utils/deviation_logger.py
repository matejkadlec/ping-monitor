"""
Deviation logging utilities for tracking high ping events.
"""

import os
from datetime import datetime, timedelta


class DeviationLogger:
    """Handles logging and management of ping deviations"""

    def __init__(self, deviations_file="deviations.txt", retention_hours=24):
        self.deviations_file = deviations_file
        self.retention_hours = retention_hours

    def log_deviation(self, server_name, result):
        """Log a deviation (high ping) to the deviations file"""
        try:
            timestamp = result["timestamp"].strftime("%Y-%m-%d %H:%M:%S")

            if result["status"] == "success":
                ping_time = result["time"]
                log_entry = f"[{timestamp}] {server_name}: {ping_time}ms\n"
            else:
                log_entry = f"[{timestamp}] {server_name}: {result['status']}\n"

            # Append to file
            with open(self.deviations_file, "a", encoding="utf-8") as f:
                f.write(log_entry)

        except Exception as e:
            print(f"Error logging deviation: {e}")

    def cleanup_deviations_file(self):
        """Clean up old entries from the deviations file"""
        try:
            if not os.path.exists(self.deviations_file):
                return

            # Read all lines from the file
            with open(self.deviations_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Filter lines to keep only those within the retention period
            cutoff_time = datetime.now() - timedelta(hours=self.retention_hours)
            filtered_lines = []

            for line in lines:
                try:
                    # Extract timestamp from the line (format: [YYYY-MM-DD HH:MM:SS])
                    if line.startswith("[") and "] " in line:
                        timestamp_str = line[1 : line.index("] ")]
                        line_time = datetime.strptime(
                            timestamp_str, "%Y-%m-%d %H:%M:%S"
                        )

                        # Keep line if it's newer than cutoff time
                        if line_time > cutoff_time:
                            filtered_lines.append(line)
                except (ValueError, IndexError):
                    # If we can't parse the timestamp, keep the line to be safe
                    filtered_lines.append(line)

            # Write filtered lines back to file
            with open(self.deviations_file, "w", encoding="utf-8") as f:
                f.writelines(filtered_lines)

        except Exception as e:
            print(f"Error during deviation file cleanup: {e}")

    def get_recent_deviations_count(self, server_name, hours=24):
        """Get count of recent deviations for a specific server"""
        try:
            if not os.path.exists(self.deviations_file):
                return 0

            count = 0
            cutoff_time = datetime.now() - timedelta(hours=hours)

            with open(self.deviations_file, "r", encoding="utf-8") as f:
                for line in f:
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

        except Exception as e:
            print(f"Error counting recent deviations: {e}")
            return 0
