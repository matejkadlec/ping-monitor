#!/usr/bin/env python3
"""
Windows System Tray Ping Monitor
Monitors ping to multiple servers and displays results in GUI and system tray
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, font
import threading
import time
import subprocess
import re
import os
import psutil
import atexit
from datetime import datetime, timedelta
from collections import deque
import pystray
from PIL import Image, ImageDraw, ImageTk
import queue

# Define lock file path globally for use in cleanup functions
LOCK_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ping_monitor.lock"
)

# Flag to determine if this is the main running instance (to prevent lock file deletion on aborted starts)
IS_MAIN_INSTANCE = False


def cleanup_lock_file():
    """Delete the lock file if it exists, but only if this is the main running instance"""
    try:
        if IS_MAIN_INSTANCE and os.path.exists(LOCK_FILE_PATH):
            os.remove(LOCK_FILE_PATH)
            print("Lock file removed during cleanup")
    except Exception as e:
        print(f"Error removing lock file: {e}")


# Register the cleanup function to run at exit
atexit.register(cleanup_lock_file)


def is_already_running():
    """Check if another instance of this application is already running using a lock file"""
    try:
        # Try to create or check the lock file
        if os.path.exists(LOCK_FILE_PATH):
            # Check if the process with the stored PID is still running
            with open(LOCK_FILE_PATH, "r") as f:
                try:
                    pid = int(f.read().strip())
                    # Try to check if process exists without actually sending a signal
                    if psutil.pid_exists(pid):
                        # Process exists, check if it's a Python process (more reliable)
                        try:
                            process = psutil.Process(pid)
                            if "python" in process.name().lower():
                                return True
                        except psutil.NoSuchProcess:
                            pass  # Process doesn't exist anymore
                except (ValueError, psutil.Error):
                    # Invalid PID or process not found, we can reuse the lock file
                    pass

        # If we get here, either the lock file doesn't exist or the process is no longer running
        # Create/update the lock file with our PID
        with open(LOCK_FILE_PATH, "w") as f:
            f.write(str(os.getpid()))

        # Flag this as the main instance
        global IS_MAIN_INSTANCE
        IS_MAIN_INSTANCE = True

        return False
    except Exception as e:
        print(f"Warning: Lock file check failed: {e}")
        # If the lock check fails, assume we can run (better than preventing startup)
        return False


class PingMonitor:
    def __init__(self):
        # Colors
        self.bg_color = "#111111"
        self.accent_color = "#ffb400"
        self.text_color = "#ffffff"
        self.log_bg_color = "#1e1e1e"
        self.highlight_color = "#333333"
        self.new_entry_highlight = "#3a3a3a"

        # Animation settings
        self.animation_enabled = True
        self.animation_duration = 800  # milliseconds
        self.animation_steps = 8

        # Server configuration
        self.servers = {
            "cloudflare.com": "1.1.1.1",
            "google.com": "8.8.8.8",
            "seznam.cz": "77.75.77.222",
            "matejkadlec.cz": "37.9.175.163",
        }

        # First server monitoring for tray icon color
        self.first_server = list(self.servers.keys())[0]  # Should be cloudflare.com
        self.first_server_ping_history = deque(
            maxlen=10
        )  # Store last 10 pings (or less based on ping_interval)
        self.first_ping_received = False  # Track if we've received first ping

        # Configuration
        self.ping_threshold = 60  # ms (for deviation logging)
        self.ping_interval = 1  # seconds between pings
        self.preserved_minutes = 10  # minutes to preserve and display per tab
        self.max_display_lines_per_server = int(
            self.preserved_minutes * (60 / self.ping_interval)
        )  # Convert to integer for deque maxlen

        # Data storage - separate deque for each server
        self.ping_results = {}
        self.ping_times = {}  # For tracking raw ping times for statistics
        self.deviation_counts = {}  # For tracking number of deviations (>60ms)
        for server_name in self.servers.keys():
            self.ping_results[server_name] = deque(
                maxlen=self.max_display_lines_per_server
            )
            # Track ping times for calculating average
            self.ping_times[server_name] = deque(
                maxlen=self.max_display_lines_per_server
            )
            # Initialize deviation counter
            self.deviation_counts[server_name] = 0

        self.deviations_file = "deviations.txt"

        # Threading
        self.ping_queue = queue.Queue()
        self.running = True

        # GUI elements
        self.root = None
        self.notebook = None  # Tabbed interface
        self.text_widgets = {}  # One text widget per server tab
        self.status_labels = {}  # One status label per server tab
        self.window_visible = False

        # System tray
        self.tray_icon = None
        self.current_status = "neutral"  # 'green', 'red', or 'neutral'
        self.icon_images = {
            "green": None,
            "red": None,
            "neutral": None,
        }  # Cache for icon images

        # Initialize
        self.setup_gui()
        self.setup_tray()
        # Add warm-up ping before starting the regular ping thread
        self.perform_warmup_pings()
        self.start_ping_thread()

    def setup_gui(self):
        """Setup the main GUI window with tabbed interface"""
        self.root = tk.Tk()
        self.root.title("Ping Monitor")
        self.root.geometry("1000x700")
        self.root.configure(bg=self.bg_color)

        # Set application icon with absolute path - improved implementation for taskbar icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            try:
                # This should work for the taskbar icon
                self.root.iconbitmap(default=icon_path)

                # For some Windows versions, we might need to use a different approach as well
                try:
                    # Try setting the icon again using the Windows API
                    import ctypes

                    myappid = f"matka.pingmonitor.1.1.0"  # Arbitrary string for Windows
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                        myappid
                    )
                except Exception as e:
                    print(f"Non-critical error setting app ID: {e}")
            except tk.TclError as e:
                print(f"Error setting window icon: {e}")

        # Configure window to start minimized
        self.root.withdraw()  # Hide window initially

        # Configure window close button to minimize instead of exit
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Configure custom fonts
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
        self.root.option_add("*Font", default_font)

        # Main frame with padding
        main_frame = tk.Frame(self.root, bg=self.bg_color, padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header frame with gold accent bar
        header_frame = tk.Frame(main_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, pady=(0, 15))

        # Gold accent bar at top
        accent_bar = tk.Frame(header_frame, bg=self.accent_color, height=4)
        accent_bar.pack(fill=tk.X, pady=(0, 10))

        # Title label with modern font
        title_label = tk.Label(
            header_frame,
            text="Ping Monitor",
            font=("Segoe UI", 18, "bold"),
            bg=self.bg_color,
            fg=self.accent_color,
        )
        title_label.pack(anchor="w")

        # Subtitle
        subtitle_label = tk.Label(
            header_frame,
            text="Real-time network connection monitoring",
            font=("Segoe UI", 10),
            bg=self.bg_color,
            fg=self.text_color,
        )
        subtitle_label.pack(anchor="w")

        # Create notebook (tabbed interface) with custom style
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Configure ttk styles for modern dark theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=self.bg_color, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#232323",
            foreground=self.text_color,
            padding=[10, 5],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.bg_color)],
            foreground=[("selected", self.accent_color)],
        )
        style.configure("TFrame", background=self.bg_color)

        # Create tab for each server
        for server_name in self.servers.keys():
            self.create_server_tab(server_name)

        # Footer with status info
        footer_frame = tk.Frame(main_frame, bg=self.bg_color, height=30)
        footer_frame.pack(fill=tk.X, pady=(15, 0))

        # Version info
        version_label = tk.Label(
            footer_frame,
            text="v1.1.0",
            font=("Segoe UI", 8),
            bg=self.bg_color,
            fg="#555555",
        )
        version_label.pack(side=tk.RIGHT)

        # Start GUI update thread
        self.start_gui_update_thread()

    def create_server_tab(self, server_name):
        """Create a tab for a specific server"""
        # Create frame for this server's tab
        tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(tab_frame, text=f"{server_name}")

        # Server info frame with accent color - add more left padding
        info_frame = tk.Frame(tab_frame, bg=self.bg_color, pady=10)
        info_frame.pack(fill=tk.X, padx=(15, 5))  # Added left padding

        # Server info label
        ip_address = self.servers[server_name]
        info_label = tk.Label(
            info_frame,
            text=f"{server_name} ({ip_address})",
            font=("Segoe UI", 12, "bold"),
            bg=self.bg_color,
            fg=self.accent_color,
            padx=5,  # Added padding within the label itself
        )
        info_label.pack(side=tk.LEFT)

        # Text widget with modern styling
        frame = tk.Frame(tab_frame, bg="#181818", padx=2, pady=2)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        text_widget = scrolledtext.ScrolledText(
            frame,
            font=("Consolas", 10),
            bg=self.log_bg_color,
            fg=self.text_color,
            insertbackground=self.text_color,
            selectbackground="#333333",
            wrap=tk.WORD,
            state=tk.DISABLED,
            borderwidth=0,
        )
        text_widget.pack(fill=tk.BOTH, expand=True)

        # Configure text tags for color coding
        text_widget.tag_configure(
            "excellent_ping", foreground="#00ff00"
        )  # Green < 40ms
        text_widget.tag_configure("good_ping", foreground="#ffff00")  # Yellow 40-60ms
        text_widget.tag_configure("bad_ping", foreground="#ff0000")  # Red > 60ms

        # Status bar for this server
        status_frame = tk.Frame(tab_frame, bg=self.bg_color, height=30)
        status_frame.pack(fill=tk.X, pady=10, padx=5)

        status_label = tk.Label(
            status_frame,
            text=f"Initializing...",
            bg=self.bg_color,
            fg=self.text_color,
            font=("Segoe UI", 9),
        )
        status_label.pack(side=tk.LEFT)

        # Store references
        self.text_widgets[server_name] = text_widget
        self.status_labels[server_name] = status_label

    def setup_tray(self):
        """Setup system tray icon"""
        # Try to use icon.ico if available, otherwise create icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

        # Store the icon path for later use
        self.icon_path = icon_path if os.path.exists(icon_path) else None

        # Pre-load all icon states to avoid issues when switching
        if self.icon_path:
            try:
                # Load and cache all icon states
                self.load_icon_states()
            except Exception as e:
                print(f"Error loading icon states: {e}")
                # Fallback to generated icons
                self.create_fallback_icons()
        else:
            print(f"Icon file not found at: {icon_path}")
            # Use generated icon
            self.create_fallback_icons()

        # Set initial icon image to neutral
        self.icon_image = self.icon_images["neutral"]

        # Create tray icon with dynamic menu
        self.tray_icon = pystray.Icon(
            "PingMonitor", self.icon_image, "Ping Monitor", self.create_menu()
        )

    def create_menu(self):
        """Create a dynamic menu based on current window state"""
        # Using a lambda for the dynamic menu to evaluate window state each time menu is shown
        return pystray.Menu(
            lambda: [
                # Show option - enabled only when window is hidden
                pystray.MenuItem(
                    "Show",
                    self.show_window,
                    enabled=not self.window_visible,
                    default=not self.window_visible,  # Make this the default/bold action when window is hidden
                ),
                # Hide option - enabled only when window is visible
                pystray.MenuItem(
                    "Hide",
                    self.hide_window,
                    enabled=self.window_visible,
                    default=self.window_visible,  # Make this the default/bold action when window is shown
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self.quit_application),
            ]
        )

    def load_icon_states(self):
        """Load and cache all icon states"""
        if not self.icon_path:
            return

        try:
            # Base icon for modification
            base_icon = Image.open(self.icon_path).copy()
            if base_icon.width != 16 or base_icon.height != 16:
                try:
                    base_icon.seek(0)
                except EOFError:
                    base_icon = base_icon.resize((16, 16))

            # Create neutral (dark gray) icon
            neutral_icon = Image.new("RGBA", (16, 16), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(neutral_icon)
            draw.ellipse([2, 2, 14, 14], fill="#333333")  # Dark gray
            self.icon_images["neutral"] = neutral_icon

            # For green status
            green_icon = Image.new("RGBA", (16, 16), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(green_icon)
            draw.ellipse([2, 2, 14, 14], fill="green")
            self.icon_images["green"] = green_icon

            # For red status
            red_icon = Image.new("RGBA", (16, 16), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(red_icon)
            draw.ellipse([2, 2, 14, 14], fill="red")
            self.icon_images["red"] = red_icon

        except Exception as e:
            print(f"Error in load_icon_states: {e}")
            raise  # Re-raise to trigger fallback

    def create_fallback_icons(self):
        """Create simple colored circle icons as fallbacks"""
        # Create neutral status icon (dark gray)
        neutral_img = Image.new("RGBA", (16, 16), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(neutral_img)
        draw.ellipse([2, 2, 14, 14], fill="#333333")  # Dark gray
        self.icon_images["neutral"] = neutral_img

        # Create green status icon
        green_img = Image.new("RGBA", (16, 16), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(green_img)
        draw.ellipse([2, 2, 14, 14], fill="green")
        self.icon_images["green"] = green_img

        # Create red status icon
        red_img = Image.new("RGBA", (16, 16), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(red_img)
        draw.ellipse([2, 2, 14, 14], fill="red")
        self.icon_images["red"] = red_img

    def update_tray_icon_status(self, server_results):
        """Update tray icon based on first server's ping history"""
        # Only consider the first server (Cloudflare)
        if self.first_server not in server_results:
            return

        # Get ping status of first server
        result = server_results.get(self.first_server, {})
        ping_time = result.get("ping_time")

        # Special case for first ping - immediately set icon color
        if not self.first_ping_received:
            if ping_time is None or ping_time > 60:  # Red ping (>60ms or timeout)
                new_status = "red"
            else:  # Green or yellow ping (<=60ms)
                new_status = "green"

            self.current_status = new_status
            self.icon_image = self.icon_images[new_status]
            self.first_ping_received = True

            # Update the tray icon immediately
            if self.tray_icon and hasattr(self.tray_icon, "icon"):
                try:
                    self.tray_icon.icon = self.icon_image
                except Exception as e:
                    print(f"Failed to update tray icon: {e}")
            return

        # For subsequent pings, add to history
        if ping_time is None:  # Timeout
            # Timeouts are considered "bad"
            current_ping_type = "bad"
        elif ping_time < 40:
            current_ping_type = "green"
        elif ping_time <= 60:
            # Yellow pings can be either "yellow_as_green" or "yellow_as_red"
            # depending on which rule we're checking
            current_ping_type = "yellow"
        else:
            current_ping_type = "bad"

        # Add to history
        self.first_server_ping_history.append(current_ping_type)

        # Check if we have enough history (10 seconds worth of pings)
        required_samples = min(10, 10 // self.ping_interval)

        if len(self.first_server_ping_history) >= required_samples:
            # Get the last X pings (where X = required_samples)
            recent_pings = list(self.first_server_ping_history)[-required_samples:]

            # RULE 1.3: If server has 10 seconds IN A ROW ping yellow or red, icon turns red
            # Yellow counts as red here, so we check if ALL pings are either yellow or bad
            all_yellow_or_red = all(ping in ["yellow", "bad"] for ping in recent_pings)

            # RULE 1.4: If server has 10 seconds ping yellow or green, icon turns green
            # Yellow counts as green here, so we check if ALL pings are either yellow or green
            all_yellow_or_green = all(
                ping in ["yellow", "green"] for ping in recent_pings
            )

            # Determine new icon state
            if all_yellow_or_red:
                new_status = "red"
            elif all_yellow_or_green:
                new_status = "green"
            else:
                # Keep current status if neither condition is fully met
                new_status = self.current_status

            # Only update if the status is actually changing (RULE 1.5)
            if new_status != self.current_status:
                self.current_status = new_status
                self.icon_image = self.icon_images[new_status]

                # Update the tray icon
                if self.tray_icon and hasattr(self.tray_icon, "icon"):
                    try:
                        self.tray_icon.icon = self.icon_image
                    except Exception as e:
                        print(f"Failed to update tray icon: {e}")

    def hide_window(self, icon=None, item=None):
        """Hide the main window"""
        if self.root and self.window_visible:
            self.root.withdraw()
            self.window_visible = False

            # Force update of the tray menu to reflect the new window state
            self.refresh_tray_menu()

    def refresh_tray_menu(self):
        """Force refresh of the tray icon menu to update enabled/disabled states"""
        if self.tray_icon and hasattr(self.tray_icon, "update_menu"):
            try:
                self.tray_icon.update_menu()
            except Exception as e:
                print(f"Failed to update tray menu: {e}")

    def show_window(self, icon=None, item=None):
        """Show the main window"""
        if self.root and not self.window_visible:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.window_visible = True

            # Force update of the tray menu to reflect the new window state
            self.refresh_tray_menu()

            # Force full refresh of all tabs
            for server_name in self.servers.keys():
                self.initial_populate_tab(server_name)

    def quit_application(self, icon=None, item=None):
        """Quit the application"""
        self.running = False

        # Clean up the lock file
        cleanup_lock_file()

        try:
            # Stop the tray icon properly - this must happen first
            if self.tray_icon:
                # Schedule the tray icon to stop in a moment
                # This allows the current callback to complete cleanly
                if hasattr(self.tray_icon, "stop"):
                    threading.Thread(target=self.tray_icon.stop, daemon=True).start()

            # Exit Tkinter mainloop if running
            if self.root:
                self.root.after(100, self.root.destroy)  # Schedule destruction

        except Exception as e:
            print(f"Error during application shutdown: {e}")
            # As a last resort, force exit
            os._exit(0)

    def ping_server(self, server_name, ip_address):
        """Ping a single server and return result"""
        try:
            # Set up subprocess to hide the console window
            startupinfo = None
            if os.name == "nt":  # Windows
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            # Use Windows ping command
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "3000", ip_address],
                capture_output=True,
                text=True,
                timeout=5,
                startupinfo=startupinfo,  # Add this to hide command window
            )

            if result.returncode == 0:
                # Parse ping time from output
                output = result.stdout
                # Look for "time=XXXms" or "time<1ms"
                time_match = re.search(r"time[<=](\d+(?:\.\d+)?)ms", output)
                if time_match:
                    ping_time = float(time_match.group(1))
                else:
                    # Look for "time<1ms" case
                    if "time<1ms" in output:
                        ping_time = 0.5
                    else:
                        ping_time = None

                return ping_time
            else:
                return None

        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return None

    def ping_all_servers(self):
        """Ping all servers and return results"""
        results = {}
        threads = []

        def ping_worker(server_name, ip_address):
            ping_time = self.ping_server(server_name, ip_address)
            results[server_name] = {
                "ip": ip_address,
                "ping_time": ping_time,
                "timestamp": datetime.now(),
            }

        # Start threads for parallel pinging
        for server_name, ip_address in self.servers.items():
            thread = threading.Thread(
                target=ping_worker, args=(server_name, ip_address)
            )
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5)

        return results

    def format_ping_result(self, server_name, result):
        """Format ping result for display with integer ping times"""
        timestamp = result["timestamp"].strftime("%H:%M:%S")
        ip = result["ip"]
        ping_time = result["ping_time"]

        if ping_time is not None:
            # Display ping time as integer
            ping_str = f"{int(ping_time)}ms"

            # New color thresholds: < 40 green, 40-60 yellow, > 60 red
            if ping_time < 40:
                status = "excellent"
            elif ping_time <= 60:
                status = "good"
            else:
                status = "bad"
        else:
            ping_str = "TIMEOUT"
            status = "bad"

        formatted = f"[{timestamp}] {server_name} ({ip}): {ping_str}"
        return formatted, status

    def log_deviation(self, server_name, result):
        """Log ping deviation to file"""
        ping_time = result["ping_time"]
        if ping_time is None or ping_time >= self.ping_threshold:
            timestamp = result["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            ip = result["ip"]
            # Display ping time as integer
            ping_str = f"{int(ping_time)}ms" if ping_time is not None else "TIMEOUT"

            log_line = f"{timestamp} - {server_name} ({ip}): {ping_str}\n"

            try:
                # Create directory for the file if it doesn't exist
                deviations_dir = os.path.dirname(os.path.abspath(self.deviations_file))
                if not os.path.exists(deviations_dir):
                    os.makedirs(deviations_dir)

                # Append to the file (will create it if it doesn't exist)
                with open(self.deviations_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
            except Exception as e:
                print(f"Error writing to deviations file: {e}")

    def cleanup_deviations_file(self):
        """Remove entries older than 24 hours from deviations file"""
        if not os.path.exists(self.deviations_file):
            return

        try:
            cutoff_time = datetime.now() - timedelta(hours=24)

            with open(self.deviations_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            filtered_lines = []
            for line in lines:
                try:
                    # Extract timestamp from line
                    timestamp_str = line[:19]  # First 19 characters should be timestamp
                    line_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    if line_time >= cutoff_time:
                        filtered_lines.append(line)
                except (ValueError, IndexError):
                    # Keep lines that can't be parsed (shouldn't happen, but just in case)
                    filtered_lines.append(line)

            # Write back filtered lines
            with open(self.deviations_file, "w", encoding="utf-8") as f:
                f.writelines(filtered_lines)

        except Exception as e:
            print(f"Error cleaning up deviations file: {e}")

    def ping_worker_thread(self):
        """Main ping worker thread"""
        last_cleanup = datetime.now()

        while self.running:
            try:
                # Ping all servers
                results = self.ping_all_servers()

                # Update tray icon based on first server history
                self.update_tray_icon_status(results)

                # Process results - always add to queue regardless of window visibility
                for server_name, result in results.items():
                    # Get the ping time
                    ping_time = result.get("ping_time")

                    # Format result for display
                    formatted_result, status = self.format_ping_result(
                        server_name, result
                    )

                    # Add to server-specific queue for result storage and GUI update
                    self.ping_queue.put((server_name, formatted_result, status))

                    # Log deviations (keep original threshold of 50ms for deviation logging)
                    self.log_deviation(server_name, result)

                    # Track ping time for average calculation
                    if ping_time is not None:
                        self.ping_times[server_name].append(ping_time)
                        # Track deviation count (pings > 60ms)
                        if ping_time > 60:
                            self.deviation_counts[server_name] += 1

                # Cleanup deviations file every hour
                if datetime.now() - last_cleanup > timedelta(hours=1):
                    self.cleanup_deviations_file()
                    last_cleanup = datetime.now()

                # Wait for next ping cycle
                time.sleep(self.ping_interval)

            except Exception as e:
                print(f"Error in ping worker thread: {e}")
                time.sleep(self.ping_interval)

    def start_ping_thread(self):
        """Start the ping worker thread"""
        ping_thread = threading.Thread(target=self.ping_worker_thread, daemon=True)
        ping_thread.start()

    def gui_update_worker(self):
        """GUI update worker thread for tabbed interface"""
        while self.running:
            try:
                # Always process all queued ping results, even when window is hidden
                while not self.ping_queue.empty():
                    try:
                        server_name, formatted_result, status = (
                            self.ping_queue.get_nowait()
                        )

                        # Always add to server-specific results deque regardless of GUI visibility
                        self.ping_results[server_name].append(
                            (formatted_result, status)
                        )

                        # Only update GUI if window is visible to avoid unnecessary processing
                        if self.window_visible and server_name in self.text_widgets:
                            # When first populating the text widget, use bulk update
                            if (
                                len(self.ping_results[server_name]) <= 2
                            ):  # For initial and second update
                                self.initial_populate_tab(server_name)
                            else:
                                # For subsequent updates, just append the new line
                                self.update_server_tab(server_name)

                    except queue.Empty:
                        break

                # Update status labels only if window is visible
                if self.window_visible:
                    for server_name in self.servers.keys():
                        if server_name in self.status_labels:
                            # Get current time
                            current_time = datetime.now().strftime("%H:%M:%S")

                            # Get total results count
                            total_results = len(self.ping_results[server_name])

                            # Calculate average ping time
                            avg_ping = 0
                            if self.ping_times[server_name]:
                                avg_ping = int(
                                    sum(self.ping_times[server_name])
                                    / len(self.ping_times[server_name])
                                )

                            # Get deviation count
                            deviation_count = self.deviation_counts[server_name]

                            # Build status text with new statistics
                            status_text = (
                                f"{server_name}: Active | "
                                f"Time: {current_time} | "
                                f"Results: {total_results} | "
                                f"Average: {avg_ping}ms | "
                                f"Deviations: {deviation_count}"
                            )

                            try:
                                self.status_labels[server_name].config(text=status_text)
                            except tk.TclError:
                                pass  # Widget might be destroyed

                time.sleep(0.1)  # Update GUI 10 times per second

            except Exception as e:
                print(f"Error in GUI update worker: {e}")
                time.sleep(1)

    def initial_populate_tab(self, server_name):
        """Initial population of a text widget with all existing results"""
        if server_name not in self.text_widgets:
            return

        text_widget = self.text_widgets[server_name]

        try:
            # Enable text widget for updating
            text_widget.config(state=tk.NORMAL)

            # Clear current content
            text_widget.delete(1.0, tk.END)

            # Add all ping results for this server
            results = list(self.ping_results[server_name])
            for i, (formatted_result, status) in enumerate(results):
                if status == "excellent":
                    tag = "excellent_ping"  # Green
                elif status == "good":
                    tag = "good_ping"  # Yellow
                else:
                    tag = "bad_ping"  # Red

                text_widget.insert(tk.END, formatted_result + "\n", tag)

            # Ensure we're at the bottom
            text_widget.yview_moveto(1.0)

            # Disable text widget
            text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass  # Widget might be destroyed

    def update_server_tab(self, server_name):
        """Update the text widget for a specific server tab with animation effects"""
        if server_name not in self.text_widgets:
            return

        text_widget = self.text_widgets[server_name]

        try:
            # Get current results
            results = list(self.ping_results[server_name])
            if not results:
                return

            # Only process the most recent entry (the one that was just added)
            formatted_result, status = results[-1]

            # Check if we need to trim the content when at capacity
            current_line_count = int(text_widget.index("end-1c").split(".")[0])
            if current_line_count >= self.max_display_lines_per_server:
                # Enable text widget for updating
                text_widget.config(state=tk.NORMAL)
                # Remove the first line to make room for the new one
                text_widget.delete("1.0", "2.0")
                # Disable text widget
                text_widget.config(state=tk.DISABLED)

            # Determine the tag for this entry
            if status == "excellent":
                tag = "excellent_ping"  # Green
            elif status == "good":
                tag = "good_ping"  # Yellow
            else:
                tag = "bad_ping"  # Red

            # Create unique tag for highlight effect
            highlight_tag = f"highlight_{time.time()}"

            # Enable text widget for updating
            text_widget.config(state=tk.NORMAL)

            # Add the new entry with its styling
            if self.animation_enabled:
                text_widget.tag_configure(
                    highlight_tag, background=self.new_entry_highlight
                )
                text_widget.insert(
                    tk.END, formatted_result + "\n", (tag, highlight_tag)
                )
                # Schedule highlight fade-out
                self.fade_highlight(text_widget, highlight_tag, self.animation_steps)
            else:
                text_widget.insert(tk.END, formatted_result + "\n", tag)

            # Ensure we stay at the bottom
            text_widget.yview_moveto(1.0)  # Direct bottom positioning

            # Disable text widget
            text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass  # Widget might be destroyed

    def fade_highlight(self, text_widget, tag, steps_left):
        """Fade out the highlight of new entries"""
        if steps_left <= 0 or not self.running:
            try:
                text_widget.tag_delete(tag)  # Remove highlight completely
            except tk.TclError:
                pass  # Widget might be destroyed
            return

        try:
            # Calculate new background color based on remaining steps
            progress = steps_left / self.animation_steps
            r = int(int(self.new_entry_highlight[1:3], 16) * progress)
            g = int(int(self.new_entry_highlight[3:5], 16) * progress)
            b = int(int(self.new_entry_highlight[5:7], 16) * progress)
            new_color = f"#{r:02x}{g:02x}{b:02x}"

            # Update highlight color
            text_widget.tag_configure(tag, background=new_color)

            # Schedule next fade step
            step_time = self.animation_duration // self.animation_steps
            self.root.after(
                step_time, lambda: self.fade_highlight(text_widget, tag, steps_left - 1)
            )
        except tk.TclError:
            pass  # Widget might be destroyed

    def smooth_scroll_to_end(self, text_widget):
        """Smoothly scroll to the end of the text widget"""
        try:
            # Get current view
            first, last = text_widget.yview()

            # If we're already at the bottom, no need to animate
            if last >= 0.99:
                text_widget.see(tk.END)
                return

            # Otherwise smoothly scroll
            self.animate_scroll(text_widget, first, 1.0, self.animation_steps)
        except tk.TclError:
            pass  # Widget might be destroyed

    def animate_scroll(self, text_widget, start_pos, end_pos, steps_left):
        """Animate scrolling from start_pos to end_pos in steps"""
        if steps_left <= 0 or not self.running:
            try:
                text_widget.see(tk.END)  # Ensure we end at the bottom
            except tk.TclError:
                pass
            return

        try:
            # Calculate intermediate position
            progress = (self.animation_steps - steps_left) / self.animation_steps
            pos = start_pos + ((end_pos - start_pos) * progress)
            text_widget.yview_moveto(pos)

            # Schedule next animation step
            step_time = 20  # milliseconds between steps (smoother)
            self.root.after(
                step_time,
                lambda: self.animate_scroll(
                    text_widget, start_pos, end_pos, steps_left - 1
                ),
            )
        except tk.TclError:
            pass  # Widget might be destroyed

    def start_gui_update_thread(self):
        """Start the GUI update thread"""
        gui_thread = threading.Thread(target=self.gui_update_worker, daemon=True)
        gui_thread.start()

    def run(self):
        """Run the application"""
        try:
            # Start tray icon in a separate thread
            tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            tray_thread.start()

            # Start tkinter main loop
            self.root.mainloop()

            # After mainloop exits, ensure clean shutdown
            print("Tkinter mainloop exited, performing final cleanup")

        except KeyboardInterrupt:
            self.quit_application()
        except Exception as e:
            print(f"Error running application: {e}")
            self.quit_application()

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


def main():
    """Main entry point"""
    try:
        # Check if an instance is already running
        if is_already_running():
            print("Another instance of Ping Monitor is already running.")
            return

        app = PingMonitor()
        app.run()
    except Exception as e:
        print(f"Failed to start Ping Monitor: {e}")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
