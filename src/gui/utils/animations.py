import tkinter as tk


class AnimationUtils:
    """Utility class for UI animations"""

    def __init__(self, theme, animation_settings):
        self.theme = theme
        self.enabled = animation_settings.get("enabled", True)
        self.duration = animation_settings.get("duration", 800)
        self.steps = animation_settings.get("steps", 8)

    def fade_highlight(self, root, text_widget, tag, steps_left, app_running_check):
        """Fade out the highlight of new entries"""
        if steps_left <= 0 or not app_running_check():
            try:
                # Set to normal background color and remove the tag
                text_widget.tag_configure(tag, background=self.theme["log_bg_color"])
                text_widget.tag_delete(tag)
            except tk.TclError:
                pass  # Widget might be destroyed
            return

        try:
            # Calculate interpolation between highlight color and log background color
            progress = steps_left / self.steps  # 1.0 to 0.0

            # Extract RGB values from highlight color
            highlight_r = int(self.theme["bg_highlight_color"][1:3], 16)
            highlight_g = int(self.theme["bg_highlight_color"][3:5], 16)
            highlight_b = int(self.theme["bg_highlight_color"][5:7], 16)

            # Extract RGB values from log background color
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
            step_time = self.duration // self.steps
            root.after(
                step_time,
                lambda: self.fade_highlight(
                    root, text_widget, tag, steps_left - 1, app_running_check
                ),
            )
        except tk.TclError:
            pass  # Widget might be destroyed

    def smooth_scroll_to_end(self, root, text_widget, app_running_check):
        """Smoothly scroll to the end of the text widget"""
        try:
            # Get current view
            first, last = text_widget.yview()

            # If we're already at the bottom, no need to animate
            if last >= 0.99:
                text_widget.see(tk.END)
                return

            # Otherwise smoothly scroll
            self.animate_scroll(
                root, text_widget, first, 1.0, self.steps, app_running_check
            )
        except tk.TclError:
            pass  # Widget might be destroyed

    def animate_scroll(
        self, root, text_widget, start_pos, end_pos, steps_left, app_running_check
    ):
        """Animate scrolling from start_pos to end_pos in steps"""
        if steps_left <= 0 or not app_running_check():
            try:
                text_widget.see(tk.END)  # Ensure we end at the bottom
            except tk.TclError:
                pass
            return

        try:
            # Calculate intermediate position
            progress = (self.steps - steps_left) / self.steps
            pos = start_pos + ((end_pos - start_pos) * progress)
            text_widget.yview_moveto(pos)

            # Schedule next animation step
            step_time = 20  # milliseconds between steps (smoother)
            root.after(
                step_time,
                lambda: self.animate_scroll(
                    root,
                    text_widget,
                    start_pos,
                    end_pos,
                    steps_left - 1,
                    app_running_check,
                ),
            )
        except tk.TclError:
            pass  # Widget might be destroyed
