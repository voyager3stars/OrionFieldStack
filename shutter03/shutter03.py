#!/usr/bin/env python3

import os
import sys
import time
import csv
import queue
import threading
import requests
import exifread
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

# exifreadの内部ログを抑制
logging.getLogger('exifread').setLevel(logging.ERROR)

# Raspberry PiのGPIO制御設定
os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"
from gpiozero import LED

# ==============================================================================
# 1. 画面出力・表示モード制御
# ==============================================================================
LOG_LEVELS = {"full": 3, "simple": 2, "off": 1}

def sp_print(message, level="full"):
    """
    指定されたレベルに基づいてメッセージを表示する。
    """
    current_mode = CONFIG.get("DISPLAY_MODE", "full")
    if LOG_LEVELS[current_mode] >= LOG_LEVELS[level]:
        if current_mode == "off":
            return
        print(f"\033[38;5;82m SP03>> {message}\033[0m")

def print_help():
    help_text = """
ShutterPro03 (v12.5) - Usage:
  python3 shutter03.py [shots] [mode] [sec] [display]

Arguments:
  1. target_shots : Number of shots (0 for infinite).
  2. shot_mode    : 'camera' or 'bulb'.
  3. bulb_sec     : Exposure seconds for bulb.
  4. display      : 'full' (all), 'simple' (milestones), 'off' (silent). [Default: full]
"""
    print(help_text)

# ==============================================================================
# 2. システム設定 (INDI設定を汎用化)
# ==============================================================================
CONFIG = {
    # --- 基本動作設定 ---
    "GPIO_SHUTTER": 27,
    "DEFAULT_BULB_SEC": 10.0,
    "TRIGGER_PULSE_SEC": 1.0,
    "SHUTTER_COMPENSATION": 0.35,
    "SHUTTER_OFF_SEC": 10.0,
    "DISPLAY_MODE": "full",
    "TIMEZONE_JST": timezone(timedelta(hours=9)),

    # --- 保存・通信設定 ---
    "FLASHAIR_URL": "http://192.168.50.200",
    "SAVE_DIR": "/home/mtorig/astroimage",
    "LOG_FILE": "shutter_log.csv",

    # --- INDI デバイス設定 (OnStep以外の場合はここを書き換える) ---
    "INDI_MOUNT": "LX200 OnStep",       # 赤道儀デバイス名 (例: "SkyWatcher HEQ5")
    "INDI_WEATHER": "LX200 OnStep",     # 気象デバイス名 (例: "Pegasus UPB")
    
    # --- INDI プロパティ設定 (標準的な名前ですが、機材により異なる場合に修正) ---
    "PROP_COORD": "EQUATORIAL_EOD_COORD", # 座標 (RA/DEC)
    "PROP_GEO": "GEOGRAPHIC_COORD",       # 地理情報 (LAT/LON/ALT)
    "PROP_WEATHER": "WEATHER_PARAMETERS", # 気象情報
}

@dataclass
class ShotRecord:
    timestamp_utc: str
    timestamp_jst: str
    elapsed_on_ms: float
    indi_data: dict
    shot_mode: str
    local_path: str = ""
    file_format: str = ""
    file_size_mb: float = 0.0

# ==============================================================================
# 3. ユーティリティ & INDI クライアント
# ==============================================================================
def _convert_gps(tags, key_coord, key_ref):
    if key_coord not in tags: return ""
    try:
        c = tags[key_coord]
        val = (float(c.values[0].num)/c.values[0].den) + \
              (float(c.values[1].num)/c.values[1].den)/60 + \
              (float(c.values[2].num)/c.values[2].den)/3600
        if key_ref in tags and str(tags[key_ref].values) in ['S', 'W']: val = -val
        return f"{val:.6f}"
    except: return ""

def _get_altitude(tags):
    if "GPS GPSAltitude" not in tags: return ""
    try:
        alt = tags["GPS GPSAltitude"].values[0]
        val = float(alt.num) / alt.den
        ref = tags.get("GPS GPSAltitudeRef")
        if ref and ref.values[0] == 1: val = -val
        return f"{val:.1f}"
    except: return ""

class IndiClient:
    def _get_prop(self, device, property_name, element_name):
        """指定したデバイスのプロパティ値を取得する汎用メソッド"""
        full_prop = f"{device}.{property_name}.{element_name}"
        try:
            result = subprocess.run(["indi_getprop", full_prop], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1)
            if result.returncode == 0 and "=" in result.stdout: 
                return result.stdout.strip().split("=")[1]
        except: pass
        return None

    def get_observation_data(self):
        """CONFIGで指定されたデバイス名・プロパティ名に基づいてデータを取得"""
        mount = CONFIG["INDI_MOUNT"]
        weather = CONFIG["INDI_WEATHER"]
        
        try:
            return {
                "ra": self._get_prop(mount, CONFIG["PROP_COORD"], "RA"), 
                "dec": self._get_prop(mount, CONFIG["PROP_COORD"], "DEC"),
                "lat": self._get_prop(mount, CONFIG["PROP_GEO"], "LAT"), 
                "lon": self._get_prop(mount, CONFIG["PROP_GEO"], "LONG"),
                "alt": self._get_prop(mount, CONFIG["PROP_GEO"], "ELEV"), 
                "weather_temp": self._get_prop(weather, CONFIG["PROP_WEATHER"], "WEATHER_TEMPERATURE"),
                "weather_hum": self._get_prop(weather, CONFIG["PROP_WEATHER"], "WEATHER_HUMIDITY"), 
                "weather_pres": self._get_prop(weather, CONFIG["PROP_WEATHER"], "WEATHER_BAROMETER"),
                "weather_dew": self._get_prop(weather, CONFIG["PROP_WEATHER"], "WEATHER_DEWPOINT"), 
                "cpu_temp": self._get_prop(weather, CONFIG["PROP_WEATHER"], "WEATHER_CPU_TEMPERATURE")
            }
        except: return {}

# ==============================================================================
# 4. ワーカー (Downloader & Analyzer)
# ==============================================================================
def downloader_worker(download_queue, analysis_queue, stop_event):
    base_url = CONFIG["FLASHAIR_URL"]
    save_dir = CONFIG["SAVE_DIR"]
    known_files = set()
    last_target = ""
    sp_print("[Run] Downloader: Monitoring started", level="full")

    while not (stop_event.is_set() and download_queue.empty()):
        target = None
        try:
            r = requests.get(f"{base_url}/command.cgi?op=100&DIR=/DCIM", timeout=5)
            dirs = [l.split(',')[1] for l in r.text.strip().splitlines()[1:] if '_' in l.split(',')[1]]
            if dirs:
                dirs.sort()
                target = f"/DCIM/{dirs[-1]}"
        except: time.sleep(2); continue

        if not target: time.sleep(2); continue
        if target != last_target: last_target = target

        try:
            r = requests.get(f"{base_url}/command.cgi", params={"op": "100", "DIR": target}, timeout=5)
            if r.status_code == 200:
                for line in r.text.strip().splitlines()[1:]:
                    parts = line.split(',')
                    if len(parts) < 3: continue
                    fname, fsize = parts[1], int(parts[2])
                    full_remote = f"{target}/{fname}"
                    ext = os.path.splitext(fname)[1].lower()

                    if ext in ['.dng', '.jpg'] and full_remote not in known_files:
                        if not known_files and last_target == "":
                            known_files.add(full_remote); continue
                        if not download_queue.empty():
                            shot_data = download_queue.get()
                            local_path = os.path.join(save_dir, fname)
                            current_fsize = fsize
                            for _ in range(25):
                                time.sleep(1)
                                chk = requests.get(f"{base_url}/command.cgi", params={"op": "100", "DIR": target}, timeout=5)
                                new_size = next((int(l.split(',')[2]) for l in chk.text.strip().splitlines() if fname in l), 0)
                                if new_size > 0 and new_size == current_fsize: break
                                current_fsize = new_size
                            
                            sp_print(f"Downloading: {fname} ({current_fsize/1024/1024:.2f}MB)", level="full")
                            resp = requests.get(f"{base_url}{full_remote}", timeout=60)
                            with open(local_path, 'wb') as f:
                                f.write(resp.content)
                                f.flush(); os.fsync(f.fileno())
                            
                            shot_data.local_path = local_path
                            shot_data.file_format = ext[1:].upper()
                            shot_data.file_size_mb = current_fsize/1024/1024
                            analysis_queue.put(shot_data)
                            download_queue.task_done()
                        known_files.add(full_remote)
        except: pass
        time.sleep(1)

def analyzer_worker(analysis_queue, stop_event):
    log_file = CONFIG["LOG_FILE"]
    sp_print("[Run] Analyzer: Ready", level="full")
    header = ["UTC", "JST", "Actual_ON_sec", "Filename", "Shot_Mode", "Format", "Size_MB", "Width_px", "Height_px", 
              "ISO_Exif", "Exposure_Exif", "DateTime_Exif", "Lat_Exif", "Lon_Exif", "Alt_Exif", 
              "Lat_INDI", "Lon_INDI", "Alt_INDI", "Exp_Diff_sec", "RA_INDI", "DEC_INDI", 
              "Temp_Ext_C", "Humidity_pct", "Pressure_hPa", "DewPoint_C", "CPU_Temp_C"]
    
    if not os.path.exists(log_file):
        with open(log_file, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(header)

    while not (stop_event.is_set() and analysis_queue.empty()):
        try:
            shot = analysis_queue.get(timeout=1)
        except queue.Empty: continue
        
        local_path = shot.local_path
        fname = os.path.basename(local_path)
        ex = {"iso": "", "exp": "", "dt": "", "lat": "", "lon": "", "alt": "", "diff": "", "w": "0", "h": "0"}
        
        time.sleep(1.0)
        for attempt in range(5):
            try:
                with open(local_path, 'rb') as f:
                    tags = exifread.process_file(f, details=True)
                all_w, all_h = [], []
                for t_name, t_val in tags.items():
                    if "ImageWidth" in t_name or "0x0100" in t_name:
                        try: v = t_val.values[0] if isinstance(t_val.values, list) else t_val.values; all_w.append(int(v))
                        except: pass
                    if "ImageLength" in t_name or "0x0101" in t_name:
                        try: v = t_val.values[0] if isinstance(t_val.values, list) else t_val.values; all_h.append(int(v))
                        except: pass
                if all_w and all_h: ex["w"], ex["h"] = str(max(all_w)), str(max(all_h))
                iso = tags.get("EXIF ISOSpeedRatings") or tags.get("Image ISOSpeedRatings")
                if iso: ex["iso"] = str(iso.values[0])
                exp = tags.get("EXIF ExposureTime") or tags.get("Image ExposureTime")
                if exp:
                    v = exp.values[0]
                    exposure_val = float(v.num) / v.den if hasattr(v, 'num') else float(v)
                    ex["exp"] = f"{exposure_val:.6f}"
                    ex["diff"] = f"{(shot.elapsed_on_ms / 1000) - exposure_val:.6f}"
                dt = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
                if dt: ex["dt"] = str(dt.values)
                ex["lat"] = _convert_gps(tags, "GPS GPSLatitude", "GPS GPSLatitudeRef")
                ex["lon"] = _convert_gps(tags, "GPS GPSLongitude", "GPS GPSLongitudeRef")
                ex["alt"] = _get_altitude(tags)
                break
            except: pass
            time.sleep(1)
        
        indi = shot.indi_data
        row = [shot.timestamp_utc, shot.timestamp_jst, f"{shot.elapsed_on_ms/1000:.6f}", fname, 
               shot.shot_mode, shot.file_format, f"{shot.file_size_mb:.2f}", ex["w"], ex["h"], 
               ex["iso"], ex["exp"], ex["dt"], ex["lat"], ex["lon"], ex["alt"], 
               indi.get("lat"), indi.get("lon"), indi.get("alt"), ex["diff"], 
               indi.get("ra"), indi.get("dec"), 
               indi.get("weather_temp"), indi.get("weather_hum"), indi.get("weather_pres"), 
               indi.get("weather_dew"), indi.get("cpu_temp")]
        with open(log_file, 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row); f.flush(); os.fsync(f.fileno())
        
        sp_print(f"[Logged]: {fname} ({shot.file_format} Mode:{shot.shot_mode})", level="simple")
        analysis_queue.task_done()

# ==============================================================================
# 5. メイン制御
# ==============================================================================
def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print_help(); sys.exit(0)

    try:
        target_shots = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except ValueError:
        sp_print("Error: The first argument must be a number.", level="simple")
        print_help(); sys.exit(1)

    shot_mode = sys.argv[2].lower() if len(sys.argv) > 2 else "camera"
    bulb_sec = float(sys.argv[3]) if len(sys.argv) > 3 else CONFIG["DEFAULT_BULB_SEC"]
    
    if len(sys.argv) > 4:
        mode_input = sys.argv[4].lower()
        if mode_input in LOG_LEVELS:
            CONFIG["DISPLAY_MODE"] = mode_input

    infinite_mode = True if target_shots <= 0 else False
    shutter = LED(CONFIG["GPIO_SHUTTER"])
    indi = IndiClient() # デバイス名はCONFIGから参照
    download_q, analysis_q = queue.Queue(), queue.Queue()
    stop_event = threading.Event()

    t_down = threading.Thread(target=downloader_worker, args=(download_q, analysis_q, stop_event))
    t_anal = threading.Thread(target=analyzer_worker, args=(analysis_q, stop_event))
    t_down.start(); t_anal.start()

    sp_print(f"--- ShutterPro03 (v12.5) --- Mode: {shot_mode.upper()} / View: {CONFIG['DISPLAY_MODE'].upper()}", level="simple")

    shot_count = 0
    try:
        while infinite_mode or shot_count < target_shots:
            shot_count += 1
            ts_jst = datetime.now(CONFIG["TIMEZONE_JST"]).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            ts_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            
            sp_print(f"[{ts_jst}] Shutter ON ({shot_count}/{'Inf' if infinite_mode else target_shots})", level="simple")
            
            start = time.monotonic()
            shutter.on()
            if shot_mode == "bulb":
                target_time = start + bulb_sec + CONFIG["SHUTTER_COMPENSATION"]
                while time.monotonic() < target_time: time.sleep(0.01)
            else:
                time.sleep(CONFIG["TRIGGER_PULSE_SEC"])
            shutter.off()
            
            sp_print("Shutter OFF", level="full")
            download_q.put(ShotRecord(ts_utc, ts_jst, (time.monotonic() - start)*1000, indi.get_observation_data(), shot_mode))
            time.sleep(CONFIG["SHUTTER_OFF_SEC"])

        sp_print("--- All shutter instructions complete. ---", level="simple")
        while not (download_q.empty() and analysis_q.empty()): time.sleep(2)
        
    except KeyboardInterrupt:
        sp_print("--- User Interrupted ---", level="simple")
    finally:
        download_q.join(); analysis_q.join(); stop_event.set()
        shutter.off(); t_down.join(); t_anal.join()
        sp_print("--- All Processes Finished ---", level="simple")

if __name__ == "__main__":
    main()
