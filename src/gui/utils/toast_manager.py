"""Toast notification utilities for the Ping Monitor GUI."""

import tkinter as tk


class ToastManager:
    """Shows animated slide-in toast notifications."""

    def __init__(self, root):
        self.root = root
        self.active_toasts = []

    def show(self, message, toast_type="success", duration_ms=3000):
        """Display a toast in the upper-right corner."""
        colors = {
            "success": {
                "bg": "#1f8f4e",
                "fg": "#ffffff",
                "border": "#32b86d",
                "icon": "✓",
            },
            "warning": {
                "bg": "#8a6a00",
                "fg": "#ffffff",
                "border": "#cc9a00",
                "icon": "!",
            },
            "error": {
                "bg": "#8f2d2d",
                "fg": "#ffffff",
                "border": "#d44f4f",
                "icon": "✕",
            },
            "info": {
                "bg": "#1e4f8a",
                "fg": "#ffffff",
                "border": "#4f86d4",
                "icon": "i",
            },
        }
        selected = colors.get(toast_type, colors["info"])

        self.root.update_idletasks()

        toast_width = 360
        toast_height = 74
        margin_x = 16
        margin_y = 16
        radius = 14

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        app_right = root_x + root_width
        app_bottom = root_y + root_height
        max_target_x = screen_width - toast_width - margin_x
        max_target_y = screen_height - toast_height - margin_y

        stack_index = len(self.active_toasts)
        toast_y = min(
            root_y + margin_y + (stack_index * (toast_height + 8)),
            max_target_y,
        )

        target_x = min(app_right - toast_width - margin_x, max_target_x)
        target_x = max(margin_x, target_x)

        # Start just outside the app edge (not outside monitor), so slide-in is visible in windowed mode.
        start_x = min(target_x + 64, max_target_x)

        toast = tk.Toplevel(self.root)
        toast.wm_overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.geometry(f"{toast_width}x{toast_height}+{start_x}+{toast_y}")
        toast.configure(bg="#ff00ff")
        toast.wm_attributes("-transparentcolor", "#ff00ff")

        canvas = tk.Canvas(
            toast,
            width=toast_width,
            height=toast_height,
            bg="#ff00ff",
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        self._draw_rounded_rect(
            canvas,
            1,
            1,
            toast_width - 2,
            toast_height - 2,
            radius=radius,
            fill=selected["bg"],
            outline=selected["border"],
            width=1,
        )

        icon_center_x = 32
        icon_center_y = toast_height // 2
        canvas.create_oval(
            icon_center_x - 13,
            icon_center_y - 13,
            icon_center_x + 13,
            icon_center_y + 13,
            fill=selected["border"],
            outline="",
        )
        canvas.create_text(
            icon_center_x,
            icon_center_y,
            text=selected["icon"],
            fill=selected["fg"],
            font=("Segoe UI", 12, "bold"),
        )

        canvas.create_text(
            58,
            toast_height // 2,
            text=message,
            fill=selected["fg"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
            width=toast_width - 76,
        )

        toast_state = {
            "window": toast,
            "x": start_x,
            "target_x": target_x,
            "y": toast_y,
            "width": toast_width,
            "height": toast_height,
            "app_right": app_right,
        }
        self.active_toasts.append(toast_state)

        def slide_in():
            if not toast.winfo_exists():
                return
            current_x = toast_state["x"]
            if current_x > toast_state["target_x"]:
                current_x = max(toast_state["target_x"], current_x - 12)
                toast_state["x"] = current_x
                toast.geometry(
                    f"{toast_state['width']}x{toast_state['height']}+{current_x}+{toast_state['y']}"
                )
                toast.after(12, slide_in)
            else:
                toast.after(duration_ms, slide_out)

        def slide_out():
            if not toast.winfo_exists():
                return
            current_x = toast_state["x"]
            # Slide slightly right but keep toast within the app bounds.
            final_x = min(
                toast_state["target_x"] + 24,
                toast_state["app_right"] - toast_state["width"] + 8,
            )
            if current_x < final_x:
                current_x = min(final_x, current_x + 12)
                toast_state["x"] = current_x
                toast.geometry(
                    f"{toast_state['width']}x{toast_state['height']}+{current_x}+{toast_state['y']}"
                )
                toast.after(12, slide_out)
            else:
                self._destroy_toast(toast_state)

        slide_in()

    def _destroy_toast(self, toast_state):
        """Destroy toast and compact stacked toasts."""
        toast = toast_state["window"]
        if toast.winfo_exists():
            toast.destroy()

        self.active_toasts = [
            item for item in self.active_toasts if item != toast_state
        ]
        self._reposition_active_toasts()

    def _reposition_active_toasts(self):
        """Re-stack active toasts after one disappears."""
        self.root.update_idletasks()
        base_y = self.root.winfo_rooty() + 16

        for index, toast_state in enumerate(self.active_toasts):
            toast = toast_state["window"]
            if not toast.winfo_exists():
                continue
            new_y = base_y + (index * (toast_state["height"] + 8))
            toast_state["y"] = new_y
            toast.geometry(
                f"{toast_state['width']}x{toast_state['height']}+{toast_state['x']}+{new_y}"
            )

    def _draw_rounded_rect(
        self,
        canvas,
        x1,
        y1,
        x2,
        y2,
        radius=12,
        fill="#1f1f1f",
        outline="#ffffff",
        width=1,
    ):
        """Draw a rounded rectangle on a canvas."""
        radius = max(2, min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2)))

        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        canvas.create_polygon(
            points,
            smooth=True,
            fill=fill,
            outline=outline,
            width=width,
            splinesteps=30,
        )
