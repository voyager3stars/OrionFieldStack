# =================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 Logger & Analyzer
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      15.0.5 (JSON Log v1.6.2 Compliance)
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
        "JSON_ver", "Session_ID", "Objective", "Telescope", "Opt", "Filter", 
        "Camera", "Aperture", "Focal_L", "F_num", "Pixel_Size", "Pixel_Scale",
        "LocalTime", "UTC_Time", "UTC_Offset", "LST", "UnixTime", "Sf_Exp_t", 
        "Diff Sf-Exif", "Mode", "Type", "Filename", "SavedDir", "Format", 
        "FileSize", "Width", "Height", "ISO_Exif", "Exposure_Exif", 
        "DateTime_Exif", "Model", "Lat_Exif", "Lon_Exif", "Alt_Exif",
        "RA", "DEC", "RA_HMS", "DEC_DMS", "MT_Status", "Side", "HourAngle",
        "Site_Name", "Lat_INDI", "Lon_INDI", "Alt_INDI", "TZ_Source",
        "Temp_Ext_C", "Humidity_pct", "Pressure_hPa", "DewPoint_C", 
        "Mnt_CPU_Temp_C", "RPi_CPU_Temp_C", "SSE_Version", "Solve_Status", 
        "Solve_Path", "Solve_Confidence", "Solve_Timestamp", "Solve_RA", 
        "Solve_DEC", "Solve_Orientation", "Solve_RA_hms", "Solve_DEC_dms", 
        "Matched_Stars", "Solve_Time_sec", "SF_version", "SF_status", 
        "SF_timestamp", "SF_stars", "SF_fwhm_med", "SF_fwhm_mean", 
        "SF_fwhm_std", "SF_ell_med", "SF_ell_mean", "SF_ell_std"
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
                
                # Check for SubIFDs in raw images to get original resolution
                subifd_tag = tags.get("Image SubIFDs")
                if subifd_tag:
                    import struct
                    f.seek(0)
                    header = f.read(4)
                    endian = '<' if header[:2] == b'II' else '>'
                    offsets = subifd_tag.values
                    if not isinstance(offsets, list):
                        offsets = [offsets]
                    for offset in offsets:
                        try:
                            f.seek(offset)
                            num_entries_data = f.read(2)
                            if len(num_entries_data) == 2:
                                num_entries = struct.unpack(f"{endian}H", num_entries_data)[0]
                                for _ in range(num_entries):
                                    entry_data = f.read(12)
                                    if len(entry_data) < 12:
                                        break
                                    tag, tag_type, count, val_offset = struct.unpack(f"{endian}HHII", entry_data)
                                    if tag == 256 and tag_type in (3, 4):
                                        all_w.append(val_offset)
                                    elif tag == 257 and tag_type in (3, 4):
                                        all_h.append(val_offset)
                        except:
                            pass

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
        f_number, pixel_scale = utils.calculate_equipment_specs(CONFIG["EQUIPMENT"])
        exp_actual = shot.elapsed_on_ms / 1000.0
        exp_exif = float(ex["exp"]) if ex["exp"] else exp_actual
        exposure_diff = round(exp_actual - exp_exif, 6)
        camera_model = ex["model"] if ex["model"] else CONFIG["EQUIPMENT"]["camera"]
        
        # utils 側で生成された整形済み文字列 (_s) を使用することで、安全かつ綺麗な表示を実現
        row = [
            CONFIG["JSON_SPEC"],
            CONFIG["CONTEXT"]["session"],
            CONFIG["CONTEXT"]["objective"],
            CONFIG["EQUIPMENT"].get("telescope", "N/A"),
            CONFIG["EQUIPMENT"].get("optics", "N/A"),
            CONFIG["EQUIPMENT"].get("filter", "N/A"),
            camera_model,
            CONFIG["EQUIPMENT"].get("aperture_mm", ""),
            CONFIG["EQUIPMENT"].get("focal_length_mm", ""),
            f"{f_number:.2f}" if f_number else "",
            CONFIG["EQUIPMENT"].get("pixel_size_um", ""),
            f"{pixel_scale:.3f}" if pixel_scale else "",
            
            shot.timestamp_local,
            shot.timestamp_utc,
            indi.get("utc_offset", "+09:00"),
            indi.get("lst_hms", "00:00:00"),
            f"{shot.dt_object.timestamp():.3f}",
            f"{exp_actual:.3f}",
            f"{exposure_diff:.3f}",
            shot.shot_mode,
            CONFIG["CONTEXT"].get("frame_type", "test"),
            
            shot.filename,
            CONFIG["SAVE_DIR"],
            shot.file_format,
            f"{shot.file_size_mb:.2f}",
            ex["w"],
            ex["h"],
            
            ex["iso"] if ex["iso"] else "",
            f"{exp_exif:.3f}",
            ex["dt"] if ex["dt"] else "",
            camera_model,
            ex["lat"] if ex["lat"] else "",
            ex["lon"] if ex["lon"] else "",
            ex["alt"] if ex["alt"] else "",
            
            indi.get("ra_deg_s", ""),
            indi.get("dec_deg_s", ""),
            indi.get("ra_hms", ""),
            indi.get("dec_dms", ""),
            indi.get("status", ""),
            indi.get("side_of_pier", ""),
            indi.get("hour_angle_s", ""),
            
            indi.get("site_name", ""),
            indi.get("latitude_s", ""),
            indi.get("longitude_s", ""),
            indi.get("elevation_s", ""),
            indi.get("tz_source", ""),
            
            indi.get("weather_temp_s", ""),
            indi.get("weather_humi_s", ""),
            indi.get("weather_pres_s", ""),
            indi.get("weather_dew_s", ""),
            indi.get("cpu_temp_mount_s", ""),
            indi.get("cpu_temp_rpi_s", ""),
            
            # SSE empty fields (12)
            "", "pending", "", "", "", "", "", "", "", "", "", "",
            # SF empty fields (10)
            "", "pending", "", "", "", "", "", "", "", ""
        ]
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row)
            f.flush(); os.fsync(f.fileno())
            
        # --- DATA ARCHIVING: 2. JSON (利用: indi.get("xxx") の生数値) ---
        
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
                    "tz_source": indi.get("tz_source")
                },
                "environment": {
                    "temp_c": indi.get("weather_temp"),
                    "humidity_pct": indi.get("weather_humi"),
                    "pressure_hPa": indi.get("weather_pres"),
                    "dew_point_c": indi.get("weather_dew"),
                    "cpu_temp_mount_c": indi.get("cpu_temp_mount"),
                    "cpu_temp_rpi_c": indi.get("cpu_temp_rpi")
                }
            },
            "analysis": {
                "SSE": {
                    "sse_version": None,
                    "solve_status": "pending",
                    "solve_path": None,
                    "confidence": None,
                    "timestamp": None,
                    "solved_coords": {
                        "ra_deg": None, "dec_deg": None, "orientation": None,
                        "ra_hms": None, "dec_dms": None
                    },
                    "process_stats": {
                        "matched_stars": None, "solve_duration_sec": None
                    }
                },
                "SF": {
                    "sf_version": None,
                    "sf_status": "pending",
                    "sf_timestamp": None,
                    "quality": {
                        "sf_stars": None,
                        "sf_fwhm_med": None, "sf_fwhm_mean": None, "sf_fwhm_std": None,
                        "sf_ell_med": None,  "sf_ell_mean": None,  "sf_ell_std": None
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
