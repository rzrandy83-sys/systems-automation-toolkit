#!/usr/bin/env python3
# UPS Monitor widget - Mint-Desktop Dell
# CyberPower EC850LCD via NUT (usbhid-ups), section: cyberpower-ec850lcd
import json
import os
import re
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime

UPS_NAME = "cyberpower-ec850lcd@localhost"
UPS_LABEL = "CyberPower EC850LCD"
NOMINAL_WATTS = 450
POLL_MS = 2000
POS_X = 1061
POS_Y = 482
STATE_DIR = os.path.expanduser("~/.config/ups_monitor")
STATE_FILE = os.path.join(STATE_DIR, "sag_state.json")
DEDUPE_SECONDS = 10

BG = "#1e1e1e"
FG = "#d0d0d0"
DIM = "#808080"
GREEN = "#4caf50"
ORANGE = "#ff9800"
RED = "#f44336"
BLUE = "#4fc3f7"
FONT = ("DejaVu Sans Mono", 10)
FONT_B = ("DejaVu Sans Mono", 10, "bold")
FONT_H = ("DejaVu Sans Mono", 11, "bold")

STATUS_TEXT = {
    "OL": "ONLINE", "OB": "ON BATTERY", "LB": "LOW BATTERY",
    "CHRG": "CHARGING", "DISCHRG": "DISCHARGING", "RB": "REPLACE BATTERY",
    "OVER": "OVERLOAD", "FSD": "FORCED SHUTDOWN", "BYPASS": "BYPASS",
    "CAL": "CALIBRATING", "OFF": "OFF",
}

RE_ON_BATT = re.compile(r"UPS \S+ on battery", re.I)
RE_ON_LINE = re.compile(r"UPS \S+ on line power", re.I)


def read_ups():
    try:
        res = subprocess.run(["upsc", UPS_NAME], capture_output=True,
                             text=True, timeout=5)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    data = {}
    for line in res.stdout.splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            data[k.strip()] = v.strip()
    return data or None


def parse_ts(line):
    try:
        ts = datetime.fromisoformat(line.split()[0])
        return ts.astimezone().replace(tzinfo=None)
    except Exception:
        return datetime.now()


class SagTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.count = 0
        self.last_sag = None
        self.last_duration = None
        self.on_batt_since = None
        os.makedirs(STATE_DIR, exist_ok=True)
        self._load()
        self._rebuild_from_journal()
        threading.Thread(target=self._tail, daemon=True).start()

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
            if s.get("last_sag"):
                self.last_sag = datetime.fromisoformat(s["last_sag"])
            self.last_duration = s.get("last_duration")
            if s.get("date") == self.today:
                self.count = int(s.get("count", 0))
        except Exception:
            pass

    def _save(self):
        s = {
            "date": self.today,
            "count": self.count,
            "last_sag": self.last_sag.isoformat() if self.last_sag else None,
            "last_duration": self.last_duration,
        }
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(s, f)
            os.replace(tmp, STATE_FILE)
        except Exception:
            pass

    def _rebuild_from_journal(self):
        # Catch events that happened while the widget was not running
        try:
            res = subprocess.run(
                ["journalctl", "-u", "nut-monitor.service", "--since", "today",
                 "-o", "short-iso", "--no-pager"],
                capture_output=True, text=True, timeout=15)
        except Exception:
            return
        jcount = 0
        jlast = None
        for line in res.stdout.splitlines():
            if RE_ON_BATT.search(line):
                jcount += 1
                jlast = parse_ts(line)
        with self.lock:
            if jcount > self.count:
                self.count = jcount
            if jlast and (self.last_sag is None or jlast > self.last_sag):
                self.last_sag = jlast
                self.last_duration = None
            self._save()

    def _tail(self):
        while True:
            try:
                proc = subprocess.Popen(
                    ["journalctl", "-u", "nut-monitor.service", "-f", "-n", "0",
                     "-o", "short-iso"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in proc.stdout:
                    if RE_ON_BATT.search(line):
                        self.mark_on_battery(parse_ts(line))
                    elif RE_ON_LINE.search(line):
                        self.mark_on_line(parse_ts(line))
            except Exception:
                pass
            time.sleep(5)

    def check_midnight(self):
        now = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            if now != self.today:
                self.today = now
                self.count = 0
                self._save()

    def mark_on_battery(self, ts):
        self.check_midnight()
        with self.lock:
            if self.on_batt_since is not None:
                return
            if self.last_sag and abs((ts - self.last_sag).total_seconds()) < DEDUPE_SECONDS:
                return
            self.count += 1
            self.last_sag = ts
            self.last_duration = None
            self.on_batt_since = ts
            self._save()

    def mark_on_line(self, ts):
        with self.lock:
            if self.on_batt_since is None:
                return
            self.last_duration = max(0, int((ts - self.on_batt_since).total_seconds()))
            self.on_batt_since = None
            self._save()

    def snapshot(self):
        with self.lock:
            return self.count, self.last_sag, self.last_duration, self.on_batt_since


def fmt_runtime(sec):
    try:
        sec = int(float(sec))
    except Exception:
        return "--"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm" % (h, m)
    return "%dm %02ds" % (m, s)


class UPSWidget:
    def __init__(self, root):
        self.root = root
        self.tracker = SagTracker()
        root.title("UPS Monitor")
        root.configure(bg=BG)
        root.geometry("+%d+%d" % (POS_X, POS_Y))
        root.resizable(False, False)

        frame = tk.Frame(root, bg=BG, padx=12, pady=10)
        frame.pack()

        tk.Label(frame, text="UPS - " + UPS_LABEL, font=FONT_H, fg=BLUE,
                 bg=BG).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.vals = {}
        rows = ["Status", "Battery", "Runtime", "Load", "Input", "Output",
                "Battery V", "Transfer"]
        r = 1
        for name in rows:
            tk.Label(frame, text=name + ":", font=FONT, fg=DIM, bg=BG,
                     anchor="w", width=12).grid(row=r, column=0, sticky="w")
            if name == "Battery":
                cell = tk.Frame(frame, bg=BG)
                cell.grid(row=r, column=1, sticky="w")
                self.bar = tk.Canvas(cell, width=120, height=10, bg="#333333",
                                     highlightthickness=0)
                self.bar.pack(side="left", padx=(0, 6))
                lbl = tk.Label(cell, text="--", font=FONT_B, fg=FG, bg=BG)
                lbl.pack(side="left")
            else:
                lbl = tk.Label(frame, text="--", font=FONT_B, fg=FG, bg=BG,
                               anchor="w")
                lbl.grid(row=r, column=1, sticky="w")
            self.vals[name] = lbl
            r += 1

        tk.Label(frame, text="POWER EVENTS", font=FONT_H, fg=BLUE,
                 bg=BG).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 2))
        r += 1
        for name in ["Sags Today", "Last Sag"]:
            tk.Label(frame, text=name + ":", font=FONT, fg=DIM, bg=BG,
                     anchor="w", width=12).grid(row=r, column=0, sticky="w")
            lbl = tk.Label(frame, text="--", font=FONT_B, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=r, column=1, sticky="w")
            self.vals[name] = lbl
            r += 1

        self.updated = tk.Label(frame, text="", font=("DejaVu Sans Mono", 8),
                                fg=DIM, bg=BG)
        self.updated.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.refresh()
        self.root.after(1500, self._set_below)

    def _find_wid(self):
        try:
            out = subprocess.run(["wmctrl", "-l"], capture_output=True,
                                 text=True, timeout=3).stdout
        except Exception:
            return None
        for line in out.splitlines():
            if line.rstrip().endswith("UPS Monitor"):
                return line.split()[0]
        return None

    def _set_below(self):
        wid = self._find_wid()
        if not wid:
            self.root.after(1000, self._set_below)
            return
        q = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        try:
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b",
                            "add,skip_taskbar,skip_pager"], **q)
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,below"], **q)
            subprocess.run(["xprop", "-id", wid, "-f", "_MOTIF_WM_HINTS", "32c",
                            "-set", "_MOTIF_WM_HINTS", "0x2, 0x0, 0x0, 0x0, 0x0"], **q)
        except Exception:
            pass
        self.root.after(3000, self._set_below)

    def _draw_bar(self, pct, color):
        self.bar.delete("all")
        try:
            w = int(120 * max(0.0, min(100.0, float(pct))) / 100)
        except Exception:
            w = 0
        if w > 0:
            self.bar.create_rectangle(0, 0, w, 10, fill=color, width=0)

    def refresh(self):
        self.tracker.check_midnight()
        d = read_ups()
        if d is None:
            self.vals["Status"].config(text="NO COMM", fg=RED)
            for k in ["Battery", "Runtime", "Load", "Input", "Output",
                      "Battery V", "Transfer"]:
                self.vals[k].config(text="--", fg=FG)
            self._draw_bar(0, RED)
        else:
            flags = d.get("ups.status", "").split()
            text = " + ".join(STATUS_TEXT.get(f, f) for f in flags) or "UNKNOWN"
            if "OB" in flags or "LB" in flags or "FSD" in flags or "OVER" in flags:
                color = RED if ("LB" in flags or "FSD" in flags) else ORANGE
            elif "OL" in flags:
                color = GREEN
            else:
                color = ORANGE
            self.vals["Status"].config(text=text, fg=color)

            now = datetime.now()
            if "OB" in flags:
                self.tracker.mark_on_battery(now)
            elif "OL" in flags:
                self.tracker.mark_on_line(now)

            chg = d.get("battery.charge", "--")
            try:
                c = float(chg)
                bcol = GREEN if c >= 50 else (ORANGE if c >= 20 else RED)
            except Exception:
                bcol = DIM
            self._draw_bar(chg if chg != "--" else 0, bcol)
            self.vals["Battery"].config(text="%s%%" % chg)

            self.vals["Runtime"].config(text=fmt_runtime(d.get("battery.runtime")))

            load = d.get("ups.load")
            try:
                lw = int(round(float(load) * NOMINAL_WATTS / 100.0))
                lcol = GREEN if float(load) < 60 else (ORANGE if float(load) < 85 else RED)
                self.vals["Load"].config(text="%s%% (%d W)" % (load, lw), fg=lcol)
            except Exception:
                self.vals["Load"].config(text="--", fg=FG)

            iv = d.get("input.voltage", "--")
            try:
                lo = float(d.get("input.transfer.low", 0))
                ivc = ORANGE if lo and float(iv) < lo + 6 else FG
            except Exception:
                ivc = FG
            self.vals["Input"].config(text="%s V" % iv, fg=ivc)
            self.vals["Output"].config(text="%s V" % d.get("output.voltage", "--"))
            self.vals["Battery V"].config(text="%s V" % d.get("battery.voltage", "--"))
            self.vals["Transfer"].config(text="%s - %s V" % (
                d.get("input.transfer.low", "--"), d.get("input.transfer.high", "--")))

        count, last, dur, since = self.tracker.snapshot()
        self.vals["Sags Today"].config(text=str(count), fg=ORANGE if count else GREEN)
        if since is not None:
            self.vals["Last Sag"].config(
                text=since.strftime("%Y-%m-%d %H:%M:%S") + " (active)", fg=RED)
        elif last is None:
            self.vals["Last Sag"].config(text="never", fg=DIM)
        else:
            extra = " (%ds)" % dur if dur is not None else ""
            self.vals["Last Sag"].config(
                text=last.strftime("%Y-%m-%d %H:%M:%S") + extra, fg=FG)

        self.updated.config(text="Updated " + datetime.now().strftime("%H:%M:%S"))
        self.root.after(POLL_MS, self.refresh)


def main():
    root = tk.Tk()
    UPSWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
