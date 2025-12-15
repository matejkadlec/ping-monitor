import tkinter as tk
from tkinter import messagebox
import os
import src.core.config as config_module


class FirstRunDialog:
    """Dialog for first run configuration"""

    def __init__(self, root, theme, app_instance, on_complete_callback):
        self.root = root
        self.theme = theme
        self.app = app_instance
        self.on_complete = on_complete_callback

    def show(self):
        """Show the configuration dialog"""
        # Create a custom dialog window
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()  # Hide initially
        dialog.title("First Run Configuration")
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg=self.theme["bg_color"])

        # Content
        tk.Label(
            dialog,
            text="Choose Close Button Behavior",
            font=("Segoe UI", 14, "bold"),
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
        ).pack(pady=(20, 10))

        tk.Label(
            dialog,
            text="What should happen when you click the X button?\nYou can change this later in config.py",
            font=("Segoe UI", 10),
            bg=self.theme["bg_color"],
            fg=self.theme["text_color"],
            justify=tk.CENTER,
        ).pack(pady=(0, 15))

        def set_behavior(minimize):
            # Update config file
            try:
                config_path = os.path.join(
                    os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    ),
                    "core",
                    "config.py",
                )

                with open(config_path, "r") as f:
                    lines = f.readlines()

                with open(config_path, "w") as f:
                    for line in lines:
                        if line.strip().startswith("CLOSE_TO_TRAY"):
                            f.write(f"CLOSE_TO_TRAY = {str(minimize)}\n")
                        else:
                            f.write(line)

                # Update runtime config
                config_module.CLOSE_TO_TRAY = minimize

                # Update protocol
                if minimize:
                    self.root.protocol("WM_DELETE_WINDOW", self.app.hide_window)
                else:
                    self.root.protocol("WM_DELETE_WINDOW", self.app.quit)

                dialog.destroy()

                # Notify completion
                if self.on_complete:
                    self.on_complete()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {e}")

        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.theme["bg_color"])
        btn_frame.pack(pady=(0, 20))

        tk.Button(
            btn_frame,
            text="Minimize to Tray",
            command=lambda: set_behavior(True),
            bg=self.theme["inactive_tab_bg"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 10),
            padx=15,
            pady=5,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame,
            text="Exit Application",
            command=lambda: set_behavior(False),
            bg=self.theme["inactive_tab_bg"],
            fg=self.theme["text_color"],
            font=("Segoe UI", 10),
            padx=15,
            pady=5,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=10)

        # Close app if dialog is closed without choice
        def on_dialog_close():
            self.app.quit()

        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)

        # Calculate geometry to fit content exactly
        dialog.update_idletasks()
        width = 400
        height = dialog.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()

        # Force focus
        dialog.focus_force()

        self.root.wait_window(dialog)
