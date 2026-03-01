# =================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 Logger & Analyzer
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      14.1.1 (Refactored to use Pre-formatted Utils Data)
# License:      MIT
# Description:  Handles asynchronous image analysis and telemetry 
#               logging. Extracts Exif metadata, merges it with 
#               INDI device data, and maintains both CSV and 
#               structured JSON logs.
# =================================================================

import os
import json
import csv
import time
import exifread
import logging
import queue
from datetime import datetime
from dataclasses import dataclass

# Import project utilities
import sp03_utils as utils
    
@dataclass
class ShotRecord:
    """
    Data container representing a single capture event.
    """
    timestamp_utc: str
    timestamp_local: str
    elapsed_on_ms: float
    indi_data: dict
    shot_mode: str
    dt_object: datetime
    local_path: str = ""
    filename: str = ""
    file_format: str = ""
    file_size_mb: float = 0.0

# ==============================================================================
# Helper Functions: Exif Coordinate Conversion
# ==============================================================================

def _convert_gps(tags, key_coord, key_ref):
    if key_coord not in tags: return None
    try:
        c = tags[key_coord]
        val = (float(c.values[0].num)/c.values[0].den) + \
              (float(c.values[1].num)/c.values[1].den)/60 + \
              (float(c.values[2].num)/c.values[2].den)/3600
        if key_ref in tags and str(tags[key_ref].values) in ['S', 'W']: val = -val
        return val 
    except: return None

def _get_altitude(tags):
    if "GPS GPSAltitude" not in tags: return None
    try:
        alt = tags["GPS GPSAltitude"].values[0]
        val = float(alt.num) / alt.den
        ref = tags.get("GPS GPSAltitudeRef")
        if ref and ref.values[0] == 1: val = -val
        return val
    except: return None


# ==============================================================================
# Main Worker: Analyzer (JSON v1.4.0 Compliance)
# ==============================================================================

def analyzer_worker(analysis_queue, stop_event, CONFIG):
    """
    Background worker that processes downloaded images.
    v14.1.0: Uses pre-formatted strings (_s) from utils for CSV and 
             pre-converted numeric values for JSON.
    """
    log_dir = os.getcwd() if CONFIG["LOG_DEST"] == "s2cur" else CONFIG["SAVE_DIR"]
    csv_file = os.path.join(log_dir, CONFIG["LOG_FILE_NAME"])
    latest_json_file = os.path.join(log_dir, CONFIG["LATEST_JSON_NAME"])
    history_json_file = os.path.join(log_dir, CONFIG["HISTORY_JSON_NAME"])

    header = [
            "Session_ID", "Objective", "Telescope", "Filter", "ISO_Timestamp", 
            "Timestamp_UTC", "Unixtime", "Actual_Exp_sec", "Exp_Diff_sec", 
            "Shot_Mode", "Frame_Type", "File_Name", "ISO", "Shutter_sec", 
            "RA_deg", "Dec_deg", "RA_HMS", "Dec_DMS", "Mount_Status", 
            "Side_Of_Pier", "Hour_Angle", "LST_HMS", "Lat_INDI", "Lon_INDI", 
            "Alt_INDI", "Temp_Ext_C", "Humidity_pct", "Pressure_hPa", 
            "DewPoint_C", "Mnt_CPU_Temp_C","RPi_CPU_Temp_C", "Solve_Status"
        ]

    if not os.path.exists(csv_file):
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            f.write(f"# OrionFieldStack CSV Log Spec v{CONFIG['JSON_SPEC']}\n")
            csv.writer(f).writerow(header)

    while not (stop_event.is_set() and analysis_queue.empty()):
        try: 
            shot = analysis_queue.get(timeout=1)
        except queue.Empty: 
            continue
        
        local_path = shot.local_path
        ex = {"iso": None, "exp": None, "dt": "", "lat": None, "lon": None, "alt": None, "diff": 0.0, "w": 0, "h": 0, "model": ""}
        
        time.sleep(1.0)
        
        # --- EXIF Extraction Block ---
        for attempt in range(5):
            try:
                with open(local_path, 'rb') as f:
                    tags = exifread.process_file(f, details=True)
                
                if "Image Model" in tags: ex["model"] = str(tags["Image Model"])
                elif "EXIF Model" in tags: ex["model"] = str(tags["EXIF Model"])

                all_w, all_h = [], []
                for t_name, t_val in tags.items():
                    if "ImageWidth" in t_name or "0x0100" in t_name:
                        try: v = t_val.values[0] if isinstance(t_val.values, list) else t_val.values; all_w.append(int(v))
                        except: pass
                    if "ImageLength" in t_name or "0x0101" in t_name:
                        try: v = t_val.values[0] if isinstance(t_val.values, list) else t_val.values; all_h.append(int(v))
                        except: pass
                if all_w and all_h: ex["w"], ex["h"] = max(all_w), max(all_h)
                
                iso = tags.get("EXIF ISOSpeedRatings") or tags.get("Image ISOSpeedRatings")
                if iso: ex["iso"] = int(iso.values[0])
                
                exp = tags.get("EXIF ExposureTime") or tags.get("Image ExposureTime")
                if exp:
                    v = exp.values[0]
                    exposure_val = float(v.num) / v.den if hasattr(v, 'num') else float(v)
                    ex["exp"] = exposure_val
                    ex["diff"] = (shot.elapsed_on_ms / 1000) - exposure_val
                
                dt = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
                if dt: ex["dt"] = str(dt.values)
                
                ex["lat"] = _convert_gps(tags, "GPS GPSLatitude", "GPS GPSLatitudeRef")
                ex["lon"] = _convert_gps(tags, "GPS GPSLongitude", "GPS GPSLongitudeRef")
                ex["alt"] = _get_altitude(tags)
                break
            except: pass
            time.sleep(1)
        
        indi = shot.indi_data
        
        # --- DATA ARCHIVING: 1. CSV (利用: indi.get("xxx_s")) ---
        # utils 側で生成された整形済み文字列 (_s) を使用することで、安全かつ綺麗な表示を実現
        row = [
            CONFIG["CONTEXT"]["session"],           # Session_ID
            CONFIG["CONTEXT"]["objective"],         # Objective
            CONFIG["EQUIPMENT"]["telescope"],       # Telescope
            CONFIG["EQUIPMENT"]["filter"],          # Filter
            shot.timestamp_local,                   # ISO_Timestamp
            shot.timestamp_utc,                     # Timestamp_UTC
            f"{shot.dt_object.timestamp():.3f}",    # Unixtime (Excel配慮で3桁)
            f"{shot.elapsed_on_ms/1000:.3f}",       # Actual_Exp_sec
            f"{ex['diff']:.3f}",                    # Exp_Diff_sec
            shot.shot_mode,                         # Shot_Mode
            CONFIG["CONTEXT"].get("frame_type", "test"), # Frame_Type
            shot.filename,                          # File_Name
            ex["iso"],                              # ISO
            f"{ex['exp']:.3f}" if ex['exp'] is not None else "", # Shutter_sec
            
            # --- INDIデータ (整形済み文字列を選択) ---
            indi.get("ra_deg_s"),                   # RA_deg
            indi.get("dec_deg_s"),                  # Dec_deg
            indi.get("ra_hms"),                     # RA_HMS
            indi.get("dec_dms"),                    # Dec_DMS
            indi.get("status"),                     # Mount_Status
            indi.get("side_of_pier"),                # Side_Of_Pier
            indi.get("hour_angle_s"),               # Hour_Angle
            indi.get("lst_hms"),                    # LST_HMS
            indi.get("latitude_s"),                 # Lat_INDI
            indi.get("longitude_s"),                # Lon_INDI
            indi.get("elevation_s"),                # Alt_INDI
            indi.get("weather_temp_s"),              # Temp_Ext_C
            indi.get("weather_humi_s"),              # Humidity_pct
            indi.get("weather_pres_s"),              # Pressure_hPa
            indi.get("weather_dew_s"),               # DewPoint_C
            indi.get("cpu_temp_mount_s"),           # INDI mountCPU temp
            indi.get("cpu_temp_rpi_s"),             # Raspberry Pi CPU temp
            
            "pending"                               # Solve_Status
        ]
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row)
            f.flush(); os.fsync(f.fileno())
            
        # --- DATA ARCHIVING: 2. JSON (利用: indi.get("xxx") の生数値) ---
        f_number, pixel_scale = utils.calculate_equipment_specs(CONFIG["EQUIPMENT"])
        exp_actual = shot.elapsed_on_ms / 1000.0
        exp_exif = float(ex["exp"]) if ex["exp"] else exp_actual
        exposure_diff = round(exp_actual - exp_exif, 6)
        camera_model = ex["model"] if ex["model"] else CONFIG["EQUIPMENT"]["camera"]
        
        json_data = {
            "version": CONFIG["JSON_SPEC"],
            "session_id": CONFIG["CONTEXT"]["session"],
            "objective": CONFIG["CONTEXT"]["objective"],
            "equipment": {
                "telescope": CONFIG["EQUIPMENT"].get("telescope"),
                "optics": CONFIG["EQUIPMENT"].get("optics"),
                "filter": CONFIG["EQUIPMENT"].get("filter"),
                "camera": CONFIG["EQUIPMENT"].get("camera"),
                "aperture_mm": CONFIG["EQUIPMENT"].get("aperture_mm"),
                "focal_length_mm": CONFIG["EQUIPMENT"].get("focal_length_mm"),
                "f_number": f_number,
                "pixel_size_um": CONFIG["EQUIPMENT"].get("pixel_size_um"),
                "pixel_scale": pixel_scale
            },
            "record": {
                "meta": {
                    "iso_timestamp": shot.timestamp_local,
                    "timestamp_utc": shot.timestamp_utc,
                    "utc_offset": indi.get("utc_offset", "+09:00"),
                    "lst_hms": indi.get("lst_hms", "00:00:00"),
                    "unixtime": round(shot.dt_object.timestamp(), 3),
                    "exposure_actual_sec": round(exp_actual, 3),
                    "exposure_diff_sec": exposure_diff,
                    "shot_mode": shot.shot_mode,
                    "frame_type": CONFIG["CONTEXT"].get("frame_type", "test")
                },
                "file": {
                    "name": shot.filename,
                    "path": CONFIG["SAVE_DIR"],
                    "format": shot.file_format,
                    "size_mb": round(shot.file_size_mb, 2),
                    "width": ex["w"], "height": ex["h"]
                },
                "exif": {
                    "iso": ex["iso"],
                    "shutter_sec": round(exp_exif, 3),
                    "datetime_original": ex["dt"],
                    "model": camera_model,
                    "lat": ex["lat"], "lon": ex["lon"], "alt": ex["alt"]
                },
                "mount": {
                    "ra_deg": indi.get("ra_deg"),
                    "dec_deg": indi.get("dec_deg"),
                    "ra_hms": indi.get("ra_hms"),
                    "dec_dms": indi.get("dec_dms"),
                    "status": indi.get("status", "Unknown"),
                    "side_of_pier": indi.get("side_of_pier", "Unknown"),
                    "hour_angle": indi.get("hour_angle")
                },
                "location": {
                    "site_name": indi.get("site_name"),
                    "latitude": indi.get("latitude"),
                    "longitude": indi.get("longitude"),
                    "elevation": indi.get("elevation"),
                    "timezone": indi.get("timezone"),
                    "utc_offset": indi.get("utc_offset"),
                    "tz_source": indi.get("tz_source")
                },
                "environment": {
                    # utils側ですでに数値化されているため、to_float_or_none は不要に
                    "temp_c": indi.get("weather_temp"),
                    "humidity_pct": indi.get("weather_humi"),
                    "pressure_hPa": indi.get("weather_pres"),
                    "dew_point_c": indi.get("weather_dew"),
                    "cpu_temp_mount_c": indi.get("cpu_temp_mount"),
                    "cpu_temp_rpi_c": indi.get("cpu_temp_rpi")
                },
                "analysis": {
                    "solve_status": "pending",
                    "solved_coords": None,
                    "quality": {
                        "hfr": None, "stars": None, "elongation": None, 
                        "satellite_detected": False, "sky_brightness": None
                    }
                }
            }
        }

        with open(latest_json_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)
        
        h = []
        if os.path.exists(history_json_file):
            try:
                with open(history_json_file, 'r', encoding='utf-8') as f: h = json.load(f)
            except: h = []
        h.append(json_data)
        with open(history_json_file, 'w', encoding='utf-8') as f:
            json.dump(h, f, indent=4, ensure_ascii=False)
        
        log_msg = f" [Logged]: {shot.filename} (v{CONFIG['VERSION']} / Spec v{CONFIG['JSON_SPEC']})"
        utils.sp_print(log_msg, CONFIG, level="simple")
        analysis_queue.task_done()
