"""
Fireplace status widget
------------------------
A small always-on-top desktop window showing the current switch state
and temperature, pulled from the Flask webhook server's /status endpoint.

Requirements:
    Tkinter (usually pre-installed with Python on Mint; if not:
    sudo apt install python3-tk)

Run (with shelly_webhook.py already running in another terminal):
    python fireplace_widget.py
"""

import tkinter as tk
import requests as http
from datetime import datetime

STATUS_URL = "http://192.168.1.101:5000/status"
REFRESH_MS = 5000  # how often to poll the local Flask server, in milliseconds

root = tk.Tk()
root.title("Fireplace Status")
root.geometry("260x140+1085+25")
root.configure(bg="#1e1e1e")
root.attributes("-type", "utility")  # hides from taskbar on most Linux WMs, without forcing always-on-top

switch_label = tk.Label(root, text="Switch: --", font=("Arial", 16, "bold"),
                         fg="white", bg="#1e1e1e")
switch_label.pack(pady=(15, 5))

temp_label = tk.Label(root, text="Temp: --", font=("Arial", 16, "bold"),
                       fg="white", bg="#1e1e1e")
temp_label.pack(pady=5)

updated_label = tk.Label(root, text="Last updated: --", font=("Arial", 9),
                          fg="#999999", bg="#1e1e1e")
updated_label.pack(pady=(10, 0))


def refresh():
    try:
        r = http.get(STATUS_URL, timeout=3)
        data = r.json()

        switch_on = data.get("switch_on")
        temp_c = data.get("temperature_c")
        last_updated = data.get("last_updated")

        if switch_on is True:
            switch_label.config(text="Switch: ON", fg="#4caf50")
        elif switch_on is False:
            switch_label.config(text="Switch: OFF", fg="#f44336")
        else:
            switch_label.config(text="Switch: --", fg="white")

        if temp_c is not None:
            temp_label.config(text=f"Temp: {temp_c:.1f}\u00b0C")
        else:
            temp_label.config(text="Temp: --")

        if last_updated:
            dt = datetime.fromisoformat(last_updated)
            updated_label.config(text=f"Last updated: {dt.strftime('%H:%M:%S')}")

    except Exception as e:
        switch_label.config(text="Switch: ERROR", fg="orange")
        temp_label.config(text="Temp: ERROR")
        updated_label.config(text=str(e)[:40])

    root.after(REFRESH_MS, refresh)


refresh()
root.mainloop()
