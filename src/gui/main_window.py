"""
Main GUI window for the Ping Monitor application.
"""

import tkinter as tk
from tkinter import ttk, font, Menu, scrolledtext
import os
import logging
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
        self.overlay_backdrop_refresh_job = None
        self.last_logs_content = None

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
            if config_module.CLOSE_TO_TRAY:
                self.root.protocol("WM_DELETE_WINDOW", self.app.hide_window)
            else:
                self.root.protocol("WM_DELETE_WINDOW", self.app.quit)

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

    def _open_config(self):
        """Open config file"""
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "core",
                "config.py",
            )
            os.startfile(config_path)
        except Exception as e:
            self.logger.exception("Error opening config: %s", e)

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
        self.logs_window.lift()
        self.logs_window.focus_force()
        self.logs_window.after_idle(self.logs_window.focus_force)

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
            self._close_logs_overlay(cancel_toast=True)
            self.root.destroy()

    def _handle_tk_exception(self, exc_type, exc_value, exc_traceback):
        """Capture Tk callback exceptions into app logging."""
        self.logger.exception(
            "Tk callback exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
