#!/usr/bin/env python3
"""
ofs_status_view.py - OrionFieldStack LCD Live Status & Telemetry Display
Displays real-time communication & telemetry status matching the OrionFieldStack Web GUI design.

Sections:
  1. INDI STATUS (Server, Mount)
  2. TIME (Local, UTC, Time Source)
  3. GPS (Latitude, Longitude, Elevation, GPSD Status)
  4. ENVIRONMENT (Temperature, Humidity, Pressure, Dew Point, CPU Mount/RPi)
  5. FLASH Air (Connection Status, URL/IP)

Target: Raspberry Pi 5 + AE-ATM0130B3 (ST7789V2 240x240 IPS LCD)
"""

import os
import sys
import time
import math
import json
import signal
import select
import urllib.request
import urllib.error
import subprocess
import argparse
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Path resolution: allow importing st7789 from ofs_lcd directory
# ---------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
OFS_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..")) if os.path.basename(CURRENT_DIR) == "ofs_lcd" else CURRENT_DIR
OFS_LCD_DIR = os.path.join(OFS_ROOT, "ofs_lcd")
if OFS_LCD_DIR not in sys.path:
    sys.path.insert(0, OFS_LCD_DIR)

# ST7789 display hardware driver import
try:
    from st7789 import ST7789, stop_backlight_daemon
except ImportError:
    ST7789 = None
    stop_backlight_daemon = None

# ST7789 power management commands
ST7789_SLPIN = 0x10
ST7789_DISPOFF = 0x28

# Terminal raw/cbreak mode support
try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False

# ---------------------------------------------------------------------------
# Web OrionFieldStack Color Palette
# ---------------------------------------------------------------------------
COLOR_BG_DARK = (10, 14, 20)           # #0a0e14
COLOR_BG_CARD = (18, 25, 36)           # rgba(20, 26, 35, 0.85)
COLOR_BORDER_CARD = (40, 52, 68)       # subtle glass border
COLOR_BORDER_GOLD = (90, 75, 45)       # gold divider line
COLOR_ACCENT_GOLD = (201, 160, 99)     # #c9a063 (Section title & Slewing)
COLOR_ACCENT_BLUE = (58, 134, 255)     # #3a86ff (Tracking & Primary Accent)
COLOR_ACCENT_CYAN = (0, 240, 255)      # Cyan highlight
COLOR_ACCENT_GREEN = (0, 255, 136)     # #00ff88 (Connected & Active)
COLOR_ACCENT_RED = (255, 71, 87)       # #ff4757 (Disconnected & Alert)
COLOR_TEXT_MAIN = (225, 228, 232)      # #e1e4e8 (Main values)
COLOR_TEXT_DIM = (149, 157, 165)       # #959da5 (Labels)
COLOR_TEXT_MUTED = (90, 100, 115)      # Muted guide text

# Badge Color Sets: (background, border, text)
BADGE_STYLES = {
    "connected":    ((12, 45, 28), (0, 255, 136), (0, 255, 136)),
    "active":       ((12, 45, 28), (0, 255, 136), (0, 255, 136)),
    "disconnected": ((48, 16, 22), (255, 71, 87), (255, 71, 87)),
    "offline":      ((48, 16, 22), (255, 71, 87), (255, 71, 87)),
    "alert":        ((48, 16, 22), (255, 71, 87), (255, 71, 87)),
    "error":        ((48, 16, 22), (255, 71, 87), (255, 71, 87)),
    "tracking":     ((16, 36, 70), (58, 134, 255), (58, 134, 255)),
    "slewing":      ((48, 36, 16), (201, 160, 99), (201, 160, 99)),
    "idle":         ((28, 34, 44), (149, 157, 165), (149, 157, 165)),
    "unknown":      ((28, 34, 44), (120, 128, 138), (149, 157, 165)),
    "os":           ((28, 34, 44), (120, 128, 138), (149, 157, 165)),
    "gpsd":         ((12, 45, 28), (0, 255, 136), (0, 255, 136)),
}


# ---------------------------------------------------------------------------
# Font Management
# ---------------------------------------------------------------------------
_FONT_CACHE = {}

def get_font(size: int, bold: bool = False, mono: bool = False):
    """Retrieve cached TrueType font with fallbacks."""
    key = (size, bold, mono)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    if mono:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _FONT_CACHE[key] = font
                return font
            except Exception:
                pass

    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# ---------------------------------------------------------------------------
# Telemetry Data Acquisition
# ---------------------------------------------------------------------------
def fetch_telemetry(mock: bool = False, api_url: str = "http://localhost:8000/api/telemetry") -> dict:
    """
    Fetch telemetry data with multiple robust fallbacks:
      1. If mock=True, return simulated telemetry matching web data.
      2. Try HTTP GET from local ofs_gui API (fastest, lightweight).
      3. Try running ofs_link.py --get (direct telemetry capture).
      4. Fall back to safe default offline values.
    """
    if mock:
        now_dt = datetime.now()
        now_utc = datetime.now(timezone.utc)
        return {
            "indi_server": "CONNECTED",
            "status": "TRACKING",
            "ra_deg": 83.8102,
            "dec_deg": -5.3897,
            "ra_str": "05h35m14s",
            "dec_str": "-05°23'23\"",
            "side_of_pier": "EAST",
            "latitude": 34.6493,
            "longitude": 135.0015,
            "elevation": 54.0,
            "gpsd_status": "enable",
            "time_source": "gpsd",
            "timestamp_utc": now_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "iso_timestamp": now_dt.astimezone().isoformat(),
            "temp_c": 25.9,
            "humidity_pct": 55.6,
            "pressure_hPa": 1010.0,
            "dew_point_c": 17.0,
            "cpu_temp_mount_c": 38.0,
            "cpu_temp_rpi_c": 45.2,
            "flashair": "CONNECTED",
            "flashair_url": "http://192.168.50.200"
        }

    # Fallback 1: Try ofs_gui REST API
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "ofs_status_view/1.0"})
        with urllib.request.urlopen(req, timeout=0.8) as response:
            if response.status == 200:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
    except Exception:
        pass

    # Fallback 2: Execute ofs_link.py directly
    ofs_link_path = os.path.join(OFS_ROOT, "ofs_link", "ofs_link.py")
    if os.path.exists(ofs_link_path):
        try:
            # Use venv python if present
            venv_python = os.path.join(OFS_ROOT, "venv", "bin", "python")
            python_bin = venv_python if os.path.exists(venv_python) else sys.executable
            proc = subprocess.run(
                [python_bin, ofs_link_path, "--get"],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout.strip())
                data["flashair"] = "UNKNOWN"
                data["flashair_url"] = "http://192.168.50.200"
                return data
        except Exception:
            pass

    # Fallback 3: Return offline defaults
    now_dt = datetime.now()
    now_utc = datetime.now(timezone.utc)
    return {
        "indi_server": "DISCONNECTED",
        "status": "UNKNOWN",
        "latitude": None,
        "longitude": None,
        "elevation": None,
        "gpsd_status": "disable",
        "time_source": "system",
        "timestamp_utc": now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "iso_timestamp": now_dt.astimezone().isoformat(),
        "temp_c": None,
        "humidity_pct": None,
        "pressure_hPa": None,
        "dew_point_c": None,
        "cpu_temp_mount_c": None,
        "cpu_temp_rpi_c": None,
        "flashair": "DISCONNECTED",
        "flashair_url": "http://192.168.50.200"
    }


# ---------------------------------------------------------------------------
# UI Drawing Helpers
# ---------------------------------------------------------------------------
def draw_badge(draw: ImageDraw.Draw, text: str, x_right: int, y_top: int, badge_type: str, font: ImageFont.ImageFont):
    """Draw an OrionFieldStack-styled badge pill with background, outline, and text."""
    b_type = badge_type.lower()
    bg_color, border_color, text_color = BADGE_STYLES.get(b_type, BADGE_STYLES["unknown"])

    # Measure text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    t_width = bbox[2] - bbox[0]
    t_height = bbox[3] - bbox[1]

    pad_h = 3
    pad_v = 1
    pill_w = t_width + pad_h * 2
    pill_h = t_height + pad_v * 2 + 1

    x0 = x_right - pill_w
    y0 = y_top
    x1 = x_right
    y1 = y0 + pill_h

    # Rounded rectangle badge
    draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=3, fill=bg_color, outline=border_color, width=1)
    # Centered text inside badge
    tx = x0 + pad_h
    ty = y0 + pad_v
    draw.text((tx, ty), text, fill=text_color, font=font)


def draw_section_card(draw: ImageDraw.Draw, x0: int, y0: int, x1: int, y1: int, title: str, font_title: ImageFont.ImageFont):
    """Draw a card panel with header title and gold underline."""
    # Glassmorphism Card Panel
    draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=3, fill=COLOR_BG_CARD, outline=COLOR_BORDER_CARD, width=1)

    # Section Title (Gold, uppercase)
    draw.text((x0 + 5, y0 + 1), title, fill=COLOR_ACCENT_GOLD, font=font_title)

    # Title Gold Underline
    draw.line([(x0 + 5, y0 + 13), (x1 - 5, y0 + 13)], fill=COLOR_BORDER_GOLD, width=1)


# ---------------------------------------------------------------------------
# Core Screen Rendering (240x240 LCD Canvas)
# ---------------------------------------------------------------------------
def render_status_screen(data: dict, width: int = 240, height: int = 240, pulse: bool = False) -> Image.Image:
    """
    Renders the live OrionFieldStack Telemetry Screen on a 240x240 canvas.
    Matches the Web GUI aesthetic with high-density, legible font sizes:
      Left Column:
        - INDI STATUS (Server, Mount)
        - TIME (Local, UTC, Source)
        - FLASH AIR (Status, Host, Link)
      Right Column:
        - GPS (Coords, Elev, GPSD)
        - ENVIRONMENT (Temp, Hum, Press, Dew, CPU, Pier)
    """
    img = Image.new("RGB", (width, height), color=COLOR_BG_DARK)
    draw = ImageDraw.Draw(img)

    # Fonts (Optimized for larger size and high readability)
    font_header = get_font(10, bold=True)
    font_sec = get_font(9, bold=True)
    font_label = get_font(9, bold=False)
    font_val = get_font(9, bold=False, mono=True)
    font_val_small = get_font(8, bold=False, mono=True)
    font_badge = get_font(8, bold=True)
    font_footer = get_font(8, bold=False)

    # 1. Outer Frame Border
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(30, 42, 58), width=1)

    # 2. Top Header Bar (Y: 1 - 19)
    draw.rectangle([(1, 1), (width - 2, 19)], fill=(14, 19, 28))
    draw.line([(1, 19), (width - 2, 19)], fill=(45, 58, 78), width=1)

    # Header Symbol (Star / Diamond)
    star_x, star_y = 8, 10
    draw.polygon([
        (star_x, star_y - 4),
        (star_x + 3, star_y),
        (star_x, star_y + 4),
        (star_x - 3, star_y)
    ], fill=COLOR_ACCENT_GOLD)

    # Header Title
    draw.text((15, 4), "ORION FIELD STACK", fill=COLOR_TEXT_MAIN, font=font_header)

    # Header Status LED & Mode
    led_col = COLOR_ACCENT_GREEN if pulse else (0, 180, 100)
    draw.ellipse([(width - 39, 7), (width - 33, 13)], fill=led_col)
    draw.text((width - 29, 4), "LIVE", fill=(160, 230, 190), font=font_badge)

    # Grid Dimensions (2 Columns, Tight Margins)
    col_w = 117
    left_x0, left_x1 = 2, 2 + col_w
    right_x0, right_x1 = 121, 121 + col_w

    pad_left = 5
    pad_right = 5

    # =========================================================================
    # LEFT COLUMN 1: INDI STATUS (y: 21 - 76, h=55)
    # =========================================================================
    draw_section_card(draw, left_x0, 21, left_x1, 76, "INDI STATUS", font_sec)

    # Server Status
    srv = (data.get("indi_server") or "DISCONNECTED").upper()
    draw.text((left_x0 + pad_left, 37), "Server", fill=COLOR_TEXT_DIM, font=font_label)
    srv_badge_text = "ONLINE" if srv == "CONNECTED" else "OFFLINE"
    draw_badge(draw, srv_badge_text, left_x1 - pad_right, 36, "connected" if srv == "CONNECTED" else "disconnected", font_badge)

    # Mount Status
    mnt = (data.get("status") or "UNKNOWN").upper()
    draw.text((left_x0 + pad_left, 56), "Mount", fill=COLOR_TEXT_DIM, font=font_label)
    mnt_badge_type = mnt.lower()
    if mnt_badge_type not in BADGE_STYLES:
        mnt_badge_type = "alert" if "ERR" in mnt else "idle"
    mnt_display = mnt[:8]
    draw_badge(draw, mnt_display, left_x1 - pad_right, 55, mnt_badge_type, font_badge)

    # =========================================================================
    # LEFT COLUMN 2: TIME (y: 78 - 150, h=72)
    # =========================================================================
    draw_section_card(draw, left_x0, 78, left_x1, 150, "TIME", font_sec)

    # Extract Local Time (HH:MM:SS)
    iso_ts = data.get("iso_timestamp")
    local_str = "--:--:--"
    if iso_ts and "T" in iso_ts:
        t_idx = iso_ts.index("T")
        local_str = iso_ts[t_idx + 1:t_idx + 9]
    elif not iso_ts:
        local_str = datetime.now().strftime("%H:%M:%S")

    # Extract UTC Time (HH:MM:SS)
    utc_ts = data.get("timestamp_utc")
    utc_str = "--:--:--"
    if utc_ts and "T" in utc_ts:
        t_idx = utc_ts.index("T")
        utc_str = utc_ts[t_idx + 1:t_idx + 9]
    elif not utc_ts:
        utc_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

    draw.text((left_x0 + pad_left, 94), "Local", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((left_x1 - pad_right, 94), local_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((left_x0 + pad_left, 112), "UTC", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((left_x1 - pad_right, 112), utc_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    time_src = (data.get("time_source") or "system").lower()
    draw.text((left_x0 + pad_left, 130), "Source", fill=COLOR_TEXT_DIM, font=font_label)
    draw_badge(draw, "GPSD" if time_src == "gpsd" else "OS", left_x1 - pad_right, 129, "gpsd" if time_src == "gpsd" else "os", font_badge)

    # =========================================================================
    # LEFT COLUMN 3: FLASH AIR (y: 152 - 225, h=73)
    # =========================================================================
    draw_section_card(draw, left_x0, 152, left_x1, 225, "FLASH AIR", font_sec)

    fa_stat = (data.get("flashair") or "DISCONNECTED").upper()
    draw.text((left_x0 + pad_left, 168), "Status", fill=COLOR_TEXT_DIM, font=font_label)
    fa_badge = "ACTIVE" if fa_stat == "CONNECTED" else "OFFLINE"
    draw_badge(draw, fa_badge, left_x1 - pad_right, 167, "connected" if fa_stat == "CONNECTED" else "disconnected", font_badge)

    fa_url = data.get("flashair_url") or "http://192.168.50.200"
    fa_ip = fa_url.replace("http://", "").replace("https://", "").split("/")[0]

    draw.text((left_x0 + pad_left, 187), "Host", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((left_x1 - pad_right, 187), fa_ip, fill=COLOR_TEXT_MAIN, font=font_val_small, anchor="ra")

    draw.text((left_x0 + pad_left, 205), "Link", fill=COLOR_TEXT_DIM, font=font_label)
    link_status_txt = "Ready" if fa_stat == "CONNECTED" else "Standby"
    draw.text((left_x1 - pad_right, 205), link_status_txt, fill=COLOR_ACCENT_BLUE if fa_stat == "CONNECTED" else COLOR_TEXT_MUTED, font=font_val, anchor="ra")

    # =========================================================================
    # RIGHT COLUMN 1: GPS (y: 21 - 105, h=84)
    # =========================================================================
    draw_section_card(draw, right_x0, 21, right_x1, 105, "GPS", font_sec)

    lat = data.get("latitude")
    lon = data.get("longitude")
    elev = data.get("elevation")
    gpsd_st = (data.get("gpsd_status") or "disable").lower()

    lat_str = f"{lat:.4f}°" if lat is not None else "N/A"
    lon_str = f"{lon:.4f}°" if lon is not None else "N/A"
    elev_str = f"{elev:.1f} m" if elev is not None else "N/A"

    draw.text((right_x0 + pad_left, 37), "Lat", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 37), lat_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 54), "Lon", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 54), lon_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 71), "Elev", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 71), elev_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 88), "GPSD", fill=COLOR_TEXT_DIM, font=font_label)
    draw_badge(draw, "ACTIVE" if gpsd_st == "enable" else "OFFLINE", right_x1 - pad_right, 87, "active" if gpsd_st == "enable" else "offline", font_badge)

    # =========================================================================
    # RIGHT COLUMN 2: ENVIRONMENT (y: 107 - 225, h=118)
    # =========================================================================
    draw_section_card(draw, right_x0, 107, right_x1, 225, "ENVIRONMENT", font_sec)

    t_val = data.get("temp_c")
    h_val = data.get("humidity_pct")
    p_val = data.get("pressure_hPa")
    d_val = data.get("dew_point_c")
    cm_val = data.get("cpu_temp_mount_c")
    cr_val = data.get("cpu_temp_rpi_c")

    t_str = f"{t_val:.1f} °C" if t_val is not None else "--"
    h_str = f"{h_val:.1f} %" if h_val is not None else "--"
    p_str = f"{p_val:.1f} hPa" if p_val is not None else "--"
    d_str = f"{d_val:.1f} °C" if d_val is not None else "--"

    cpu_m = f"{cm_val:.0f}°" if cm_val is not None else "--"
    cpu_r = f"{cr_val:.0f}°" if cr_val is not None else "--"
    cpu_str = f"M:{cpu_m} R:{cpu_r}"

    draw.text((right_x0 + pad_left, 123), "Temp", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 123), t_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 140), "Humid", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 140), h_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 157), "Press", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 157), p_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 174), "Dew P", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 174), d_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    draw.text((right_x0 + pad_left, 191), "CPU", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 191), cpu_str, fill=COLOR_TEXT_MAIN, font=font_val, anchor="ra")

    # Pier / Position Indicator
    pier = (data.get("side_of_pier") or "UNKNOWN").upper()
    pier_col = COLOR_ACCENT_CYAN if pier == "EAST" else ((255, 120, 255) if pier == "WEST" else COLOR_TEXT_MUTED)
    draw.text((right_x0 + pad_left, 208), "Pier", fill=COLOR_TEXT_DIM, font=font_label)
    draw.text((right_x1 - pad_right, 208), pier, fill=pier_col, font=font_val, anchor="ra")

    # =========================================================================
    # 4. Bottom Footer Bar (Y: 226 - 239)
    # =========================================================================
    draw.line([(1, 226), (width - 2, 226)], fill=(30, 42, 58), width=1)
    draw.text((5, 228), "● Live Telemetry", fill=(100, 180, 140), font=font_footer)
    draw.text((width - 5, 228), "Press 'q' exit", fill=COLOR_TEXT_MUTED, font=font_footer, anchor="ra")

    return img


# ---------------------------------------------------------------------------
# LCD Hardware Shutdown Helper
# ---------------------------------------------------------------------------
def turn_off_display(display):
    """Completely turn off the ST7789 display screen and backlight."""
    print("\n[INFO] Turning off display and shutting down...")
    if display is not None:
        try:
            display.clear((0, 0, 0))
        except Exception:
            pass
        try:
            display.command(ST7789_DISPOFF)
            display.command(ST7789_SLPIN)
        except Exception:
            pass
        try:
            display.set_backlight(0.0)
        except Exception:
            pass

    if stop_backlight_daemon is not None:
        try:
            stop_backlight_daemon()
        except Exception:
            pass

    try:
        subprocess.run(["pinctrl", "set", "23", "op", "dl"], check=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main Routine & Event Loop
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="OrionFieldStack LCD Status View (ofs_status_view)")
    parser.add_argument("--rotation", type=int, default=2, choices=[0, 1, 2, 3], help="Screen rotation (default: 2 / 180 deg)")
    parser.add_argument("--brightness", type=float, default=100.0, help="Backlight brightness duty cycle 0-100% (default: 100.0)")
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds (default: 1.0)")
    parser.add_argument("--mock", action="store_true", help="Use mock telemetry data for simulation/testing")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000/api/telemetry", help="URL of telemetry REST API")
    parser.add_argument("--preview-only", action="store_true", help="Generate preview PNG without hardware initialization")
    parser.add_argument("--output", type=str, default="preview_ofs_status.png", help="Preview output filename (default: preview_ofs_status.png)")
    parser.add_argument("--x-offset", type=int, default=None, help="Custom column offset (default: auto)")
    parser.add_argument("--y-offset", type=int, default=None, help="Custom row offset (default: auto)")
    parser.add_argument("--no-invert", action="store_true", help="Disable IPS color inversion")
    args = parser.parse_args()

    print("==================================================")
    print("OrionFieldStack Live Status View (ofs_status_view)")
    print("Host: Raspberry Pi 5 / ST7789 240x240 LCD")
    print(f"Config: rotation={args.rotation}, brightness={args.brightness}%, interval={args.interval}s")
    if args.mock:
        print("Mode: Mock telemetry simulation enabled (--mock)")
    if args.preview_only:
        print("Mode: Preview PNG generation only (--preview-only)")
    print("==================================================")

    # 1. Fetch telemetry & Generate initial screen
    telemetry = fetch_telemetry(mock=args.mock, api_url=args.api_url)
    img = render_status_screen(telemetry, pulse=True)

    if args.preview_only:
        preview_path = os.path.join(CURRENT_DIR, args.output)
        img.save(preview_path)
        print(f">> Saved telemetry preview image: {preview_path}")
        print(">> Preview generation completed successfully.")
        return

    # 2. Hardware initialization
    if ST7789 is None:
        print("ERROR: st7789 driver module could not be imported.", file=sys.stderr)
        print("Tip: If testing on PC without SPI hardware, use '--preview-only'.", file=sys.stderr)
        sys.exit(1)

    print("[*] Initializing AE-ATM0130B3 display via SPI...")
    try:
        display = ST7789(
            width=240,
            height=240,
            rotation=args.rotation,
            spi_port=0,
            spi_cs=0,
            spi_speed_hz=24_000_000,
            pin_dc=25,
            pin_res=24,
            pin_bl=23,
            bl_duty=args.brightness,
            x_offset=args.x_offset,
            y_offset=args.y_offset,
            invert_colors=not args.no_invert,
        )
    except Exception as e:
        print(f"ERROR: Failed to initialize ST7789 hardware: {e}", file=sys.stderr)
        print("Tip: Use '--preview-only' to inspect UI without hardware.", file=sys.stderr)
        sys.exit(1)

    # 3. Setup console raw mode for smooth interactive exit
    stop_requested = False

    def sig_handler(sig, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    fd = None
    old_settings = None
    if HAS_TERMIOS and sys.stdin.isatty():
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except Exception:
            fd = None
            old_settings = None

    print("--------------------------------------------------")
    print(">> Status view is running on LCD screen.")
    print(">> Press 'q' or Enter to exit and safely shut down.")
    print("--------------------------------------------------")

    pulse_state = False
    try:
        while not stop_requested:
            # 1. Fetch latest telemetry
            telemetry = fetch_telemetry(mock=args.mock, api_url=args.api_url)

            # 2. Render frame
            pulse_state = not pulse_state
            frame_img = render_status_screen(telemetry, pulse=pulse_state)

            # 3. Transmit to display
            display.display(frame_img)

            # 4. Wait for next interval while monitoring user key
            start_wait = time.time()
            while (time.time() - start_wait) < args.interval:
                if fd is not None:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if rlist:
                        ch = sys.stdin.read(1)
                        if ch in ('q', 'Q', '\n', '\r', '\x1b', '\x03'):
                            stop_requested = True
                            break
                else:
                    time.sleep(0.05)
                if stop_requested:
                    break

    finally:
        # Restore terminal settings
        if old_settings is not None and fd is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass
        # Safely shut down display and backlight
        turn_off_display(display)
        display.close()
        print("Display shut down cleanly. Bye!")


if __name__ == "__main__":
    main()
