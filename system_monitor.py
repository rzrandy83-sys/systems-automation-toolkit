#!/usr/bin/env python3
"""
System Monitor Widget for Linux Mint (Dell Mini - Mint-Desktop)
"""

import tkinter as tk
import subprocess
import threading
import time
import datetime
import platform
import os
import re
import json
import urllib.request

# ---------- Config ----------
NETWORK_INTERFACE = "eno1"
DISK_DEVICE = "/dev/sda"
DISK_PARTITION = "/"
WAN_IP_CHECK_URL = "https://icanhazip.com"
WAN_IP_REFRESH_SECONDS = 300
UPDATE_INTERVAL_MS = 1000
POSITION_FILE = os.path.expanduser("~/.config/monitor/position.json")

# Weather config
WEATHER_CONFIG_FILE = os.path.expanduser("~/.config/monitor/weather.json")

def load_owm_api_key():
    try:
        with open(WEATHER_CONFIG_FILE) as f:
            cfg = json.load(f)
        return cfg.get("api_key", "")
    except Exception:
        return ""

OWM_API_KEY = load_owm_api_key()
WEATHER_LAT = 51.19
WEATHER_LON = -114.47
WEATHER_UNITS = "metric"  # Celsius
WEATHER_REFRESH_SECONDS = 600  # 10 minutes
WEATHER_URL = (
    f"https://api.openweathermap.org/data/2.5/weather"
    f"?lat={WEATHER_LAT}&lon={WEATHER_LON}&appid={OWM_API_KEY}&units={WEATHER_UNITS}"
)

FONT_FAMILY = "DejaVu Sans Mono"
BG_COLOR = "#000000"
FG_GREEN = "#00ff66"
FG_WHITE = "#e8e8e8"
FG_DIM = "#4a4a4a"
FG_ORANGE = "#ff9d2f"
FG_RED = "#ff4444"
FG_CYAN = "#33ccff"

# ---------- Helpers ----------

def run_cmd(cmd, timeout=3):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.readline().split()[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        return f"{hours}h {minutes}m"
    except Exception:
        return "N/A"


def get_process_count():
    try:
        out = run_cmd("ps -e --no-headers | wc -l")
        return out if out else "N/A"
    except Exception:
        return "N/A"


def get_mint_version():
    try:
        with open("/etc/linuxmint/info") as f:
            content = f.read()
        match = re.search(r'RELEASE=(.+)', content)
        codename = re.search(r'CODENAME=(.+)', content)
        version = match.group(1).strip() if match else "?"
        cname = codename.group(1).strip() if codename else ""
        return f"Mint {version} ({cname})" if cname else f"Mint {version}"
    except Exception:
        return platform.platform()


def get_kernel():
    return platform.release()


def get_cpu_freq():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "MHz" in line:
                    mhz = float(line.split(":")[1].strip())
                    return f"{mhz/1000:.2f}GHz"
    except Exception:
        pass
    return "N/A"


def get_cpu_temps():
    out = run_cmd("sensors")
    package_temp = None
    core_temps = []
    for line in out.splitlines():
        if "Package id 0" in line:
            m = re.search(r'\+([\d.]+)', line)
            if m:
                package_temp = float(m.group(1))
        elif re.match(r'\s*Core \d+:', line):
            m = re.search(r'\+([\d.]+)', line)
            if m:
                core_temps.append(float(m.group(1)))
    return package_temp, core_temps


def get_cpu_usage():
    try:
        with open("/proc/stat") as f:
            lines = f.readlines()
        cores = []
        for line in lines:
            if re.match(r'cpu\d+', line):
                parts = line.split()
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                iowait = int(parts[5])
                total = user + nice + system + idle + iowait
                cores.append((total, idle))
        return cores
    except Exception:
        return []


def get_ram():
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        info = {}
        for line in lines:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]
                info[key] = int(val)
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", 0)
        used = total - available
        total_gb = total / 1024 / 1024
        used_gb = used / 1024 / 1024
        pct = (used / total * 100) if total else 0
        return used_gb, total_gb, pct
    except Exception:
        return 0, 0, 0


def get_disk_usage():
    try:
        out = run_cmd(f"df -BG {DISK_PARTITION} --output=used,size,pcent")
        lines = out.splitlines()
        if len(lines) >= 2:
            used, size, pcent = lines[1].split()
            used = used.replace("G", "")
            size = size.replace("G", "")
            pcent = pcent.replace("%", "")
            return used, size, pcent
    except Exception:
        pass
    return "N/A", "N/A", "N/A"


def get_disk_health():
    try:
        out = run_cmd(f"sudo -n smartctl -H {DISK_DEVICE}")
        if "PASSED" in out:
            return "PASSED"
        elif "FAILED" in out:
            return "FAILED"
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def get_lan_ip():
    out = run_cmd(f"ip -4 addr show {NETWORK_INTERFACE}")
    m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
    return m.group(1) if m else "N/A"


def get_network_bytes():
    try:
        with open(f"/sys/class/net/{NETWORK_INTERFACE}/statistics/rx_bytes") as f:
            rx = int(f.read().strip())
        with open(f"/sys/class/net/{NETWORK_INTERFACE}/statistics/tx_bytes") as f:
            tx = int(f.read().strip())
        return rx, tx
    except Exception:
        return 0, 0


def format_bytes(b):
    b = float(b)
    for unit in ["B", "K", "M", "G", "T"]:
        if b < 1024:
            return f"{b:.1f}{unit}" if unit != "B" else f"{b:.0f}{unit}"
        b /= 1024
    return f"{b:.1f}P"


def read_rapl_energy():
    out = run_cmd("sudo -n /usr/local/bin/read_rapl.sh")
    try:
        return int(out.strip())
    except Exception:
        return None



def get_rkhunter_status():
    """Check rkhunter log for warnings from the most recent scan."""
    try:
        with open("/var/log/rkhunter.log") as f:
            lines = f.readlines()
        # Find warnings from the last scan (after last "Starting test")
        last_start = 0
        for i, line in enumerate(lines):
            if "Starting test name" in line and "rootkits" in line:
                last_start = i
        warnings = []
        i = last_start
        while i < len(lines):
            line = lines[i]
            if "Warning:" in line:
                header = line.split("Warning:")[-1].strip()
                details = []
                j = i + 1
                # Collect indented continuation lines (e.g. "File:", "Segment ID:", etc.)
                while j < len(lines):
                    stripped = lines[j].rstrip("\n")
                    # Strip the leading "[HH:MM:SS]" timestamp if present
                    content_part = stripped.split("]", 1)[-1] if stripped.startswith("[") else stripped
                    if content_part.strip() == "" or not content_part.startswith(" " * 8):
                        break
                    details.append(content_part.strip())
                    j += 1
                if details:
                    warnings.append(header + " -- " + " | ".join(details))
                else:
                    warnings.append(header)
                i = j
            else:
                i += 1
        return len(warnings), warnings
    except Exception:
        return -1, []


def get_weather():
    """Fetch current weather from OpenWeatherMap."""
    if not OWM_API_KEY:
        return {"error": f"No API key found in {WEATHER_CONFIG_FILE}"}
    try:
        with urllib.request.urlopen(WEATHER_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        main = data.get("main", {})
        wind = data.get("wind", {})
        weather_arr = data.get("weather", [{}])
        condition = weather_arr[0].get("main", "N/A") if weather_arr else "N/A"
        description = weather_arr[0].get("description", "").title() if weather_arr else ""
        return {
            "temp": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "humidity": main.get("humidity"),
            "condition": condition,
            "description": description,
            "wind_speed": wind.get("speed"),
            "error": None,
        }
    except Exception as e:
        return {"error": str(e)}

# ---------- Background data collector ----------

class DataCollector:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self._last_cpu_stats = None
        self._last_rapl_energy = None
        self._last_rapl_time = None
        self._last_rx = None
        self._last_tx = None
        self._last_net_time = None
        self._total_rx = 0
        self._total_tx = 0
        self._wan_ip = "checking..."
        self._last_wan_check = 0
        self._weather = {"error": "loading..."}
        self._last_weather_check = 0
        self._running = True

    def start(self):
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def stop(self):
        self._running = False

    def _update_wan_ip(self):
        now = time.time()
        if now - self._last_wan_check < WAN_IP_REFRESH_SECONDS and self._wan_ip != "checking...":
            return
        try:
            with urllib.request.urlopen(WAN_IP_CHECK_URL, timeout=3) as resp:
                self._wan_ip = resp.read().decode().strip()
        except Exception:
            pass
        self._last_wan_check = now

    def _update_weather(self):
        now = time.time()
        if now - self._last_weather_check < WEATHER_REFRESH_SECONDS and self._weather.get("error") != "loading...":
            return
        self._weather = get_weather()
        self._last_weather_check = now

    def _update_power(self):
        energy = read_rapl_energy()
        now = time.time()
        watts = None
        if energy is not None and self._last_rapl_energy is not None:
            dt = now - self._last_rapl_time
            denergy = energy - self._last_rapl_energy
            if denergy < 0:
                denergy = 0
            if dt > 0:
                watts = (denergy / 1_000_000) / dt
        if energy is not None:
            self._last_rapl_energy = energy
            self._last_rapl_time = now
        return watts

    def _update_network_speed(self):
        rx, tx = get_network_bytes()
        now = time.time()
        rx_speed = tx_speed = 0
        if self._last_rx is not None:
            dt = now - self._last_net_time
            if dt > 0:
                drx = rx - self._last_rx
                dtx = tx - self._last_tx
                if drx >= 0:
                    rx_speed = drx / dt
                    self._total_rx += drx
                if dtx >= 0:
                    tx_speed = dtx / dt
                    self._total_tx += dtx
        self._last_rx = rx
        self._last_tx = tx
        self._last_net_time = now
        return rx_speed, tx_speed

    def _loop(self):
        while self._running:
            try:
                pkg_temp, core_temps = get_cpu_temps()
                cur_stats = get_cpu_usage()
                core_usage = []
                if self._last_cpu_stats and len(cur_stats) == len(self._last_cpu_stats):
                    for (ct, ci), (lt, li) in zip(cur_stats, self._last_cpu_stats):
                        dt = ct - lt
                        di = ci - li
                        pct = (1 - di / dt) * 100 if dt > 0 else 0
                        core_usage.append(max(0, min(100, pct)))
                self._last_cpu_stats = cur_stats
                used_ram, total_ram, ram_pct = get_ram()
                disk_used, disk_size, disk_pct = get_disk_usage()
                watts = self._update_power()
                down_speed, up_speed = self._update_network_speed()
                self._update_wan_ip()
                self._update_weather()

                snapshot = {
                    "time": datetime.datetime.now().strftime("%I:%M:%S %p"),
                    "date": datetime.datetime.now().strftime("%A, %B %d %Y"),
                    "mint_version": get_mint_version(),
                    "kernel": get_kernel(),
                    "uptime": get_uptime(),
                    "processes": get_process_count(),
                    "cpu_freq": get_cpu_freq(),
                    "pkg_temp": pkg_temp,
                    "core_temps": core_temps,
                    "core_usage": core_usage,
                    "power_watts": watts,
                    "ram_used": used_ram,
                    "ram_total": total_ram,
                    "ram_pct": ram_pct,
                    "disk_used": disk_used,
                    "disk_size": disk_size,
                    "disk_pct": disk_pct,
                    "disk_health": get_disk_health(),
                    "interface": NETWORK_INTERFACE,
                    "lan_ip": get_lan_ip(),
                    "wan_ip": self._wan_ip,
                    "down_speed": format_bytes(down_speed) + "/s",
                    "up_speed": format_bytes(up_speed) + "/s",
                    "total_down": format_bytes(self._total_rx),
                    "total_up": format_bytes(self._total_tx),
                    "rkhunter": get_rkhunter_status(),
                    "weather": self._weather,
                }

                with self.lock:
                    self.data = snapshot
            except Exception as e:
                with self.lock:
                    self.data["error"] = str(e)

            time.sleep(1)

    def get(self):
        with self.lock:
            return dict(self.data)


# ---------- GUI ----------

class SystemMonitorWidget:
    def __init__(self, root, collector):
        self.root = root
        self.collector = collector

        root.title("System Monitor")
        root.configure(bg=BG_COLOR)
        root.attributes("-topmost", False)
        root.attributes("-alpha", 0.92)

        WIDTH = 560
        HEIGHT = 860
        screen_w = root.winfo_screenwidth()
        margin = 20
        default_x = screen_w - WIDTH - margin
        default_y = margin
        x, y = self._load_position(default_x, default_y)
        root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

        self.frame = tk.Frame(root, bg=BG_COLOR, padx=18, pady=14)
        self.frame.pack(fill="both", expand=True)

        self.clock_label = tk.Label(
            self.frame, text="--:--:--", font=(FONT_FAMILY, 34, "bold"),
            fg=FG_GREEN, bg=BG_COLOR, anchor="w"
        )
        self.clock_label.pack(fill="x")

        self.section_labels = {}
        self._add_section("system", "SYSTEM")
        self._add_section("weather", "WEATHER")
        self._add_section("cpu", "CPU")
        self._add_section("ram", "MEMORY")
        self._add_section("disk", "DISK")
        self._add_section("network", "NETWORK")
        self._add_section("security", "SECURITY")

        self.frame.bind("<ButtonPress-1>", self._start_move)
        self.frame.bind("<B1-Motion>", self._on_move)
        self.frame.bind("<ButtonRelease-1>", self._on_release)
        self.clock_label.bind("<ButtonPress-1>", self._start_move)
        self.clock_label.bind("<B1-Motion>", self._on_move)
        self.clock_label.bind("<ButtonRelease-1>", self._on_release)

        self._refresh()
        self.root.after(500, self._set_below_loop)

    def _set_below_loop(self):
        self._set_below()
        self.root.after(3000, self._set_below_loop)

    def _set_below(self):
        try:
            win_id = hex(self.root.winfo_id())
            subprocess.run(["wmctrl", "-i", "-r", win_id, "-b", "add,skip_taskbar,skip_pager,below"], check=False)
            subprocess.run(["xprop", "-id", win_id, "-f", "_MOTIF_WM_HINTS", "32c",
                            "-set", "_MOTIF_WM_HINTS", "0x2, 0x0, 0x0, 0x0, 0x0"], check=False)
        except Exception:
            pass

    def _add_section(self, key, title):
        header = tk.Label(
            self.frame, text=title, font=(FONT_FAMILY, 13, "bold"),
            fg=FG_CYAN, bg=BG_COLOR, anchor="w"
        )
        header.pack(fill="x", pady=(10, 3))
        body = tk.Label(
            self.frame, text="", font=(FONT_FAMILY, 13),
            fg=FG_WHITE, bg=BG_COLOR, anchor="w", justify="left",
            wraplength=520
        )
        body.pack(fill="x")
        self.section_labels[key] = body

    def _load_position(self, default_x, default_y):
        try:
            with open(POSITION_FILE) as f:
                pos = json.load(f)
            return pos.get("x", default_x), pos.get("y", default_y)
        except Exception:
            return default_x, default_y

    def _save_position(self):
        try:
            os.makedirs(os.path.dirname(POSITION_FILE), exist_ok=True)
            with open(POSITION_FILE, "w") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()}, f)
        except Exception:
            pass

    def _start_move(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_move(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        self._save_position()

    def _color_for_temp(self, temp):
        if temp is None:
            return FG_WHITE
        if temp >= 80:
            return FG_RED
        if temp >= 65:
            return FG_ORANGE
        return FG_GREEN

    def _color_for_pct(self, pct):
        try:
            pct = float(pct)
        except Exception:
            return FG_WHITE
        if pct >= 90:
            return FG_RED
        if pct >= 70:
            return FG_ORANGE
        return FG_GREEN

    def _make_bar(self, pct, width=10):
        filled = int(pct / 100 * width)
        filled = max(0, min(width, filled))
        return "[" + "\u2588" * filled + "\u2591" * (width - filled) + "] " + f"{pct:3.0f}%"

    def _refresh(self):
        data = self.collector.get()
        if data:
            self.clock_label.config(text=data.get("time", "--:--:--"))

            self.section_labels["system"].config(text=(
                f"{data.get('mint_version','N/A')}\n"
                f"Kernel: {data.get('kernel','N/A')}\n"
                f"Uptime: {data.get('uptime','N/A')}\n"
                f"Processes: {data.get('processes','N/A')}"
            ))

            weather = data.get("weather", {})
            if weather.get("error"):
                if weather.get("error") == "loading...":
                    weather_text = "Loading weather..."
                else:
                    weather_text = "Weather unavailable"
                self.section_labels["weather"].config(text=weather_text, fg=FG_DIM)
            else:
                temp = weather.get("temp")
                feels = weather.get("feels_like")
                humidity = weather.get("humidity")
                wind = weather.get("wind_speed")
                condition = weather.get("condition", "N/A")
                description = weather.get("description", "")
                temp_str = f"{temp:.1f}C" if temp is not None else "N/A"
                feels_str = f"{feels:.1f}C" if feels is not None else "N/A"
                wind_str = f"{wind:.1f} m/s" if wind is not None else "N/A"
                weather_text = (
                    f"{description or condition}  {temp_str}  (feels {feels_str})\n"
                    f"Humidity: {humidity}%   Wind: {wind_str}"
                )
                self.section_labels["weather"].config(text=weather_text, fg=FG_WHITE)

            pkg_temp = data.get("pkg_temp")
            core_temps = data.get("core_temps", [])
            core_usage = data.get("core_usage", [])
            watts = data.get("power_watts")
            watts_str = f"{watts:.1f}W" if watts is not None else "N/A"
            pkg_str = f"{pkg_temp:.1f}C" if pkg_temp is not None else "N/A"

            core_lines = ""
            for i, temp in enumerate(core_temps):
                usage = core_usage[i] if i < len(core_usage) else 0
                core_lines += f"C{i} {self._make_bar(usage)} {temp:.0f}C\n"

            self.section_labels["cpu"].config(text=(
                f"Freq: {data.get('cpu_freq','N/A')}  Pkg: {pkg_str}  Pwr: {watts_str}\n"
                + core_lines.rstrip()
            ), fg=self._color_for_temp(pkg_temp))

            ram_pct = data.get("ram_pct", 0)
            self.section_labels["ram"].config(
                text=f"{data.get('ram_used',0):.2f}G / {data.get('ram_total',0):.2f}G  ({ram_pct:.0f}%)",
                fg=self._color_for_pct(ram_pct)
            )

            disk_health = data.get("disk_health", "UNKNOWN")
            self.section_labels["disk"].config(text=(
                f"Usage: {data.get('disk_used','N/A')}G / {data.get('disk_size','N/A')}G "
                f"({data.get('disk_pct','N/A')}%)\n"
                f"Health: {disk_health}"
            ), fg=self._color_for_pct(data.get('disk_pct', 0)))
            if disk_health != "PASSED":
                self.section_labels["disk"].config(fg=FG_RED)

            self.section_labels["network"].config(text=(
                f"Interface: {data.get('interface','N/A')}\n"
                f"LAN IP: {data.get('lan_ip','N/A')}\n"
                f"WAN IP: {data.get('wan_ip','N/A')}\n"
                f"Down: {data.get('down_speed','N/A')}   Up: {data.get('up_speed','N/A')}\n"
                f"Total Down: {data.get('total_down','N/A')}   Total Up: {data.get('total_up','N/A')}"
            ))

            rk_count, rk_warnings = data.get("rkhunter", (0, []))
            if rk_count == -1:
                rk_text = "rkhunter log unavailable"
                rk_color = FG_DIM
            elif rk_count == 0:
                rk_text = "rkhunter: CLEAN"
                rk_color = FG_GREEN
            else:
                rk_text = f"rkhunter: {rk_count} WARNING(S)\n" + "\n".join(rk_warnings[:3])
                rk_color = FG_RED
            self.section_labels["security"].config(text=rk_text, fg=rk_color)
        self.root.after(UPDATE_INTERVAL_MS, self._refresh)


def main():
    collector = DataCollector()
    collector.start()

    root = tk.Tk()
    app = SystemMonitorWidget(root, collector)

    def on_right_click(event):
        root.destroy()
    root.bind("<Button-3>", on_right_click)

    root.mainloop()


if __name__ == "__main__":
    main()
