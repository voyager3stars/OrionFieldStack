# =================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 Logger & Analyzer
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      13.12.0 (JSON Spec v1.3.2 Compliance)
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
    Passed from the Shutter engine to the Downloader and finally to the Analyzer.
    """
    timestamp_utc: str
    timestamp_jst: str
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
    """
    Converts Exif GPS rational format (degrees, minutes, seconds) to decimal degrees.
    
    Args:
        tags (dict): Exif tags extracted by exifread.
        key_coord (str): The Exif key for the coordinate (e.g., 'GPS GPSLatitude').
        key_ref (str): The Exif key for the reference (e.g., 'GPS GPSLatitudeRef').
    
    Returns:
        float: Decimal coordinate, or None if conversion fails.
    """
    if key_coord not in tags: return None
    try:
        c = tags[key_coord]
        # Convert rational values to float: (D/1) + (M/60) + (S/3600)
        val = (float(c.values[0].num)/c.values[0].den) + \
              (float(c.values[1].num)/c.values[1].den)/60 + \
              (float(c.values[2].num)/c.values[2].den)/3600
        # Apply sign based on Reference (S and W are negative)
        if key_ref in tags and str(tags[key_ref].values) in ['S', 'W']: val = -val
        return val 
    except: 
        return None

def _get_altitude(tags):
    """
    Extracts and converts GPS Altitude from Exif tags.
    """
    if "GPS GPSAltitude" not in tags: return None
    try:
        alt = tags["GPS GPSAltitude"].values[0]
        val = float(alt.num) / alt.den
        ref = tags.get("GPS GPSAltitudeRef")
        # GPSAltitudeRef: 0 = Above Sea Level, 1 = Below Sea Level
        if ref and ref.values[0] == 1: val = -val
        return val
    except: 
        return None


# ==============================================================================
# Main Worker: Analyzer (JSON v1.3.2 Orchestrator)
# ==============================================================================

def analyzer_worker(analysis_queue, stop_event, CONFIG):
    """
    Background worker that processes downloaded images.
    1. Extracts Exif data (ISO, Exposure, GPS, Model).
    2. Merges with INDI telemetry captured at the time of shutter pulse.
    3. Writes a flat record to CSV for legacy compatibility.
    4. Generates a structured JSON log adhering to Project Spec v1.3.2.
    """
    # Determine log destination based on config
    log_dir = os.getcwd() if CONFIG["LOG_DEST"] == "s2cur" else CONFIG["SAVE_DIR"]
    csv_file = os.path.join(log_dir, CONFIG["LOG_FILE_NAME"])
    latest_json_file = os.path.join(log_dir, CONFIG["LATEST_JSON_NAME"])
    history_json_file = os.path.join(log_dir, CONFIG["HISTORY_JSON_NAME"])
    
    # Define CSV Header (Structured for astronomical metadata)
    header = ["UTC", "JST", "Actual_ON_sec", "Filename", "SavedDir", "Shot_Mode", "Format", "Size_MB", "Width_px", "Height_px", 
              "ISO_Exif", "Exposure_Exif", "DateTime_Exif", "Lat_Exif", "Lon_Exif", "Alt_Exif", 
              "Lat_INDI", "Lon_INDI", "Alt_INDI", "Exp_Diff_sec", "RA_INDI", "DEC_INDI", 
              "Temp_Ext_C", "Humidity_pct", "Pressure_hPa", "DewPoint_C", "CPU_Temp_C"]
    
    # Initialize CSV if it doesn't exist
    if not os.path.exists(csv_file):
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(header)

    while not (stop_event.is_set() and analysis_queue.empty()):
        try: 
            # Non-blocking fetch from the analysis queue
            shot = analysis_queue.get(timeout=1)
        except queue.Empty: 
            continue
        
        local_path = shot.local_path
        # Temporary storage for extracted Exif data
        ex = {"iso": None, "exp": None, "dt": "", "lat": None, "lon": None, "alt": None, "diff": 0.0, "w": 0, "h": 0, "model": ""}
        
        # Brief pause to ensure OS file handles are settled
        time.sleep(1.0)
        
        # --- EXIF Extraction Block (with retry logic) ---
        for attempt in range(5):
            try:
                with open(local_path, 'rb') as f:
                    tags = exifread.process_file(f, details=True)
                
                # Identify Camera Model
                if "Image Model" in tags: ex["model"] = str(tags["Image Model"])
                elif "EXIF Model" in tags: ex["model"] = str(tags["EXIF Model"])

                # Extract Image Dimensions (checking multiple standard Exif tags)
                all_w, all_h = [], []
                for t_name, t_val in tags.items():
                    if "ImageWidth" in t_name or "0x0100" in t_name:
                        try: v = t_val.values[0] if isinstance(t_val.values, list) else t_val.values; all_w.append(int(v))
                        except: pass
                    if "ImageLength" in t_name or "0x0101" in t_name:
                        try: v = t_val.values[0] if isinstance(t_val.values, list) else t_val.values; all_h.append(int(v))
                        except: pass
                if all_w and all_h: ex["w"], ex["h"] = max(all_w), max(all_h)
                
                # Extract ISO and Exposure Time
                iso = tags.get("EXIF ISOSpeedRatings") or tags.get("Image ISOSpeedRatings")
                if iso: ex["iso"] = int(iso.values[0])
                
                exp = tags.get("EXIF ExposureTime") or tags.get("Image ExposureTime")
                if exp:
                    v = exp.values[0]
                    exposure_val = float(v.num) / v.den if hasattr(v, 'num') else float(v)
                    ex["exp"] = exposure_val
                    # Calculate latency: (GPIO pulse time) - (Internal Camera exposure)
                    ex["diff"] = (shot.elapsed_on_ms / 1000) - exposure_val
                
                dt = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
                if dt: ex["dt"] = str(dt.values)
                
                # Parse GPS data
                ex["lat"] = _convert_gps(tags, "GPS GPSLatitude", "GPS GPSLatitudeRef")
                ex["lon"] = _convert_gps(tags, "GPS GPSLongitude", "GPS GPSLongitudeRef")
                ex["alt"] = _get_altitude(tags)
                break # Success
            except: 
                pass
            time.sleep(1)
        
        indi = shot.indi_data
        
        # --- DATA ARCHIVING: 1. CSV (Flat format) ---
        row = [shot.timestamp_utc, shot.timestamp_jst, f"{shot.elapsed_on_ms/1000:.6f}", shot.filename, CONFIG["SAVE_DIR"],
               shot.shot_mode, shot.file_format, f"{shot.file_size_mb:.2f}", ex["w"], ex["h"], 
               ex["iso"], f"{ex['exp']:.6f}" if ex['exp'] else "", ex["dt"], 
               f"{ex['lat']:.6f}" if ex['lat'] else "", f"{ex['lon']:.6f}" if ex['lon'] else "", f"{ex['alt']:.2f}" if ex['alt'] else "", 
               indi.get("lat"), indi.get("lon"), indi.get("alt"), f"{ex['diff']:.6f}", 
               indi.get("ra"), indi.get("dec"), 
               indi.get("weather_temp"), indi.get("weather_hum"), indi.get("weather_pres"), 
               indi.get("weather_dew"), indi.get("cpu_temp")]
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row)
            f.flush(); os.fsync(f.fileno())
        
        # --- DATA ARCHIVING: 2. JSON (Spec v1.3.2 Strict Implementation) ---
        def to_float_or_none(val):
            try: return float(val)
            except: return None
        
        camera_model = ex["model"] if ex["model"] else CONFIG["EQUIPMENT"]["camera"]

        json_data = {
            "version": CONFIG["JSON_SPEC"],
            
            "session_id": CONFIG["CONTEXT"]["session"],
            "objective": CONFIG["CONTEXT"]["objective"],
            "equipment": CONFIG["EQUIPMENT"],
            "record": {
                "meta": {
                    "timestamp_jst": shot.timestamp_jst + "+09:00",
                    "timestamp_utc": shot.timestamp_utc + "Z",
                    "unixtime": shot.dt_object.timestamp(),
                    "exposure_actual_sec": round(shot.elapsed_on_ms/1000.0, 3),
                    "shot_mode": shot.shot_mode,
                    "frame_type": CONFIG["CONTEXT"]["frame_type"]
                },
                "file": {
                    "name": shot.filename,
                    "path": CONFIG["SAVE_DIR"],
                    "format": shot.file_format,
                    "size_mb": round(shot.file_size_mb, 2),
                    "width": int(ex["w"]) if ex["w"] else None,
                    "height": int(ex["h"]) if ex["h"] else None
                },
                "exif": {
                    "iso": ex["iso"],
                    "shutter_sec": float(ex["exp"]) if ex["exp"] else round(shot.elapsed_on_ms/1000.0, 3),
                    "model": camera_model,
                    "lat": ex["lat"],
                    "lon": ex["lon"],
                    "alt": ex["alt"]
                },
                "mount": {
                    "ra_deg": indi.get("ra_deg"),
                    "dec_deg": indi.get("dec_deg"),
                    "ra_hms": indi.get("ra_hms"),
                    "dec_dms": indi.get("dec_dms"),
                    "status": indi.get("status", "Unknown"),
                    "side_of_pier": indi.get("side_of_pier", "Unknown")
                },
                "location": {
                    "lat": to_float_or_none(indi.get("lat")),
                    "lon": to_float_or_none(indi.get("lon")),
                    "alt": to_float_or_none(indi.get("alt"))
                },
                "environment": {
                    "temp_c": to_float_or_none(indi.get("weather_temp")),
                    "humidity_pct": to_float_or_none(indi.get("weather_hum")),
                    "pressure_hPa": to_float_or_none(indi.get("weather_pres")),
                    "cpu_temp_c": to_float_or_none(indi.get("cpu_temp"))
                },
                "analysis": {
                    # Placeholder for future Plate-Solving integration
                    "solve_status": "pending",
                    "solved_coords": None,
                    "quality": {
                        "hfr": None,
                        "stars": None,
                        "elongation": None,
                        "satellite_detected": False,
                        "sky_brightness": None
                    }
                }
            }
        }

        # Save the single latest shot metadata
        with open(latest_json_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)
        
        # Update the cumulative history log
        h = []
        if os.path.exists(history_json_file):
            try:
                with open(history_json_file, 'r', encoding='utf-8') as f: h = json.load(f)
            except: h = []
        h.append(json_data)
        with open(history_json_file, 'w', encoding='utf-8') as f:
            json.dump(h, f, indent=4, ensure_ascii=False)
        
        # User notification
        log_msg = f" SP03>> [Logged]: {shot.filename} (Software v{CONFIG['VERSION']} / JSON Spec v{CONFIG['JSON_SPEC']})"
        utils.sp_print(log_msg, CONFIG, level="simple")
        
        
        analysis_queue.task_done()
