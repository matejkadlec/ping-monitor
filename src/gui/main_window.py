"""
Main GUI window for the Ping Monitor application.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, font
import os
import threading
from src.core.config import THEME, VERSION


class MainWindow:
    """Main application window with tabbed interface"""

    def __init__(self, servers, app_instance):
        self.servers = servers
        self.app = app_instance
        self.theme = THEME

        # GUI elements
        self.root = None
        self.notebook = None  # Tabbed interface
        self.text_widgets = {}  # One text widget per server tab
        self.status_labels = {}  # One status label per server tab
        self.window_visible = False

        # Animation settings
        self.animation_enabled = True
        self.animation_duration = 800  # milliseconds
        self.animation_steps = 8

        self._setup_gui()

    def _setup_gui(self):
        """Setup the main GUI window with tabbed interface"""
        self.root = tk.Tk()
        self.root.title("Ping Monitor")
        self.root.geometry("1000x700")
        self.root.configure(bg=self.theme["bg_color"])

        # Set application icon with absolute path
        icon_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            "assets",
            "icon.ico",
        )
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
                self._set_windows_app_id()
            except tk.TclError as e:
                print(f"Error setting window icon: {e}")

        # Configure window to start minimized
        self.root.withdraw()  # Hide window initially

        # Configure window close button to minimize instead of exit
        self.root.protocol("WM_DELETE_WINDOW", self.app.hide_window)

        # Configure custom fonts
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
        self.root.option_add("*Font", default_font)

        self._create_main_layout()
        self._create_server_tabs()
        self._start_gui_update_thread()

    def _set_windows_app_id(self):
        """Set Windows app ID for better taskbar integration"""
        try:
            import ctypes

            myappid = f"matka.pingmonitor.1.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            print(f"Non-critical error setting app ID: {e}")

    def _create_main_layout(self):
        """Create the main layout with header, content, and footer"""
        # Main frame with padding
        main_frame = tk.Frame(self.root, bg=self.theme["bg_color"], padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header frame with gold accent bar
        self._create_header(main_frame)

        # Create notebook (tabbed interface)
        self._create_notebook(main_frame)

        # Footer with status info
        self._create_footer(main_frame)

    def _create_header(self, parent):
        """Create the header section with title and accent bar"""
        header_frame = tk.Frame(parent, bg=self.theme["bg_color"])
        header_frame.pack(fill=tk.X, pady=(0, 15))

        # Gold accent bar at top
        accent_bar = tk.Frame(header_frame, bg=self.theme["accent_color"], height=4)
        accent_bar.pack(fill=tk.X, pady=(0, 10))

        # Title label with modern font
        title_label = tk.Label(
            header_frame,
            text="Ping Monitor",
            font=("Segoe UI", 18, "bold"),
            bg=self.theme["bg_color"],
            fg=self.theme["accent_color"],
        )
        title_label.pack(anchor="w")

        # Subtitle
        subtitle_label = tk.Label(
            header_frame,
            text="Real-time network connection monitoring",
            font=("Segoe UI", 10),
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
        )
        subtitle_label.pack(anchor="w")

    def _create_notebook(self, parent):
        """Create the tabbed notebook interface"""
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Configure ttk styles for modern dark theme
        self._configure_notebook_style()

    def _configure_notebook_style(self):
        """Configure the notebook styling"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=self.theme["bg_color"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#232323",
            foreground=self.theme["text_color"],
            padding=[10, 5],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.theme["bg_color"])],
            foreground=[("selected", self.theme["accent_color"])],
        )
        style.configure("TFrame", background=self.theme["bg_color"])

    def _create_footer(self, parent):
        """Create the footer with version info"""
        footer_frame = tk.Frame(parent, bg=self.theme["bg_color"], height=30)
        footer_frame.pack(fill=tk.X, pady=(15, 0))

        version_label = tk.Label(
            footer_frame,
            text=VERSION,
            font=("Segoe UI", 8),
            bg=self.theme["bg_color"],
            fg="#555555",
        )
        version_label.pack(side=tk.RIGHT)

    def _create_server_tabs(self):
        """Create a tab for each server"""
        for server_name in self.servers.keys():
            self._create_server_tab(server_name)

    def _create_server_tab(self, server_name):
        """Create a tab for a specific server"""
        # Create frame for this server's tab
        tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(tab_frame, text=f"{server_name}")

        # Server info frame
        info_frame = tk.Frame(tab_frame, bg=self.theme["bg_color"], pady=10)
        info_frame.pack(fill=tk.X, padx=(15, 5))

        # Server info label
        ip_address = self.servers[server_name]
        info_label = tk.Label(
            info_frame,
            text=f"{server_name} ({ip_address})",
            font=("Segoe UI", 12, "bold"),
            bg=self.theme["bg_color"],
            fg=self.theme["accent_color"],
            padx=5,
        )
        info_label.pack(side=tk.LEFT)

        # Text widget with modern styling
        frame = tk.Frame(tab_frame, bg="#181818", padx=2, pady=2)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        text_widget = scrolledtext.ScrolledText(
            frame,
            font=("Consolas", 10),
            bg=self.theme["log_bg_color"],
            fg=self.theme["text_color"],
            insertbackground=self.theme["text_color"],
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
        status_frame = tk.Frame(tab_frame, bg=self.theme["bg_color"], height=30)
        status_frame.pack(fill=tk.X, pady=10, padx=5)

        status_label = tk.Label(
            status_frame,
            text="Initializing...",
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 9),
        )
        status_label.pack(side=tk.LEFT)

        # Store references
        self.text_widgets[server_name] = text_widget
        self.status_labels[server_name] = status_label

    def fade_highlight(self, text_widget, tag, steps_left):
        """Fade out the highlight of new entries"""
        if steps_left <= 0 or not self.app.running:
            try:
                # Set to normal background color and remove the tag
                text_widget.tag_configure(tag, background=self.theme["log_bg_color"])
                text_widget.tag_delete(tag)
            except tk.TclError:
                pass  # Widget might be destroyed
            return

        try:
            # Calculate interpolation between highlight color and log background color
            progress = steps_left / self.animation_steps  # 1.0 to 0.0

            # Extract RGB values from highlight color (#3a3a3a)
            highlight_r = int(self.theme["bg_highlight_color"][1:3], 16)
            highlight_g = int(self.theme["bg_highlight_color"][3:5], 16)
            highlight_b = int(self.theme["bg_highlight_color"][5:7], 16)

            # Extract RGB values from log background color (#1e1e1e)
            log_bg_r = int(self.theme["log_bg_color"][1:3], 16)
            log_bg_g = int(self.theme["log_bg_color"][3:5], 16)
            log_bg_b = int(self.theme["log_bg_color"][5:7], 16)

            # Interpolate between highlight and log background colors
            r = int(highlight_r * progress + log_bg_r * (1 - progress))
            g = int(highlight_g * progress + log_bg_g * (1 - progress))
            b = int(highlight_b * progress + log_bg_b * (1 - progress))

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

    def update_display(self, server_name, formatted_result, statistics=None):
        """Update the display for a specific server"""
        if server_name not in self.text_widgets:
            return

        text_widget = self.text_widgets[server_name]

        try:
            # Create unique tag for highlight effect
            import time

            highlight_tag = f"highlight_{time.time()}"

            # Enable text widget for updating
            text_widget.config(state=tk.NORMAL)

            # Add the new entry with its styling
            if self.animation_enabled:
                text_widget.tag_configure(
                    highlight_tag, background=self.theme["bg_highlight_color"]
                )
                text_widget.insert(
                    tk.END,
                    formatted_result["text"] + "\n",
                    (formatted_result["tag"], highlight_tag),
                )
                # Schedule highlight fade-out
                self.fade_highlight(text_widget, highlight_tag, self.animation_steps)
            else:
                text_widget.insert(
                    tk.END, formatted_result["text"] + "\n", formatted_result["tag"]
                )

            # Only auto-scroll if user is already at the bottom (within 5% of the end)
            # This prevents interrupting users who are scrolling through older logs
            try:
                first, last = text_widget.yview()
                if last >= 0.95:  # User is near the bottom, auto-scroll to new content
                    self.smooth_scroll_to_end(text_widget)
            except tk.TclError:
                pass  # Widget might be destroyed

            # Disable text widget
            text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass  # Widget might be destroyed

        # Update status if statistics provided
        if statistics and server_name in self.status_labels:
            status_text = (
                f"Best: {statistics['best']}ms | "
                f"Worst: {statistics['worst']}ms | "
                f"Avg: {round(statistics['avg'])}ms | "
                f"Deviations: {statistics['deviations']}x"
            )
            self.status_labels[server_name].config(text=status_text)

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
        if steps_left <= 0 or not self.app.running:
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

    def _start_gui_update_thread(self):
        """Start the GUI update thread"""

        def update_gui_periodically():
            """Update GUI from the main thread"""
            try:
                if (
                    self.app.ping_service
                    and not self.app.ping_service.ping_queue.empty()
                ):
                    result = self.app.ping_service.ping_queue.get_nowait()
                    self.app._process_ping_result(result)
            except:
                pass
            finally:
                # Schedule next update from main thread
                if self.root and self.app.running:
                    self.root.after(100, update_gui_periodically)

        # Start the periodic updates from the main thread
        if self.root:
            self.root.after(100, update_gui_periodically)

    def show(self):
        """Show the main window"""
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.window_visible = True

    def hide(self):
        """Hide the main window"""
        if self.root:
            self.root.withdraw()
            self.window_visible = False

    def is_visible(self):
        """Check if window is visible"""
        return self.window_visible

    def mainloop(self):
        """Start the GUI main loop"""
        if self.root:
            self.root.mainloop()

    def destroy(self):
        """Destroy the window"""
        if self.root:
            self.root.destroy()
