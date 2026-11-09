"""
Main GUI window for the Ping Monitor application.
"""

import tkinter as tk
from tkinter import ttk, font, Menu, scrolledtext
import os
import logging
import copy
from PIL import Image, ImageTk
from src.core.config import (
    THEME,
    BACKGROUND_FILE,
    PING_SPIKES_FILE,
    ANIMATION_SETTINGS,
)
import src.core.config as config_module
from src.gui.components.server_tab import ServerTab
from src.gui.dialogs.first_run import FirstRunDialog
from src.gui.utils.animations import AnimationUtils
from src.gui.utils.toast_manager import ToastManager

try:
    from ttkbootstrap_icons_fa import FAIcon
except Exception:
    FAIcon = None


class MainWindow:
    """Main application window with tabbed interface"""

    def __init__(self, servers, app_instance):
        self.servers = servers
        self.app = app_instance
        self.theme = THEME
        self.logger = logging.getLogger(__name__)

        # GUI elements
        self.root = None
        self.notebook = None
        self.server_tabs = {}
        self.window_visible = False
        self.bg_image_original = None
        self.bg_image_tk = None
        self.bg_label = None
        self.overlay_backdrop = None
        self.overlay_backdrop_image = None
        self.overlay_backdrop_photo = None
        self.logs_overlay_frame = None
        self.logs_window = None
        self.logs_text_widget = None
        self.logs_refresh_job = None
        self.config_window = None
        self.config_rows = []
        self.config_dirty = False
        self.config_initial_state = None
        self.config_save_btn = None
        self.config_close_to_tray_var = None
        self.config_threshold_healthy_var = None
        self.config_threshold_degraded_var = None
        self.config_interval_var = None
        self.config_preserved_var = None
        self.overlay_backdrop_refresh_job = None
        self.last_logs_content = None
        self.bulk_update_overlay = None

        # Resize handling
        self.resize_timer = None
        self.is_resizing = False
        self.resize_overlay = None

        # Utilities
        self.animation_utils = AnimationUtils(THEME, ANIMATION_SETTINGS)
        self.toast_manager = None

        # State flags
        self.updates_paused = False

        self._setup_gui()

        # Show first-run dialog if not configured, otherwise start services
        delay = 100 if config_module.CLOSE_TO_TRAY is None else 0
        self.root.after(delay, self._check_close_behavior)

    def _check_close_behavior(self):
        """Check if close behavior is configured, if not ask user"""
        if config_module.CLOSE_TO_TRAY is None:
            # Pause updates while dialog is open
            self.updates_paused = True

            def on_complete():
                self.root.deiconify()
                self.root.geometry("1200x800")
                self.window_visible = True
                self.updates_paused = False
                self.app.start_services()
                self._start_gui_update_thread()

            dialog = FirstRunDialog(self.root, self.theme, self.app, on_complete)
            dialog.show()

        else:
            # Apply configured behavior
            self.apply_close_behavior(config_module.CLOSE_TO_TRAY)

            # Start background services immediately for normal run
            self.app.start_services()
            self._start_gui_update_thread()

    def _setup_gui(self):
        """Setup the main GUI window with tabbed interface"""
        self.root = tk.Tk()
        self.root.title("Ping Monitor")
        self.root.geometry("1000x700")
        self.root.report_callback_exception = self._handle_tk_exception

        # Load background image
        bg_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            BACKGROUND_FILE,
        )
        if os.path.exists(bg_path):
            try:
                self.bg_image_original = Image.open(bg_path)
                self.bg_label = tk.Label(self.root, borderwidth=0)
                self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
                self.root.bind("<Configure>", self._resize_background)
            except Exception as e:
                self.logger.exception("Error loading background image: %s", e)
                self.root.configure(bg=self.theme["bg_color"])
        else:
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
                self.logger.exception("Error setting window icon: %s", e)

        # Configure window visibility based on first run status
        if config_module.CLOSE_TO_TRAY is None:
            self.root.withdraw()
            self.window_visible = False
        else:
            self.root.geometry("1200x800")
            self.window_visible = True

        # Configure window close button - will be updated by _check_close_behavior
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        # Configure custom fonts
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
        self.root.option_add("*Font", default_font)

        self._create_main_layout()
        self._create_server_tabs()
        self.toast_manager = ToastManager(self.root)
        # Note: _start_gui_update_thread is now called after configuration/startup

    def _resize_background(self, event):
        """Resize background image to fit window with debounce"""
        if event.widget != self.root:
            return

        if not self.bg_image_original or not self.bg_label:
            return

        # Only resize if dimensions changed significantly
        if (
            hasattr(self, "_last_bg_size")
            and abs(self._last_bg_size[0] - event.width) < 10
            and abs(self._last_bg_size[1] - event.height) < 10
        ):
            return

        # Cancel previous timer
        if self.resize_timer:
            self.root.after_cancel(self.resize_timer)

        # Show overlay to cover white background during resize
        if not self.is_resizing:
            self.is_resizing = True
            self._show_resize_overlay()

        # Schedule the actual resize
        self.resize_timer = self.root.after(
            300, lambda: self._perform_resize(event.width, event.height)
        )

    def _show_resize_overlay(self):
        """Show overlay to cover white background during resize"""
        if not self.resize_overlay:
            self.resize_overlay = tk.Frame(self.root, bg=self.theme["bg_color"])

        self.resize_overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self.resize_overlay.lift()

    def _perform_resize(self, width, height):
        """Perform the actual background resize"""
        self.is_resizing = False

        # Hide overlay
        if self.resize_overlay:
            self.resize_overlay.place_forget()

        self._last_bg_size = (width, height)

        # Resize image using LANCZOS and crop to center
        img_w, img_h = self.bg_image_original.size
        target_w, target_h = width, height

        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)

        resized = self.bg_image_original.resize(
            (new_w, new_h), Image.Resampling.LANCZOS
        )

        # Crop to center
        left = (new_w - target_w) / 2
        top = (new_h - target_h) / 2
        right = (new_w + target_w) / 2
        bottom = (new_h + target_h) / 2

        cropped = resized.crop((left, top, right, bottom))

        self.bg_image_tk = ImageTk.PhotoImage(cropped)
        self.bg_label.configure(image=self.bg_image_tk)

    def _set_windows_app_id(self):
        """Set Windows app ID for better taskbar integration"""
        try:
            import ctypes

            myappid = f"matka.pingmonitor.1.2.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            self.logger.warning("Non-critical error setting app ID: %s", e)

    def _create_main_layout(self):
        """Create the main layout with toolbar, content, and footer"""
        # Main container with margins to show background
        self.main_container = tk.Frame(self.root, bg=self.theme["bg_color"])
        self.main_container.place(relx=0.05, rely=0.05, relwidth=0.9, relheight=0.9)

        # Toolbar
        self._create_toolbar(self.main_container)

        # Create notebook (tabbed interface)
        self._create_notebook(self.main_container)

    def _create_toolbar(self, parent):
        """Create the toolbar with icon buttons"""
        toolbar_frame = tk.Frame(parent, bg=self.theme["bg_color"])
        toolbar_frame.pack(fill=tk.X, pady=5, padx=5)

        self.icons = {
            "config": self._draw_icon("gear"),
            "logs": self._draw_icon("file-lines"),
            "reset": self._draw_icon("arrow-rotate-left"),
        }

        btn_config = tk.Label(
            toolbar_frame,
            image=self.icons["config"],
            bg=self.theme["bg_color"],
            cursor="hand2",
        )
        btn_config.pack(side=tk.LEFT, padx=(5, 1))
        btn_config.bind("<Button-1>", lambda e: self._open_config())
        self._create_tooltip(btn_config, "Open config")

        btn_logs = tk.Label(
            toolbar_frame,
            image=self.icons["logs"],
            bg=self.theme["bg_color"],
            cursor="hand2",
        )
        btn_logs.pack(side=tk.LEFT, padx=1)
        btn_logs.bind("<Button-1>", lambda e: self._open_logs())
        self._create_tooltip(btn_logs, "Open logs")

        btn_reset = tk.Label(
            toolbar_frame,
            image=self.icons["reset"],
            bg=self.theme["bg_color"],
            cursor="hand2",
        )
        btn_reset.pack(side=tk.LEFT, padx=1)
        btn_reset.bind("<Button-1>", lambda e: self._show_reset_menu(e))
        self._create_tooltip(btn_reset, "Reset metrics")

    def _draw_icon(self, name, size=24):
        """Render toolbar icons using Font Awesome icons."""
        if FAIcon is None:
            raise RuntimeError(
                "ttkbootstrap-icons-fa is required for toolbar icon rendering."
            )
        return FAIcon(
            name, size=size, color=self.theme["accent_color"], style="solid"
        ).image

    def _create_tooltip(self, widget, text):
        """Create a simple tooltip for a widget"""

        def enter(event):
            x, y, _, _ = widget.bbox("insert")
            x += widget.winfo_rootx() + 25
            y += widget.winfo_rooty() + 20

            self.tooltip = tk.Toplevel(widget)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry(f"+{x}+{y}")

            label = tk.Label(
                self.tooltip,
                text=text,
                background="#ffffe0",
                relief="solid",
                borderwidth=1,
                font=("Segoe UI", 8),
            )
            label.pack()

        def leave(event):
            if hasattr(self, "tooltip"):
                self.tooltip.destroy()

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _create_rounded_button(
        self,
        parent,
        text,
        command,
        width=86,
        height=30,
        font_spec=("Segoe UI", 10, "bold"),
        enabled=True,
        text_y_offset=0,
        normal_bg="#123462",
        hover_bg="#183f75",
        border_color="#0b2242",
        text_color=None,
    ):
        disabled_bg = "#324a64"
        disabled_fg = "#9eb1c9"
        if text_color is None:
            text_color = self.theme["text_color"]

        canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=self.theme["log_bg_color"],
            bd=0,
            highlightthickness=0,
            cursor="hand2" if enabled else "",
        )

        state = {"enabled": enabled}

        def draw(bg_color, fg_color):
            canvas.delete("all")
            radius = max(6, min(10, int(height / 2) - 2))

            def rounded_points(x1, y1, x2, y2, r):
                return [
                    x1 + r,
                    y1,
                    x2 - r,
                    y1,
                    x2,
                    y1,
                    x2,
                    y1 + r,
                    x2,
                    y2 - r,
                    x2,
                    y2,
                    x2 - r,
                    y2,
                    x1 + r,
                    y2,
                    x1,
                    y2,
                    x1,
                    y2 - r,
                    x1,
                    y1 + r,
                    x1,
                    y1,
                ]

            outer_points = rounded_points(1, 1, width - 1, height - 1, radius)
            inner_points = rounded_points(
                2, 2, width - 2, height - 2, max(4, radius - 1)
            )

            canvas.create_polygon(
                outer_points,
                smooth=True,
                fill=border_color,
                outline=border_color,
                splinesteps=20,
            )
            canvas.create_polygon(
                inner_points,
                smooth=True,
                fill=bg_color,
                outline=bg_color,
                splinesteps=20,
            )
            canvas.create_text(
                width // 2,
                (height // 2) + text_y_offset,
                text=text,
                fill=fg_color,
                font=font_spec,
            )

        def set_enabled(is_enabled):
            state["enabled"] = bool(is_enabled)
            canvas.configure(cursor="hand2" if state["enabled"] else "")
            if state["enabled"]:
                draw(normal_bg, text_color)
            else:
                draw(disabled_bg, disabled_fg)

        def on_enter(_event):
            if state["enabled"]:
                draw(hover_bg, text_color)

        def on_leave(_event):
            if state["enabled"]:
                draw(normal_bg, text_color)

        def on_click(_event):
            if state["enabled"] and callable(command):
                command()

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<Button-1>", on_click)

        set_enabled(enabled)
        return {"widget": canvas, "set_enabled": set_enabled}

    def _open_config(self):
        """Open in-app configuration window."""
        try:
            self._show_config_window()
        except Exception as e:
            self.logger.exception("Error opening config window: %s", e)
            if self.toast_manager:
                self.toast_manager.show("Unable to open config window.", "error")

    def _show_config_window(self):
        if self.config_window and self.config_window.winfo_exists():
            self.config_window.lift()
            self.config_window.focus_force()
            return

        self._create_overlay_backdrop()

        config_snapshot = config_module.get_runtime_config_snapshot()
        self.config_initial_state = copy.deepcopy(config_snapshot)
        self.config_rows = []
        self.config_dirty = False

        overlay_width = 540
        overlay_height = 480

        self.config_window = tk.Toplevel(self.root)
        self.config_window.withdraw()
        self.config_window.title("App config")
        self.config_window.transient(self.root)
        self.config_window.resizable(True, True)
        self.config_window.minsize(500, 420)
        self.config_window.configure(bg=self.theme["bg_color"])
        self.config_window.protocol("WM_DELETE_WINDOW", self._close_config_window)

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        pos_x = root_x + max(0, (root_w - overlay_width) // 2)
        pos_y = root_y + max(0, (root_h - overlay_height) // 2)
        self.config_window.geometry(f"{overlay_width}x{overlay_height}+{pos_x}+{pos_y}")

        shell = tk.Frame(
            self.config_window,
            bg=self.theme["log_bg_color"],
            highlightbackground=self.theme["accent_color"],
            highlightthickness=1,
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        content = tk.Frame(shell, bg=self.theme["log_bg_color"])
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self._build_servers_section(content, config_snapshot)
        self._build_settings_section(content, config_snapshot)

        action_row = tk.Frame(shell, bg=self.theme["log_bg_color"])
        action_row.pack(fill=tk.X, padx=12, pady=(8, 12))

        self.config_save_btn = self._create_rounded_button(
            action_row,
            text="Save",
            command=self._save_config_window,
            width=78,
            height=30,
            font_spec=("Segoe UI", 10, "bold"),
            enabled=False,
        )
        self.config_save_btn["widget"].pack(side=tk.RIGHT)

        cancel_btn = self._create_rounded_button(
            action_row,
            text="Cancel",
            command=self._close_config_window,
            width=88,
            height=30,
            font_spec=("Segoe UI", 10, "bold"),
            enabled=True,
        )
        cancel_btn["widget"].pack(side=tk.RIGHT, padx=(0, 16))

        self.config_window.update_idletasks()
        self.config_window.deiconify()
        self.config_window.lift()
        self.config_window.focus_force()

        self._refresh_config_dirty_state()

    def _build_servers_section(self, parent, config_snapshot):
        header_row = tk.Frame(parent, bg=self.theme["log_bg_color"])
        header_row.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            header_row,
            text="Servers",
            bg=self.theme["log_bg_color"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT)

        add_button = self._create_rounded_button(
            header_row,
            text="+",
            command=self._add_server_row,
            width=22,
            height=28,
            font_spec=("Segoe UI", 16, "bold"),
            enabled=True,
            text_y_offset=0,
            normal_bg=self.theme["text_color"],
            hover_bg="#e8eef7",
            border_color="#d4deec",
            text_color=self.theme["bg_color"],
        )
        add_button["widget"].pack(side=tk.RIGHT)

        table_frame = tk.Frame(parent, bg=self.theme["log_bg_color"])
        table_frame.pack(fill=tk.X, pady=(0, 10))
        self.config_table_frame = table_frame

        tk.Label(
            table_frame,
            text="Name",
            bg=self.theme["log_bg_color"],
            fg=self.theme["inactive_tab_fg"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 4))
        tk.Label(
            table_frame,
            text="IP",
            bg=self.theme["log_bg_color"],
            fg=self.theme["inactive_tab_fg"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=(0, 4))

        table_frame.grid_columnconfigure(0, weight=2)
        table_frame.grid_columnconfigure(1, weight=2)
        table_frame.grid_columnconfigure(2, weight=0)

        for name, ip in config_snapshot["servers"].items():
            self._create_server_row(name, ip)

    def _build_settings_section(self, parent, config_snapshot):
        settings_frame = tk.Frame(parent, bg=self.theme["log_bg_color"])
        settings_frame.pack(fill=tk.X, pady=(4, 0))

        self.config_threshold_healthy_var = tk.StringVar(
            value=str(config_snapshot["ping_threshold_healthy"])
        )
        self.config_threshold_degraded_var = tk.StringVar(
            value=str(config_snapshot["ping_threshold_degraded"])
        )
        self.config_interval_var = tk.StringVar(
            value=str(config_snapshot["ping_interval"])
        )
        self.config_preserved_var = tk.StringVar(
            value=str(config_snapshot["preserved_minutes"])
        )
        self.config_close_to_tray_var = tk.BooleanVar(
            value=bool(config_snapshot["close_to_tray"])
        )

        self._create_setting_row(
            settings_frame,
            row=0,
            label_text="Ping Threshold Healthy",
            tooltip_text="In milliseconds.",
            widget=self._create_numeric_entry(
                settings_frame, self.config_threshold_healthy_var
            ),
        )
        self._create_setting_row(
            settings_frame,
            row=1,
            label_text="Ping Threshold Degraded",
            tooltip_text="In milliseconds.",
            widget=self._create_numeric_entry(
                settings_frame, self.config_threshold_degraded_var
            ),
        )
        self._create_setting_row(
            settings_frame,
            row=2,
            label_text="Ping Interval",
            tooltip_text="Seconds between pings.",
            widget=self._create_numeric_entry(settings_frame, self.config_interval_var),
        )
        self._create_setting_row(
            settings_frame,
            row=3,
            label_text="Preserved Minutes",
            tooltip_text="Minutes to preserve and display per tab.",
            widget=self._create_numeric_entry(
                settings_frame, self.config_preserved_var
            ),
        )

        close_checkbox = tk.Checkbutton(
            settings_frame,
            variable=self.config_close_to_tray_var,
            bg=self.theme["log_bg_color"],
            activebackground=self.theme["log_bg_color"],
            selectcolor=self.theme["bg_color"],
            highlightthickness=0,
            bd=0,
            command=self._refresh_config_dirty_state,
            cursor="hand2",
        )
        self._create_setting_row(
            settings_frame,
            row=4,
            label_text="Close To Tray",
            tooltip_text="App will minimize to system tray icon instead of closing.",
            widget=close_checkbox,
        )

        settings_frame.grid_columnconfigure(0, weight=2, uniform="config_settings")
        settings_frame.grid_columnconfigure(1, weight=2, uniform="config_settings")
        settings_frame.grid_columnconfigure(2, weight=0, minsize=28)

    def _create_numeric_entry(self, parent, text_var):
        entry = tk.Entry(
            parent,
            textvariable=text_var,
            width=4,
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            insertbackground=self.theme["text_color"],
            relief=tk.FLAT,
            justify="left",
        )
        entry.bind("<KeyRelease>", lambda _event: self._refresh_config_dirty_state())
        return entry

    def _create_setting_row(self, parent, row, label_text, tooltip_text, widget):
        left = tk.Frame(parent, bg=self.theme["log_bg_color"])
        left.grid(row=row, column=0, sticky="ew", pady=4)

        tk.Label(
            left,
            text=label_text,
            bg=self.theme["log_bg_color"],
            fg=self.theme["text_color"],
            anchor="w",
        ).pack(side=tk.LEFT)

        info_label = tk.Label(
            left,
            text="ⓘ",
            bg=self.theme["log_bg_color"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 11, "bold"),
            cursor="question_arrow",
        )
        info_label.pack(side=tk.LEFT, padx=(8, 0), pady=(0, 1))
        self._create_tooltip(info_label, tooltip_text)

        widget.grid(row=row, column=1, sticky="w", padx=(0, 6), pady=4)

        spacer = tk.Frame(parent, bg=self.theme["log_bg_color"], width=28, height=1)
        spacer.grid(row=row, column=2, sticky="e")

    def _create_server_row(self, name_value="", ip_value=""):
        row_index = len(self.config_rows) + 1
        name_var = tk.StringVar(value=name_value)
        ip_var = tk.StringVar(value=ip_value)

        name_entry = tk.Entry(
            self.config_table_frame,
            textvariable=name_var,
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            insertbackground=self.theme["text_color"],
            relief=tk.FLAT,
        )
        name_entry.grid(row=row_index, column=0, sticky="ew", padx=(0, 6), pady=2)

        ip_entry = tk.Entry(
            self.config_table_frame,
            textvariable=ip_var,
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            insertbackground=self.theme["text_color"],
            relief=tk.FLAT,
        )
        ip_entry.grid(row=row_index, column=1, sticky="ew", padx=(0, 6), pady=2)

        delete_btn = tk.Button(
            self.config_table_frame,
            text="🗑",
            bg=self.theme["inactive_tab_bg"],
            fg=self.theme["text_color"],
            relief=tk.FLAT,
            bd=0,
            width=3,
            cursor="hand2",
            command=lambda: self._delete_server_row(row_data),
        )
        delete_btn.grid(row=row_index, column=2, sticky="e", pady=2)
        self._create_tooltip(delete_btn, "Delete this record")

        row_data = {
            "frame_row": row_index,
            "name_var": name_var,
            "ip_var": ip_var,
            "name_entry": name_entry,
            "ip_entry": ip_entry,
            "delete_btn": delete_btn,
        }

        name_entry.bind(
            "<KeyRelease>", lambda _event: self._refresh_config_dirty_state()
        )
        ip_entry.bind("<KeyRelease>", lambda _event: self._refresh_config_dirty_state())

        self.config_rows.append(row_data)
        self._refresh_config_dirty_state()

    def _reflow_server_rows(self):
        for row_index, row_data in enumerate(self.config_rows, start=1):
            row_data["frame_row"] = row_index
            row_data["name_entry"].grid_configure(row=row_index)
            row_data["ip_entry"].grid_configure(row=row_index)
            row_data["delete_btn"].grid_configure(row=row_index)

    def _add_server_row(self):
        for row_data in self.config_rows:
            if (
                not row_data["name_var"].get().strip()
                or not row_data["ip_var"].get().strip()
            ):
                if self.toast_manager:
                    self.toast_manager.show(
                        "Finish the existing empty row first.", "warning"
                    )
                return
        self._create_server_row("", "")

    def _delete_server_row(self, row_data):
        if len(self.config_rows) <= 1:
            if self.toast_manager:
                self.toast_manager.show("At least one server is required.", "warning")
            return

        confirm = self._show_confirmation_dialog(
            "Delete server",
            "Are you sure you want to delete this record?",
        )
        if not confirm:
            return

        for widget_name in ("name_entry", "ip_entry", "delete_btn"):
            row_data[widget_name].destroy()
        self.config_rows = [row for row in self.config_rows if row is not row_data]
        self._reflow_server_rows()
        self._refresh_config_dirty_state()

    def _current_config_state_from_window(self):
        if (
            self.config_threshold_healthy_var is None
            or self.config_threshold_degraded_var is None
            or self.config_interval_var is None
            or self.config_preserved_var is None
            or self.config_close_to_tray_var is None
        ):
            return {
                "servers": {},
                "ping_threshold_healthy": "",
                "ping_threshold_degraded": "",
                "ping_interval": "",
                "preserved_minutes": "",
                "close_to_tray": False,
            }

        servers = {}
        for row_data in self.config_rows:
            name = row_data["name_var"].get().strip()
            ip = row_data["ip_var"].get().strip()
            if name or ip:
                servers[name] = ip

        return {
            "servers": servers,
            "ping_threshold_healthy": self.config_threshold_healthy_var.get().strip(),
            "ping_threshold_degraded": self.config_threshold_degraded_var.get().strip(),
            "ping_interval": self.config_interval_var.get().strip(),
            "preserved_minutes": self.config_preserved_var.get().strip(),
            "close_to_tray": bool(self.config_close_to_tray_var.get()),
        }

    def _refresh_config_dirty_state(self):
        if not (self.config_window and self.config_window.winfo_exists()):
            return

        current_state = self._current_config_state_from_window()
        normalized_initial = {
            "servers": dict(self.config_initial_state["servers"]),
            "ping_threshold_healthy": str(
                self.config_initial_state["ping_threshold_healthy"]
            ),
            "ping_threshold_degraded": str(
                self.config_initial_state["ping_threshold_degraded"]
            ),
            "ping_interval": str(self.config_initial_state["ping_interval"]),
            "preserved_minutes": str(self.config_initial_state["preserved_minutes"]),
            "close_to_tray": bool(self.config_initial_state["close_to_tray"]),
        }

        self.config_dirty = current_state != normalized_initial
        if self.config_save_btn and self.config_save_btn.get("widget"):
            self.config_save_btn["set_enabled"](self.config_dirty)

    def _validate_config_payload(self, payload):
        servers = payload["servers"]
        if not servers:
            return False, "At least one server is required.", None

        clean_servers = {}
        for name, ip in servers.items():
            clean_name = name.strip()
            clean_ip = ip.strip()
            if not clean_name or not clean_ip:
                return False, "Server name and IP must both be filled.", None
            if clean_name in clean_servers:
                return False, f"Duplicate server name: {clean_name}", None
            clean_servers[clean_name] = clean_ip

        numeric_fields = {}
        for key, label in (
            ("ping_threshold_healthy", "Ping Threshold Healthy"),
            ("ping_threshold_degraded", "Ping Threshold Degraded"),
            ("ping_interval", "Ping Interval"),
            ("preserved_minutes", "Preserved Minutes"),
        ):
            raw_value = payload[key]
            if not raw_value.isdigit():
                return False, f"{label} must be a number.", None
            value = int(raw_value)
            if value < 1 or value > 999:
                return False, f"{label} must be between 1 and 999.", None
            numeric_fields[key] = value

        if (
            numeric_fields["ping_threshold_degraded"]
            < numeric_fields["ping_threshold_healthy"]
        ):
            return (
                False,
                "Ping Threshold Degraded must be greater than or equal to Ping Threshold Healthy.",
                None,
            )

        initial_ips = set()
        if self.config_initial_state and self.config_initial_state.get("servers"):
            initial_ips = set(self.config_initial_state["servers"].values())

        for name, ip in clean_servers.items():
            if ip in initial_ips:
                continue

            success = False
            for _ in range(2):
                validation_result = self.app.ping_service.ping_server(name, ip)
                if validation_result["status"] == "success":
                    success = True
                    break
            if not success:
                return False, f"The server IP is invalid: {ip}", None

        return (
            True,
            "",
            {
                "servers": clean_servers,
                "ping_threshold_healthy": numeric_fields["ping_threshold_healthy"],
                "ping_threshold_degraded": numeric_fields["ping_threshold_degraded"],
                "ping_interval": numeric_fields["ping_interval"],
                "preserved_minutes": numeric_fields["preserved_minutes"],
                "close_to_tray": bool(payload["close_to_tray"]),
            },
        )

    def _save_config_window(self):
        payload = self._current_config_state_from_window()
        is_valid, error_message, sanitized = self._validate_config_payload(payload)
        if not is_valid:
            if self.toast_manager:
                self.toast_manager.show(error_message, "error")
            return

        self.app.apply_runtime_config(sanitized)
        self.config_initial_state = copy.deepcopy(sanitized)
        self._refresh_config_dirty_state()
        if self.toast_manager:
            self.toast_manager.show("Configuration saved successfully.", "success")
        self._destroy_config_window(force=True)

    def _close_config_window(self):
        if self.config_dirty:
            proceed = self._show_confirmation_dialog(
                "Discard changes",
                "You have unsaved changes that will be discarded if you continue. Do you wish to proceed?",
            )
            if not proceed:
                return
        self._destroy_config_window(force=True)

    def _destroy_config_window(self, force=False):
        if self.config_window and self.config_window.winfo_exists():
            self.config_window.destroy()
        self.config_window = None
        self.config_rows = []
        self.config_save_btn = None
        self.config_initial_state = None
        self.config_dirty = False
        self._destroy_overlay_backdrop()

    def _show_confirmation_dialog(self, title, message):
        result = {"value": False}
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("Unsaved changes detected")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=self.theme["log_bg_color"])
        dialog.grab_set()

        width = 460
        height = 170
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        pos_x = root_x + max(0, (root_w - width) // 2)
        pos_y = root_y + max(0, (root_h - height) // 2)
        dialog.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()

        tk.Label(
            dialog,
            text=message.replace(
                " Do you wish to proceed?", "\nDo you wish to proceed?"
            ),
            bg=self.theme["log_bg_color"],
            fg=self.theme["text_color"],
            wraplength=420,
            justify="left",
            anchor="w",
        ).pack(fill=tk.BOTH, expand=True, padx=16, pady=(20, 10))

        button_row = tk.Frame(dialog, bg=self.theme["log_bg_color"])
        button_row.pack(fill=tk.X, padx=16, pady=(0, 14))

        def on_yes():
            result["value"] = True
            dialog.destroy()

        def on_no():
            result["value"] = False
            dialog.destroy()

        yes_button = self._create_rounded_button(
            button_row,
            text="Yes",
            command=on_yes,
            width=68,
            height=30,
            font_spec=("Segoe UI", 10, "bold"),
            enabled=True,
        )
        yes_button["widget"].pack(side=tk.RIGHT, padx=(6, 0))

        no_button = self._create_rounded_button(
            button_row,
            text="No",
            command=on_no,
            width=68,
            height=30,
            font_spec=("Segoe UI", 10, "bold"),
            enabled=True,
        )
        no_button["widget"].pack(side=tk.RIGHT)

        dialog.wait_window()
        return result["value"]

    def _create_overlay_backdrop(self):
        if self.overlay_backdrop and self.overlay_backdrop.winfo_exists():
            return

        self.overlay_backdrop = tk.Toplevel(self.root)
        self.overlay_backdrop.overrideredirect(True)
        self.overlay_backdrop.transient(self.root)
        self.overlay_backdrop.configure(bg="#000000")
        self.overlay_backdrop.attributes("-alpha", 0.25)

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        self.overlay_backdrop.geometry(f"{root_w}x{root_h}+{root_x}+{root_y}")
        self.overlay_backdrop.lift(self.root)

    def _destroy_overlay_backdrop(self):
        if self.overlay_backdrop and self.overlay_backdrop.winfo_exists():
            self.overlay_backdrop.destroy()
        self.overlay_backdrop = None

    def _open_logs(self):
        """Open in-app logs overlay with ping spikes history."""
        try:
            self._show_logs_overlay()
        except Exception as e:
            if self.toast_manager:
                self.toast_manager.show(
                    f"Unable to open logs overlay: {e}", toast_type="error"
                )
            self.logger.exception("Failed to open logs window")

    def _show_logs_overlay(self):
        """Render logs in a stable modal window."""
        if self.logs_window and self.logs_window.winfo_exists():
            self.logs_window.lift()
            self.logs_window.focus_force()
            self._refresh_logs_overlay()
            return

        self._close_logs_overlay(cancel_toast=True)
        overlay_width = 620
        overlay_height = 520

        self.logs_window = tk.Toplevel(self.root)
        self.logs_window.withdraw()
        self.logs_window.title("Ping spikes logs")
        self.logs_window.transient(self.root)
        self.logs_window.resizable(True, True)
        self.logs_window.minsize(540, 420)
        self.logs_window.configure(bg=self.theme["bg_color"])
        self.logs_window.protocol("WM_DELETE_WINDOW", self._close_logs_overlay)

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        pos_x = root_x + max(0, (root_w - overlay_width) // 2)
        pos_y = root_y + max(0, (root_h - overlay_height) // 2)
        self.logs_window.geometry(f"{overlay_width}x{overlay_height}+{pos_x}+{pos_y}")

        self.logs_overlay_frame = tk.Frame(
            self.logs_window,
            bg=self.theme["log_bg_color"],
            highlightbackground=self.theme["accent_color"],
            highlightthickness=1,
            bd=0,
        )
        self.logs_overlay_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self.logs_text_widget = scrolledtext.ScrolledText(
            self.logs_overlay_frame,
            font=("Consolas", 10),
            bg=self.theme["log_bg_color"],
            fg=self.theme["log_text_color"],
            insertbackground=self.theme["log_text_color"],
            selectbackground="#b3d7ff",
            wrap=tk.NONE,
            state=tk.DISABLED,
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.logs_text_widget.pack(fill=tk.BOTH, expand=True)

        self.last_logs_content = None
        self.logs_window.update_idletasks()
        self.logs_window.deiconify()
        self.logs_window.lift()
        self.logs_window.focus_force()
        self.logs_window.after_idle(self.logs_window.focus_force)
        self.logger.info("Logs window opened")
        self._refresh_logs_overlay()

    def _get_logs_file_path(self):
        """Resolve ping spikes file path."""
        return os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            PING_SPIKES_FILE,
        )

    def _refresh_logs_overlay(self):
        """Reload logs text and schedule periodic refresh while overlay is open."""
        if not (self.logs_window and self.logs_window.winfo_exists()):
            return

        log_path = self._get_logs_file_path()
        if not os.path.exists(log_path):
            content = "No ping spikes recorded yet."
        else:
            try:
                content = self._read_logs_text(log_path).strip()
                if not content:
                    content = "No ping spikes recorded yet."
            except Exception as error:
                content = f"Unable to read logs: {error}"
                if self.toast_manager:
                    self.toast_manager.show(
                        "Could not read ping spikes file.", toast_type="error"
                    )

        if self.logs_text_widget and self.logs_text_widget.winfo_exists():
            if content != self.last_logs_content:
                self.logs_text_widget.config(state=tk.NORMAL)
                self.logs_text_widget.delete(1.0, tk.END)
                self.logs_text_widget.insert(tk.END, content + "\n")
                self.logs_text_widget.see(tk.END)
                self.logs_text_widget.config(state=tk.DISABLED)
                self.last_logs_content = content

        self.logs_refresh_job = self.root.after(1500, self._refresh_logs_overlay)

    def _close_logs_overlay(self, cancel_toast=False):
        """Close logs overlay and stop auto-refresh."""
        if self.logs_refresh_job:
            try:
                self.root.after_cancel(self.logs_refresh_job)
            except Exception:
                pass
            self.logs_refresh_job = None

        if self.logs_overlay_frame and self.logs_overlay_frame.winfo_exists():
            self.logs_overlay_frame.destroy()
        self.logs_overlay_frame = None
        self.logs_text_widget = None

        if self.logs_window and self.logs_window.winfo_exists():
            self.logs_window.destroy()
        self.logs_window = None
        self.logger.info("Logs window closed")

    def _read_logs_text(self, log_path):
        """Read logs using tolerant encoding fallbacks for legacy files."""
        encodings = ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "cp1250", "cp1252")
        for encoding in encodings:
            try:
                with open(log_path, "r", encoding=encoding) as file_handle:
                    return file_handle.read()
            except UnicodeDecodeError:
                continue

        with open(log_path, "r", encoding="utf-8", errors="replace") as file_handle:
            return file_handle.read()

    def _show_reset_menu(self, event):
        """Show reset menu"""
        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Reset current tab", command=self._reset_current_tab)
        menu.add_command(label="Reset all tabs", command=self._reset_all_tabs)
        menu.post(event.x_root, event.y_root)

    def _reset_current_tab(self):
        """Reset current tab stats"""
        current_tab = self.notebook.select()
        if not current_tab:
            return
        tab_index = self.notebook.index(current_tab)
        server_name = list(self.servers.keys())[tab_index]

        self.app.ping_service.reset_stats(server_name)
        self.app.reset_server_statistics(server_name)
        # Clear text widget
        if server_name in self.server_tabs:
            self.server_tabs[server_name].reset()
        self.logger.info("Reset current tab: %s", server_name)

    def _reset_all_tabs(self):
        """Reset all tabs stats"""
        self.app.ping_service.reset_all_stats()
        self.app.reset_all_statistics()
        for server_name in self.server_tabs:
            self.server_tabs[server_name].reset()
        self.logger.info("Reset all tabs")

    def _create_notebook(self, parent):
        """Create the tabbed notebook interface"""
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Bind tab change event to auto-scroll to bottom
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook.bind("<Motion>", self._on_notebook_motion)
        self.notebook.bind("<Leave>", self._on_notebook_leave)

        # Configure ttk styles for modern dark theme
        self._configure_notebook_style()

    def _configure_notebook_style(self):
        """Configure the notebook styling"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=self.theme["bg_color"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=self.theme["inactive_tab_bg"],
            foreground=self.theme["inactive_tab_fg"],
            padding=[10, 5],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.theme["bg_color"])],
            foreground=[("selected", self.theme["accent_color"])],
        )
        style.configure("TFrame", background=self.theme["bg_color"])

    def _create_server_tabs(self):
        """Create a tab for each server"""
        for server_name in self.servers.keys():
            self._create_server_tab(server_name)

    def _create_server_tab(self, server_name):
        """Create a tab for a specific server"""
        ip_address = self.servers[server_name]

        # Create ServerTab instance
        tab = ServerTab(
            self.notebook,
            server_name,
            ip_address,
            self.theme,
            self.animation_utils,
            self.root,
            lambda: self.app.running,
        )

        # Store reference
        self.server_tabs[server_name] = tab

    def update_display(self, server_name, formatted_result, statistics=None):
        """Update the display for a specific server"""
        if server_name in self.server_tabs:
            self.server_tabs[server_name].update_display(formatted_result, statistics)

    def _start_gui_update_thread(self):
        """Start the GUI update thread"""

        def update_gui_periodically():
            """Update GUI from the main thread"""
            try:
                if self.app.ping_service:
                    max_batch = 200
                    processed = 0
                    while (
                        processed < max_batch
                        and not self.app.ping_service.ping_queue.empty()
                    ):
                        result = self.app.ping_service.ping_queue.get_nowait()
                        self.app._process_ping_result(result)
                        processed += 1
            except:
                pass
            finally:
                # Schedule next update from main thread
                if self.root and self.app.running:
                    self.root.after(50, update_gui_periodically)

        # Start the periodic updates from the main thread
        if self.root:
            self.root.after(50, update_gui_periodically)

    def rebuild_server_tabs(self, servers):
        """Recreate server tabs after configuration changes."""
        self.servers = dict(servers)
        for tab_id in self.notebook.tabs():
            self.notebook.forget(tab_id)
        self.server_tabs.clear()
        self._create_server_tabs()

    def clear_server_tab_displays(self):
        """Clear existing tab text without rebuilding tabs."""
        for tab in self.server_tabs.values():
            tab.reset()

    def begin_bulk_update_visual(self):
        """Cover metrics area while runtime config is being applied."""
        if not self.notebook or not self.notebook.winfo_exists():
            return

        if (
            self.bulk_update_overlay is None
            or not self.bulk_update_overlay.winfo_exists()
        ):
            self.bulk_update_overlay = tk.Frame(
                self.notebook,
                bg=self.theme["log_bg_color"],
                bd=0,
                highlightthickness=0,
            )

        self.bulk_update_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.bulk_update_overlay.lift()
        self.root.update_idletasks()

    def end_bulk_update_visual(self):
        """Remove metrics-area update cover."""
        if self.bulk_update_overlay and self.bulk_update_overlay.winfo_exists():
            self.bulk_update_overlay.place_forget()

    def apply_close_behavior(self, close_to_tray):
        """Apply current close button behavior from settings."""
        if close_to_tray:
            self.root.protocol("WM_DELETE_WINDOW", self.app.hide_window)
        else:
            self.root.protocol("WM_DELETE_WINDOW", self.app.quit)

    def _on_tab_changed(self, event):
        """Auto-scroll to bottom when switching tabs"""
        try:
            current_tab = self.notebook.select()
            if not current_tab:
                return

            tab_index = self.notebook.index(current_tab)
            server_name = list(self.servers.keys())[tab_index]

            if server_name in self.server_tabs:
                text_widget = self.server_tabs[server_name].text_widget
                text_widget.see(tk.END)
        except Exception:
            pass

    def _on_notebook_motion(self, event):
        """Show pointer cursor when hovering inactive tabs."""
        try:
            tab_index = self.notebook.index(f"@{event.x},{event.y}")
            current_tab = self.notebook.select()
            current_index = self.notebook.index(current_tab) if current_tab else -1
            if tab_index != current_index:
                self.notebook.configure(cursor="hand2")
            else:
                self.notebook.configure(cursor="")
        except tk.TclError:
            self.notebook.configure(cursor="")

    def _on_notebook_leave(self, _event):
        """Reset notebook cursor on leave."""
        self.notebook.configure(cursor="")

    def show(self):
        """Show the main window"""
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.window_visible = True
            self.logger.info("Main window shown")

    def hide(self):
        """Hide the main window"""
        if self.root:
            self.root.withdraw()
            self.window_visible = False
            self.logger.info("Main window hidden")

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
            self._destroy_config_window(force=True)
            self._close_logs_overlay(cancel_toast=True)
            self.root.destroy()

    def _handle_tk_exception(self, exc_type, exc_value, exc_traceback):
        """Capture Tk callback exceptions into app logging."""
        self.logger.exception(
            "Tk callback exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
