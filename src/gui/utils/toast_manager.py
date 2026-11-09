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

        toast_width = 252
        toast_height = 52
        margin_x = 16
        margin_y = 16

        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()

        stack_index = len(self.active_toasts)
        target_x = max(4, root_width - toast_width - margin_x)
        start_x = root_width + 24
        toast_y = min(
            margin_y + (stack_index * (toast_height + 8)),
            max(4, root_height - toast_height - margin_y),
        )

        toast_frame = tk.Frame(
            self.root,
            bg=selected["border"],
            bd=0,
            highlightthickness=0,
        )
        toast_frame.place(x=start_x, y=toast_y, width=toast_width, height=toast_height)
        toast_frame.lift()

        inner = tk.Frame(
            toast_frame,
            bg=selected["bg"],
            bd=0,
            highlightthickness=0,
        )
        inner.place(x=1, y=1, width=toast_width - 2, height=toast_height - 2)

        icon_label = tk.Label(
            inner,
            text=selected["icon"],
            bg=selected["border"],
            fg=selected["fg"],
            font=("Segoe UI", 9, "bold"),
            width=2,
        )
        icon_label.place(x=8, y=14)

        message_label = tk.Label(
            inner,
            text=message,
            bg=selected["bg"],
            fg=selected["fg"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify="left",
            wraplength=toast_width - 58,
        )
        message_label.place(x=38, y=8, width=toast_width - 46, height=toast_height - 14)

        toast_state = {
            "window": toast_frame,
            "x": start_x,
            "target_x": target_x,
            "y": toast_y,
            "width": toast_width,
            "height": toast_height,
            "start_x": start_x,
        }
        self.active_toasts.append(toast_state)
        toast = toast_frame

        def slide_in():
            if not toast.winfo_exists():
                return
            current_x = toast_state["x"]
            if current_x > toast_state["target_x"]:
                current_x = max(toast_state["target_x"], current_x - 16)
                toast_state["x"] = current_x
                toast.place(x=current_x, y=toast_state["y"])
                toast.after(10, slide_in)
            else:
                toast.after(duration_ms, slide_out)

        def slide_out():
            if not toast.winfo_exists():
                return
            current_x = toast_state["x"]
            final_x = toast_state["start_x"]
            if current_x < final_x:
                current_x = min(final_x, current_x + 16)
                toast_state["x"] = current_x
                toast.place(x=current_x, y=toast_state["y"])
                toast.after(10, slide_out)
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
        base_y = 16

        for index, toast_state in enumerate(self.active_toasts):
            toast = toast_state["window"]
            if not toast.winfo_exists():
                continue
            new_y = base_y + (index * (toast_state["height"] + 8))
            toast_state["y"] = new_y
            toast.place(x=toast_state["x"], y=new_y)

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
