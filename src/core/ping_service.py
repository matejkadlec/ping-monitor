"""
Ping functionality for monitoring network connectivity.
"""

import os
import subprocess
import re
import threading
import time
import queue
from datetime import datetime
from collections import deque


class PingService:
    """Service for handling ping operations and results"""

    def __init__(
        self, servers, ping_interval=1, ping_threshold=60, max_display_lines=600
    ):
        self.servers = servers
        self.ping_interval = ping_interval
        self.ping_threshold = ping_threshold

        # Data storage - separate deque for each server
        self.ping_results = {}
        self.ping_times = {}  # For tracking raw ping times for statistics
        self.deviation_counts = {}  # For tracking number of deviations

        for server_name in servers.keys():
            self.ping_results[server_name] = deque(maxlen=max_display_lines)
            self.ping_times[server_name] = deque(maxlen=max_display_lines)
            self.deviation_counts[server_name] = 0

        self.ping_queue = queue.Queue()
        self.running = True
        self.ping_thread_started = False

    def reset_stats(self, server_name):
        """Reset statistics for a specific server"""
        if server_name in self.ping_results:
            self.ping_results[server_name].clear()
            self.ping_times[server_name].clear()
            self.deviation_counts[server_name] = 0

    def reset_all_stats(self):
        """Reset statistics for all servers"""
        for server_name in self.servers.keys():
            self.reset_stats(server_name)

    def ping_server(self, server_name, ip_address):
        """Ping a single server and return the result"""
        try:
            # Set up subprocess to hide the console window
            startupinfo = None
            if os.name == "nt":  # Windows
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            # Use Windows ping command with specific options
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "5000", ip_address],
                capture_output=True,
                text=True,
                timeout=10,
                startupinfo=startupinfo,  # Add this to hide command window
            )

            if result.returncode == 0:
                # Parse ping time from output
                match = re.search(r"time[<=](\d+)ms", result.stdout)
                if match:
                    ping_time = int(match.group(1))
                    return {
                        "status": "success",
                        "time": ping_time,
                        "server": server_name,
                    }
                else:
                    # Couldn't parse time, but ping succeeded
                    return {"status": "success", "time": 0, "server": server_name}
            else:
                # Ping failed
                return {"status": "timeout", "time": None, "server": server_name}

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "time": None, "server": server_name}
        except Exception as e:
            return {
                "status": "error",
                "time": None,
                "server": server_name,
                "error": str(e),
            }

    def ping_all_servers(self):
        """Ping all servers concurrently"""

        def ping_worker(server_name, ip_address):
            result = self.ping_server(server_name, ip_address)
            result["timestamp"] = datetime.now()
            self.ping_queue.put(result)

        # Create and start threads for each server
        threads = []
        for server_name, ip_address in self.servers.items():
            thread = threading.Thread(
                target=ping_worker, args=(server_name, ip_address)
            )
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete (with timeout)
        for thread in threads:
            thread.join(timeout=15)  # 15 second timeout per thread

    def format_ping_result(self, server_name, result):
        """Format ping result for display"""
        timestamp = result["timestamp"].strftime("%H:%M:%S")

        if result["status"] == "success":
            ping_time = result["time"]
            return {
                "text": f"[{timestamp}] {server_name}: {ping_time}ms",
                "tag": self._get_ping_tag(ping_time),
                "ping_time": ping_time,
            }
        elif result["status"] == "timeout":
            return {
                "text": f"[{timestamp}] {server_name}: Request timeout",
                "tag": "bad_ping",
                "ping_time": None,
            }
        else:  # error
            error_msg = result.get("error", "Unknown error")
            return {
                "text": f"[{timestamp}] {server_name}: Error - {error_msg}",
                "tag": "bad_ping",
                "ping_time": None,
            }

    def _get_ping_tag(self, ping_time):
        """Get the appropriate tag for ping time coloring"""
        if ping_time < 40:
            return "excellent_ping"  # Green
        elif ping_time <= 60:
            return "good_ping"  # Yellow
        else:
            return "bad_ping"  # Red

    def is_deviation(self, result):
        """Check if the ping result is considered a deviation (high ping)"""
        return (
            result["status"] == "success"
            and result["time"] is not None
            and result["time"] > self.ping_threshold
        )

    def perform_warmup_pings(self):
        """Perform warm-up pings to establish network connections"""
        print("Performing warm-up pings...")
        try:
            # Ping each server once without recording results
            for server_name, ip_address in self.servers.items():
                # Just ping once and ignore the result
                _ = self.ping_server(server_name, ip_address)

            # Add a small delay to let the network settle
            time.sleep(1)
            print("Warm-up pings completed")
        except Exception as e:
            print(f"Error during warm-up pings: {e}")
            # Continue with the application even if warm-up fails
            pass

    def ping_worker_thread(self):
        """Main ping worker thread that continuously pings servers"""
        try:
            last_ping_time = 0

            while self.running:
                current_time = time.time()

                # Check if it's time for the next ping
                if current_time - last_ping_time >= self.ping_interval:
                    self.ping_all_servers()
                    last_ping_time = current_time

                # Small sleep to prevent excessive CPU usage
                time.sleep(0.1)

        except Exception as e:
            print(f"Ping worker thread error: {e}")

    def start_ping_thread(self):
        """Start the ping monitoring thread"""
        if self.ping_thread_started:
            return

        self.ping_thread_started = True
        ping_thread = threading.Thread(target=self.ping_worker_thread, daemon=True)
        ping_thread.start()

    def stop(self):
        """Stop the ping service"""
        self.running = False
