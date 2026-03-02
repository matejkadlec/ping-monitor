import tkinter as tk
from tkinter import ttk, scrolledtext
import time
import os
from PIL import Image, ImageTk


class ServerTab:
    """Represents a single server tab in the UI"""

    def __init__(
        self,
        notebook,
        server_name,
        ip_address,
        theme,
        animation_utils,
        root,
        app_running_check,
    ):
        self.notebook = notebook
        self.server_name = server_name
        self.ip_address = ip_address
        self.theme = theme
        self.animation_utils = animation_utils
        self.root = root
        self.app_running_check = app_running_check

        self.text_widget = None
        self.status_label = None
        self.overall_prefix_label = None
        self.overall_value_label = None
        self.stats_label = None
        self.pinged_label = None

        self._create_tab()

    def _create_tab(self):
        """Create the tab UI elements"""
        # Create frame for this server's tab
        # Ensure the frame has the correct background color immediately
        style = ttk.Style()
        style.configure("ServerTab.TFrame", background=self.theme["bg_color"])
        tab_frame = ttk.Frame(self.notebook, style="ServerTab.TFrame")
        self.notebook.add(tab_frame, text=f"{self.server_name}")

        info_frame = tk.Frame(tab_frame, bg=self.theme["bg_color"], pady=10)
        info_frame.pack(fill=tk.X, padx=(15, 5))

        info_label = tk.Label(
            info_frame,
            text=f"{self.server_name} ({self.ip_address})",
            font=("Segoe UI", 12, "bold"),
            bg=self.theme["bg_color"],
            fg=self.theme["accent_color"],
            padx=5,
        )
        info_label.pack(side=tk.LEFT)

        frame = tk.Frame(tab_frame, bg=self.theme["log_bg_color"], padx=1, pady=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.text_widget = scrolledtext.ScrolledText(
            frame,
            font=("Consolas", 10),
            bg=self.theme["log_bg_color"],
            fg=self.theme["log_text_color"],
            insertbackground=self.theme["log_text_color"],
            selectbackground="#b3d7ff",
            wrap=tk.WORD,
            state=tk.DISABLED,
            borderwidth=0,
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        self.text_widget.tag_configure("excellent_ping", foreground="#009900")
        self.text_widget.tag_configure("good_ping", foreground="#b38f00")
        self.text_widget.tag_configure("bad_ping", foreground="#cc0000")

        status_frame = tk.Frame(tab_frame, bg=self.theme["bg_color"], height=30)
        status_frame.pack(fill=tk.X, pady=10, padx=5)

        left_status_frame = tk.Frame(status_frame, bg=self.theme["bg_color"])
        left_status_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.overall_prefix_label = tk.Label(
            left_status_frame,
            text="Overall ping: ",
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 9),
        )
        self.overall_prefix_label.pack(side=tk.LEFT)

        self.overall_value_label = tk.Label(
            left_status_frame,
            text="Healthy",
            bg=self.theme["bg_color"],
            fg="#00cc66",
            font=("Segoe UI", 9, "bold"),
        )
        self.overall_value_label.pack(side=tk.LEFT)

        self.stats_label = tk.Label(
            left_status_frame,
            text="",
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 9),
        )
        self.stats_label.pack(side=tk.LEFT)

        self.pinged_label = tk.Label(
            status_frame,
            text="",
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 9),
            width=38,
            anchor="e",
        )
        self.pinged_label.pack(side=tk.RIGHT)

    def _create_heavy_ui(self, tab_frame):
        """Deprecated: UI is now created immediately"""
        pass

    def update_display(self, formatted_result, statistics=None):
        """Update the display with new ping result"""
        try:
            highlight_tag = f"highlight_{time.time()}"

            # Enable text widget for updating
            self.text_widget.config(state=tk.NORMAL)

            # Add the new entry with its styling
            if self.animation_utils.enabled:
                self.text_widget.tag_configure(
                    highlight_tag, background=self.theme["bg_highlight_color"]
                )
                self.text_widget.insert(
                    tk.END,
                    formatted_result["text"] + "\n",
                    (formatted_result["tag"], highlight_tag),
                )
                # Schedule highlight fade-out
                self.animation_utils.fade_highlight(
                    self.root,
                    self.text_widget,
                    highlight_tag,
                    self.animation_utils.steps,
                    self.app_running_check,
                )
            else:
                self.text_widget.insert(
                    tk.END, formatted_result["text"] + "\n", formatted_result["tag"]
                )

            # Only auto-scroll if user is already at the bottom (within 5% of the end)
            try:
                first, last = self.text_widget.yview()
                if last >= 0.95:  # User is near the bottom, auto-scroll to new content
                    self.animation_utils.smooth_scroll_to_end(
                        self.root, self.text_widget, self.app_running_check
                    )
            except tk.TclError:
                pass  # Widget might be destroyed

            # Disable text widget
            self.text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass

        if statistics and self.stats_label:
            overall_status = statistics.get("overall_status", "healthy")
            status_colors = {
                "healthy": "#00cc66",
                "degraded": "#d4b000",
                "failing": "#cc0000",
            }

            next_overall_text = overall_status.title()
            next_overall_fg = status_colors.get(
                overall_status, self.theme["text_color"]
            )
            if (
                self.overall_value_label.cget("text") != next_overall_text
                or self.overall_value_label.cget("fg") != next_overall_fg
            ):
                self.overall_value_label.config(
                    text=next_overall_text,
                    fg=next_overall_fg,
                )

            status_text = (
                f" (Best: {statistics['best']}ms | "
                f"Worst: {statistics['worst']}ms | "
                f"Avg: {round(statistics['avg'])}ms | "
                f"Ping spikes: {statistics['ping_spikes']}x)"
            )
            if self.stats_label.cget("text") != status_text:
                self.stats_label.config(text=status_text)

            elapsed_minutes = max(1, statistics.get("elapsed_minutes", 1))
            minute_word = "minute" if elapsed_minutes == 1 else "minutes"
            pinged_count = statistics.get("pinged_count", 0)
            pinged_text = (
                f"Pinged {pinged_count} times over {elapsed_minutes} {minute_word}."
            )
            if self.pinged_label.cget("text") != pinged_text:
                self.pinged_label.config(text=pinged_text)

    def reset(self):
        """Reset the text widget content"""
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete(1.0, tk.END)
        self.text_widget.config(state=tk.DISABLED)
