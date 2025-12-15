"""
Main GUI window for the Ping Monitor application.
"""

import tkinter as tk
from tkinter import ttk, font, Menu
import os
import threading
from PIL import Image, ImageTk, ImageDraw
from src.core.config import THEME, BACKGROUND_FILE, DEVIATIONS_FILE, ANIMATION_SETTINGS
import src.core.config as config_module
from src.gui.components.server_tab import ServerTab
from src.gui.dialogs.first_run import FirstRunDialog
from src.gui.utils.animations import AnimationUtils


class MainWindow:
    """Main application window with tabbed interface"""

    def __init__(self, servers, app_instance):
        self.servers = servers
        self.app = app_instance
        self.theme = THEME

        # GUI elements
        self.root = None
        self.notebook = None  # Tabbed interface
        self.server_tabs = {}  # One ServerTab per server
        self.window_visible = False
        self.bg_image_original = None
        self.bg_image_tk = None
        self.bg_label = None

        # Utilities
        self.animation_utils = AnimationUtils(THEME, ANIMATION_SETTINGS)

        # State flags
        self.updates_paused = False

        self._setup_gui()

        # Check for first run configuration
        # If first run (hidden window), show dialog sooner
        delay = 100 if config_module.CLOSE_TO_TRAY is None else 1000
        self.root.after(delay, self._check_close_behavior)

    def _check_close_behavior(self):
        """Check if close behavior is configured, if not ask user"""
        if config_module.CLOSE_TO_TRAY is None:
            # Pause updates while dialog is open
            self.updates_paused = True

            def on_complete():
                # Show main window now that configuration is done
                self.root.deiconify()
                self.root.state("zoomed")
                self.window_visible = True
                self.updates_paused = False
                # Start background services now that we are configured
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
                print(f"Error loading background image: {e}")
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
                print(f"Error setting window icon: {e}")

        # Configure window visibility based on first run status
        if config_module.CLOSE_TO_TRAY is None:
            self.root.withdraw()  # Hide main window for first run dialog
            self.window_visible = False
        else:
            self.root.state("zoomed")  # Start maximized
            self.window_visible = True

        # Configure window close button - will be updated by _check_close_behavior
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        # Configure custom fonts
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
        self.root.option_add("*Font", default_font)

        self._create_main_layout()
        self._create_server_tabs()
        # Note: _start_gui_update_thread is now called after configuration/startup

    def _resize_background(self, event):
        """Resize background image to fit window"""
        if not self.bg_image_original or not self.bg_label:
            return

        # Only resize if dimensions changed significantly to avoid lag
        if (
            hasattr(self, "_last_bg_size")
            and abs(self._last_bg_size[0] - event.width) < 10
            and abs(self._last_bg_size[1] - event.height) < 10
        ):
            return

        self._last_bg_size = (event.width, event.height)

        # Resize image using LANCZOS for quality
        # Use cover mode (crop if needed)
        img_w, img_h = self.bg_image_original.size
        target_w, target_h = event.width, event.height

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
            print(f"Non-critical error setting app ID: {e}")

    def _create_main_layout(self):
        """Create the main layout with toolbar, content, and footer"""
        # Main container frame (transparent-ish look by not filling everything)
        # We use place to put it on top of the background label
        # Using a frame with padding to show background around it

        # Toolbar at the top (transparent background to show image?)
        # Tkinter frames are opaque. We'll make a frame that spans the top.
        # To make it look good, we might want it to be semi-transparent or just small buttons floating.
        # Let's make a toolbar frame.

        self.main_container = tk.Frame(self.root, bg=self.theme["bg_color"])
        # Place it with margins so background is visible
        self.main_container.place(relx=0.05, rely=0.05, relwidth=0.9, relheight=0.9)

        # Toolbar
        self._create_toolbar(self.main_container)

        # Create notebook (tabbed interface)
        self._create_notebook(self.main_container)

    def _create_toolbar(self, parent):
        """Create the toolbar with icon buttons"""
        toolbar_frame = tk.Frame(parent, bg=self.theme["bg_color"])
        # Reduced top margin to match bottom margin (pady=5)
        toolbar_frame.pack(fill=tk.X, pady=5, padx=5)

        # Create icons
        self.icons = {
            "config": self._draw_icon("config"),
            "logs": self._draw_icon("logs"),
            "reset": self._draw_icon("reset"),
        }

        # Config Button - Reduced left margin
        btn_config = tk.Label(
            toolbar_frame,
            image=self.icons["config"],
            bg=self.theme["bg_color"],
            cursor="hand2",
        )
        btn_config.pack(side=tk.LEFT, padx=(5, 2))
        btn_config.bind("<Button-1>", lambda e: self._open_config())
        self._create_tooltip(btn_config, "Open config")

        # Logs Button - Reduced gap
        btn_logs = tk.Label(
            toolbar_frame,
            image=self.icons["logs"],
            bg=self.theme["bg_color"],
            cursor="hand2",
        )
        btn_logs.pack(side=tk.LEFT, padx=2)
        btn_logs.bind("<Button-1>", lambda e: self._open_logs())
        self._create_tooltip(btn_logs, "Open logs")

        # Reset Button - Reduced gap
        btn_reset = tk.Label(
            toolbar_frame,
            image=self.icons["reset"],
            bg=self.theme["bg_color"],
            cursor="hand2",
        )
        btn_reset.pack(side=tk.LEFT, padx=2)
        btn_reset.bind("<Button-1>", lambda e: self._show_reset_menu(e))
        self._create_tooltip(btn_reset, "Reset metrics")

    def _draw_icon(self, name, size=24):
        """Draw simple icons using PIL"""
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = self.theme["accent_color"]  # Use accent color for icons

        if name == "config":
            # Gear ⚙️
            # Center hole
            draw.ellipse([8, 8, size - 8, size - 8], outline=color, width=2)
            # Teeth
            import math

            center = size / 2
            outer_radius = size / 2 - 1
            inner_radius = size / 2 - 4

            for i in range(0, 360, 45):
                angle_rad = math.radians(i)
                # Draw tooth
                x1 = center + inner_radius * math.cos(angle_rad - 0.2)
                y1 = center + inner_radius * math.sin(angle_rad - 0.2)
                x2 = center + outer_radius * math.cos(angle_rad - 0.2)
                y2 = center + outer_radius * math.sin(angle_rad - 0.2)
                x3 = center + outer_radius * math.cos(angle_rad + 0.2)
                y3 = center + outer_radius * math.sin(angle_rad + 0.2)
                x4 = center + inner_radius * math.cos(angle_rad + 0.2)
                y4 = center + inner_radius * math.sin(angle_rad + 0.2)

                draw.polygon([(x1, y1), (x2, y2), (x3, y3), (x4, y4)], fill=color)

        elif name == "logs":
            # Document 📃
            # Paper body
            draw.polygon(
                [
                    (5, 2),
                    (size - 9, 2),
                    (size - 5, 6),
                    (size - 5, size - 2),
                    (5, size - 2),
                ],
                outline=color,
                width=2,
            )
            # Folded corner
            draw.line(
                [(size - 9, 2), (size - 9, 6), (size - 5, 6)], fill=color, width=1
            )
            # Lines
            draw.line([(9, 8), (size - 9, 8)], fill=color, width=2)
            draw.line([(9, 12), (size - 9, 12)], fill=color, width=2)
            draw.line([(9, 16), (size - 9, 16)], fill=color, width=2)

        elif name == "reset":
            # Recycle ♻️
            # Top arc
            draw.arc([4, 4, size - 4, size - 4], 30, 150, fill=color, width=2)
            # Bottom arc
            draw.arc([4, 4, size - 4, size - 4], 210, 330, fill=color, width=2)

            # Arrow 1 (Top, pointing left)
            draw.arc([4, 4, size - 4, size - 4], 20, 160, fill=color, width=2)
            # Arrowhead at 160 deg (left)
            # Left side, slightly up
            draw.polygon(
                [2, size / 2 - 4, 2, size / 2 + 2, 8, size / 2 - 1], fill=color
            )

            # Arrow 2 (Bottom, pointing right)
            draw.arc([4, 4, size - 4, size - 4], 200, 340, fill=color, width=2)
            # Arrowhead at 340 deg (right)
            # Right side, slightly down
            draw.polygon(
                [
                    size - 2,
                    size / 2 + 4,
                    size - 2,
                    size / 2 - 2,
                    size - 8,
                    size / 2 + 1,
                ],
                fill=color,
            )

        return ImageTk.PhotoImage(img)

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
            print(f"Error opening config: {e}")

    def _open_logs(self):
        """Open logs file"""
        try:
            log_path = os.path.join(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                ),
                DEVIATIONS_FILE,
            )
            if os.path.exists(log_path):
                os.startfile(log_path)
        except Exception as e:
            print(f"Error opening logs: {e}")

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
        # Clear text widget
        if server_name in self.server_tabs:
            self.server_tabs[server_name].reset()

    def _reset_all_tabs(self):
        """Reset all tabs stats"""
        self.app.ping_service.reset_all_stats()
        for server_name in self.server_tabs:
            self.server_tabs[server_name].reset()

    def _create_notebook(self, parent):
        """Create the tabbed notebook interface"""
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Bind tab change event to auto-scroll to bottom
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

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
            # Get the currently selected tab
            current_tab = self.notebook.select()
            if not current_tab:
                return

            # Find which server this tab belongs to
            tab_index = self.notebook.index(current_tab)
            server_name = list(self.servers.keys())[tab_index]

            # Get the text widget for this server
            if server_name in self.server_tabs:
                text_widget = self.server_tabs[server_name].text_widget
                # Scroll to the bottom
                text_widget.see(tk.END)
        except Exception as e:
            # Fail silently if something goes wrong
            pass

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
