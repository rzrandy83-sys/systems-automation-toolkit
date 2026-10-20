#!/usr/bin/env python3
"""
govee_widget.py

Small always-on-top Tkinter widget showing live status of the Govee
Permanent Lights Pro (H706A) via the local LAN API. Monitor only - no
controls yet. Matches the style/placement of the existing fireplace
status widget.

Discovers the device once at startup and caches its IP; re-discovers
automatically if the cached IP stops responding (handles DHCP lease
changes without needing a restart).
"""

import tkinter as tk
import threading
import time
from datetime import datetime

import govee_control as gc
import govee_scheduler as sched
from govee_schedule_editor import ScheduleEditor

POLL_INTERVAL_SECONDS = 10
RETRY_DISCOVERY_AFTER_FAILURES = 3  # consecutive failed status queries before re-discovering

# Colors matching the Fireplace Status widget
BG_COLOR = "#1e1e1e"
FG_COLOR = "#e0e0e0"
ACCENT_ON = "#4fc3f7"
ACCENT_OFF = "#666666"
FONT_TITLE = ("Sans", 15, "bold")
FONT_BODY = ("Sans", 13)
FONT_SMALL = ("Sans", 9)


class GoveeWidget:
    def __init__(self, root):
        self.root = root
        self.device_ip = None
        self.consecutive_failures = 0

        root.title("Govee Lights")
        root.configure(bg=BG_COLOR)
        # Positioned directly beneath the Fireplace Status widget, same left
        # edge (x=1086), flush under its bottom edge (y=210 based on the
        # screenshot). Drag to adjust if needed - it will NOT snap back.
        root.geometry("+1086+210")

        # Same approach as the working Fireplace Status widget: "utility"
        # type hides it from the taskbar without forcing always-on-top,
        # unlike overrideredirect which Cinnamon stacks above everything.
        root.attributes("-type", "utility")

        self.frame = tk.Frame(root, bg=BG_COLOR, padx=18, pady=14)
        self.frame.pack()

        self.title_label = tk.Label(
            self.frame, text="Permanent Lights Pro", font=FONT_TITLE,
            bg=BG_COLOR, fg=FG_COLOR
        )
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w")

        self.status_dot = tk.Label(
            self.frame, text="●", font=("Sans", 10),
            bg=BG_COLOR, fg=ACCENT_OFF
        )
        self.status_dot.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.status_text = tk.Label(
            self.frame, text="Checking...", font=FONT_BODY,
            bg=BG_COLOR, fg=FG_COLOR
        )
        self.status_text.grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(4, 0))

        self.brightness_label = tk.Label(
            self.frame, text="", font=FONT_BODY, bg=BG_COLOR, fg=FG_COLOR
        )
        self.brightness_label.grid(row=2, column=0, columnspan=2, sticky="w")

        self.color_label = tk.Label(
            self.frame, text="", font=FONT_BODY, bg=BG_COLOR, fg=FG_COLOR
        )
        self.color_label.grid(row=3, column=0, columnspan=2, sticky="w")

        self.last_updated_label = tk.Label(
            self.frame, text="", font=FONT_SMALL, bg=BG_COLOR, fg="#777777"
        )
        self.last_updated_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.next_change_label = tk.Label(
            self.frame, text="", font=FONT_SMALL, bg=BG_COLOR, fg="#999999",
            wraplength=220, justify="left"
        )
        self.next_change_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.edit_schedule_btn = tk.Button(
            self.frame, text="Edit Schedule", font=FONT_SMALL,
            command=self._open_schedule_editor,
            bg="#2a2a2a", fg=FG_COLOR, activebackground="#3a3a3a",
            borderwidth=0, padx=8, pady=3
        )
        self.edit_schedule_btn.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Allow dragging the widget since it has no title bar
        self.frame.bind("<Button-1>", self._start_move)
        self.frame.bind("<B1-Motion>", self._do_move)
        self.title_label.bind("<Button-1>", self._start_move)
        self.title_label.bind("<B1-Motion>", self._do_move)

        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        # Background scheduler: fires schedule rules against the light
        self._scheduler_thread = sched.SchedulerThread(
            get_device_ip_callback=lambda: self.device_ip,
            on_fire_callback=lambda rule: self.root.after(0, self._refresh_next_change)
        )
        self._scheduler_thread.start()

        self._refresh_next_change()
        # Keep the "next change" display current even if nothing fires
        # (e.g. countdown naturally rolls forward after a rule's time passes)
        self._schedule_periodic_refresh()

    def _open_schedule_editor(self):
        ScheduleEditor(self.root, on_save_callback=self._refresh_next_change)

    def _refresh_next_change(self):
        rules = sched.load_schedule()
        next_rule, next_time = sched.get_next_scheduled_change(rules)
        if next_rule is None:
            self.next_change_label.config(text="No schedule set")
        else:
            desc = sched.describe_rule(next_rule)
            time_str = next_time.strftime("%a %H:%M")
            self.next_change_label.config(text=f"Next: {desc} ({time_str})")

    def _schedule_periodic_refresh(self):
        self._refresh_next_change()
        self.root.after(60000, self._schedule_periodic_refresh)

    def _start_move(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_move(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def _poll_loop(self):
        """Background thread: discover device, then poll status forever."""
        while True:
            if self.device_ip is None:
                self._set_status_text("Discovering...")
                devices = gc.discover()
                if devices:
                    self.device_ip = devices[0].ip
                    self.consecutive_failures = 0
                else:
                    self._set_status_text("Device not found")
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

            status = gc.get_status(self.device_ip)
            if status is None:
                self.consecutive_failures += 1
                if self.consecutive_failures >= RETRY_DISCOVERY_AFTER_FAILURES:
                    # IP may have changed (DHCP lease); force re-discovery next loop
                    self.device_ip = None
                    self.consecutive_failures = 0
                else:
                    self._set_status_text("No response")
            else:
                self.consecutive_failures = 0
                self._update_display(status)

            time.sleep(POLL_INTERVAL_SECONDS)

    def _set_status_text(self, text):
        self.root.after(0, lambda: self.status_text.config(text=text))

    def _update_display(self, status):
        on = status.get("onOff") == 1
        brightness = status.get("brightness", "?")
        color = status.get("color", {})
        kelvin = status.get("colorTemInKelvin", 0)

        def update():
            self.status_dot.config(fg=ACCENT_ON if on else ACCENT_OFF)
            self.status_text.config(text="ON" if on else "OFF")
            self.brightness_label.config(text=f"Brightness: {brightness}%")

            if kelvin and kelvin > 0:
                self.color_label.config(text=f"Color temp: {kelvin}K")
            else:
                r, g, b = color.get("r", 0), color.get("g", 0), color.get("b", 0)
                self.color_label.config(text=f"Color: RGB({r},{g},{b})")

            self.last_updated_label.config(text=f"Updated {time.strftime('%H:%M:%S')}")

        self.root.after(0, update)


if __name__ == "__main__":
    root = tk.Tk()
    app = GoveeWidget(root)
    root.mainloop()
