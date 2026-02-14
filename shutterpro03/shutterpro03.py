#!/usr/bin/env python3
# =================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 (Main Engine)
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      13.12.0 (JSON Spec v1.3.2 Compliance)
# License:      MIT
# Description:  A professional GPIO-based camera shutter controller 
#               designed for Raspberry Pi. Orchestrates hardware 
#               triggering, INDI telemetry collection, and 
#               automated wireless image downloading via FlashAir.
# =================================================================

__version__ = "13.12.0"
__json_spec__ = "1.3.2"

import os
import sys
import time
import json
import queue
import threading
import requests
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

# Suppress internal logging from exifread to keep console output clean
logging.getLogger('exifread').setLevel(logging.ERROR)

# Raspberry Pi GPIO backend configuration
# Ensures the lgpio factory is used for compatibility with newer Pi hardware/OS
os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"
from gpiozero import LED

# Import project-specific utility and logging modules
import sp03_utils as utils
from sp03_logger import ShotRecord, analyzer_worker

# ==============================================================================
# 1. Global Configuration & Default Settings
# ==============================================================================
# Numerical weights for log level filtering
LOG_LEVELS = {"full": 3, "simple": 2, "off": 1}

CONFIG = {
    # --- SYSTEM HARDWARE & PATHS ---
    
    "VERSION": __version__,       # version no of ShutterPro03
    "JSON_SPEC": __json_spec__,
    
    "GPIO_SHUTTER": 27,           # GPIO pin connected to the shutter relay/optocoupler
    "DEFAULT_BULB_SEC": 10.0,     # Default exposure time for Bulb mode
    "TRIGGER_PULSE_SEC": 1.0,     # Short pulse duration for standard camera trigger
    "SHUTTER_COMPENSATION": 0.35, # Latency offset for mechanical shutter response
    "SHUTTER_OFF_SEC": 1.0,       # Settle time between consecutive shots
    "DISPLAY_MODE": "full",       # Verbosity level of console output
    "TIMEZONE_JST": timezone(timedelta(hours=9)), # Default timezone (Japan Standard Time)
    "FLASHAIR_URL": "http://192.168.50.200",      # IP address of the FlashAir card
    "SAVE_DIR": os.path.expanduser("~/Pictures"), # Local storage path for images
    "LOG_FILE_NAME": "shutter_log.csv",           # Filename for the CSV log
    "LATEST_JSON_NAME": "latest_shot.json",       # Filename for the most recent shot metadata
    "HISTORY_JSON_NAME": "shutter_log.json",      # Filename for the cumulative JSON log
    "LOG_DEST": "s2cur",          # Log destination policy
    "INDI_MOUNT": "LX200 OnStep", # Device name for the INDI Mount
    "INDI_WEATHER": "LX200 OnStep",# Device name for the INDI Weather station
    "PROP_COORD": "EQUATORIAL_EOD_COORD", # INDI property for coordinates
    "PROP_GEO": "GEOGRAPHIC_COORD",       # INDI property for observer location
    "PROP_WEATHER": "WEATHER_PARAMETERS", # INDI property for environmental data

    # --- OBSERVATION CONTEXT ---
    "CONTEXT": {
        "session": "def",         # Session ID (auto-generated if "def")
        "objective": "Test Target",# Name of the celestial target
        "frame_type": "test"      # Type of frame (Light, Dark, Flat, etc.)
    },

    # --- OPTICAL EQUIPMENT METADATA ---
    "EQUIPMENT": {
        "telescope": "N/A",
        "optics": "N/A",
        "filter": "N/A",
        "camera": "Generic Camera",
        "focal_length_mm": 0
    }
}

# ==============================================================================
# 3. Worker Thread: Image Downloader
# ==============================================================================
def downloader_worker(download_queue, analysis_queue, stop_event):
    """
    Background worker that polls the FlashAir card for new images.
    
    This function monitors the latest DCIM directory on the FlashAir card,
    identifies newly created DNG/JPG files, waits for the file write to 
    complete (via size checking), and downloads them to the local SAVE_DIR.
    """
    base_url = CONFIG["FLASHAIR_URL"]
    save_dir = CONFIG["SAVE_DIR"]
    known_files = set() # Track files already processed or existing at startup
    last_target = ""

    while not (stop_event.is_set() and download_queue.empty()):
        target = None
        try:
            # Poll for the latest directory under /DCIM
            r = requests.get(f"{base_url}/command.cgi?op=100&DIR=/DCIM", timeout=5)
            dirs = [l.split(',')[1] for l in r.text.strip().splitlines()[1:] if '_' in l.split(',')[1]]
            if dirs:
                dirs.sort()
                target = f"/DCIM/{dirs[-1]}"
        except: 
            time.sleep(2); continue

        if not target: 
            time.sleep(2); continue
        if target != last_target: 
            last_target = target

        try:
            # List files in the target directory
            r = requests.get(f"{base_url}/command.cgi", params={"op": "100", "DIR": target}, timeout=5)
            if r.status_code == 200:
                for line in r.text.strip().splitlines()[1:]:
                    parts = line.split(',')
                    if len(parts) < 3: continue
                    fname, fsize = parts[1], int(parts[2])
                    full_remote = f"{target}/{fname}"
                    ext = os.path.splitext(fname)[1].lower()

                    # Filter for specific image formats and check for new arrivals
                    if ext in ['.dng', '.jpg'] and full_remote not in known_files:
                        # Skip files existing before the first capture pulse
                        if not known_files and last_target == "":
                            known_files.add(full_remote); continue
                            
                        if not download_queue.empty():
                            # Retrieve telemetry data associated with this capture pulse
                            shot_data = download_queue.get()
                            date_prefix = datetime.now().strftime('%y%m%d')
                            new_fname = f"{date_prefix}_{fname}"
                            local_path = os.path.join(save_dir, new_fname)
                            
                            # Stability Check: Wait until the file size stops increasing
                            current_fsize = fsize
                            for _ in range(25): # Max 25 seconds wait
                                time.sleep(1)
                                try:
                                    chk = requests.get(f"{base_url}/command.cgi", params={"op": "100", "DIR": target}, timeout=5)
                                    new_size = next((int(l.split(',')[2]) for l in chk.text.strip().splitlines() if fname in l), 0)
                                    if new_size > 0 and new_size == current_fsize: break
                                    current_fsize = new_size
                                except: continue
                            
                            utils.sp_print(f"Downloading: {new_fname}", CONFIG, level="full")
                            try:
                                # Fetch the binary content of the image
                                resp = requests.get(f"{base_url}{full_remote}", timeout=60)
                                with open(local_path, 'wb') as f:
                                    f.write(resp.content)
                                    f.flush(); os.fsync(f.fileno())
                                
                                # Update record and pass to the analysis worker
                                shot_data.local_path = local_path
                                shot_data.filename = new_fname
                                shot_data.file_format = ext[1:].upper()
                                shot_data.file_size_mb = current_fsize/1024/1024
                                analysis_queue.put(shot_data)
                                download_queue.task_done()
                                known_files.add(full_remote)
                            except Exception as e:
                                utils.sp_print(f"DL Error: {e}", CONFIG, level="simple")
                                download_queue.put(shot_data) # Return to queue for retry
                        else:
                            # Mark as known even if no pulse was recorded (e.g. manual shot)
                            known_files.add(full_remote)
        except: 
            pass
        time.sleep(1)


# ==============================================================================
# 5. Main Execution Control
# ==============================================================================
def main():
    """
    Main application entry point. Performs initialization, CLI argument 
    processing, and orchestrates the shutter control loop.
    """
    global CONFIG
    
    # Merge external config.json if present
    CONFIG = utils.load_config_file(CONFIG)
    
    # Parse CLI Arguments
    # Separate Key=Value configuration overrides from positional capture parameters
    args_kv = [arg for arg in sys.argv[1:] if "=" in arg]
    args_pos = [arg for arg in sys.argv[1:] if "=" not in arg and not arg.startswith("-")]

    # Display Help Screen
    if "-h" in sys.argv or "--help" in sys.argv:
        utils.print_help(CONFIG); sys.exit(0)

    # Process Configuration Overwrites (Key=Value format)
    for arg in args_kv:
        key, val = [x.strip() for x in arg.split("=", 1)]
        k = key.lower()
        
        # [CONTEXT]
        if k in ["objective", "obj"]:   CONFIG["CONTEXT"]["objective"] = val
        elif k in ["session", "sess"]:  CONFIG["CONTEXT"]["session"] = val
        elif k in ["type", "t"]:        CONFIG["CONTEXT"]["frame_type"] = val
        
        # [EQUIPMENT]
        elif k in ["telescope", "tel"]: CONFIG["EQUIPMENT"]["telescope"] = val
        elif k in ["optics", "opt"]:    CONFIG["EQUIPMENT"]["optics"] = val
        elif k in ["camera", "cam"]:    CONFIG["EQUIPMENT"]["camera"] = val
        elif k in ["filter", "fil"]:    CONFIG["EQUIPMENT"]["filter"] = val
        elif k in ["focal", "f"]:
            try: CONFIG["EQUIPMENT"]["focal_length_mm"] = int(val)
            except: pass
            
        # [SYSTEM / INDI]
        elif k == "dir":      CONFIG["SAVE_DIR"] = os.path.abspath(os.path.expanduser(val))
        elif k == "display":  CONFIG["DISPLAY_MODE"] = val.lower()
        elif k == "log_dest": CONFIG["LOG_DEST"] = val.lower()
        elif k in ["mount", "mnt"]:   CONFIG["INDI_MOUNT"] = val
        elif k in ["weather", "wth"]: CONFIG["INDI_WEATHER"] = val

    # Process Positional Capture Parameters: [shots] [mode] [exposure_sec]
    try:
        target_shots = int(args_pos[0]) if len(args_pos) > 0 else 1
        shot_mode = args_pos[1].lower() if len(args_pos) > 1 else "camera"
        bulb_sec = float(args_pos[2]) if len(args_pos) > 2 else CONFIG["DEFAULT_BULB_SEC"]
    except ValueError:
        print("Error: Invalid arguments.")
        utils.print_help(CONFIG); sys.exit(1)

    # Initialize Session ID if not manually specified
    if CONFIG["CONTEXT"]["session"] == "def":
        CONFIG["CONTEXT"]["session"] = datetime.now().strftime('%Y%m%d_%H%M')

    # Ensure the local save directory exists
    if not os.path.exists(CONFIG["SAVE_DIR"]):
        os.makedirs(CONFIG["SAVE_DIR"], exist_ok=True)

    # Hardware & Multi-threading Setup
    shutter = LED(CONFIG["GPIO_SHUTTER"])
    indi = utils.IndiClient(CONFIG)
    download_q, analysis_q = queue.Queue(), queue.Queue()
    stop_event = threading.Event()

    # Launch background worker threads
    t_down = threading.Thread(target=downloader_worker, args=(download_q, analysis_q, stop_event))
    t_anal = threading.Thread(target=analyzer_worker, args=(analysis_q, stop_event, CONFIG))
    t_down.start(); t_anal.start()

    # Startup Status Report
    utils.sp_print(f"--- ShutterPro03 (v{CONFIG['VERSION']}) Engine Online ---", CONFIG, level="simple")
    utils.sp_print(f"Session: {CONFIG['CONTEXT']['session']} / Target: {CONFIG['CONTEXT']['objective']}", CONFIG, level="simple")
    utils.sp_print(f"Equip: {CONFIG['EQUIPMENT']['telescope']} + {CONFIG['EQUIPMENT']['optics']} ({CONFIG['EQUIPMENT']['focal_length_mm']}mm)", CONFIG, level="simple")

    shot_count = 0
    try:
        # Core Capture Loop
        while (target_shots <= 0) or shot_count < target_shots:
            shot_count += 1
            now_obj = datetime.now(CONFIG["TIMEZONE_JST"])
            ts_jst = now_obj.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            ts_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            
            utils.sp_print(f"[{ts_jst}] Shutter ON ({shot_count}/{'Inf' if target_shots <= 0 else target_shots})", CONFIG, level="simple")
            
            # --- GPIO Triggering Block ---
            start = time.monotonic()
            shutter.on()
            if shot_mode == "bulb":
                # Precise timing for bulb exposure including mechanical compensation
                target_time = start + bulb_sec + CONFIG["SHUTTER_COMPENSATION"]
                while time.monotonic() < target_time: 
                    time.sleep(0.01)
            else:
                # Fixed pulse for camera-controlled exposure
                time.sleep(CONFIG["TRIGGER_PULSE_SEC"])
            shutter.off()
            # -----------------------------
            
            # Record current telemetry and signal the downloader that a file is expected
            download_q.put(ShotRecord(ts_utc, ts_jst, (time.monotonic() - start)*1000, indi.get_observation_data(), shot_mode, now_obj))
            
            # Safety settle time before the next trigger
            time.sleep(CONFIG["SHUTTER_OFF_SEC"])
            if target_shots > 0 and shot_count >= target_shots: 
                break

        # Wait for all background tasks (DL & Logging) to complete
        while not (download_q.empty() and analysis_q.empty()): 
            time.sleep(2)
        
    except KeyboardInterrupt: 
        utils.sp_print("--- Interrupted by User ---", CONFIG, level="simple")
    finally:
        # Graceful Shutdown
        download_q.join()
        analysis_q.join()
        stop_event.set()
        shutter.off()
        t_down.join()
        t_anal.join()
        utils.sp_print(f"--- Finished Session: {CONFIG['CONTEXT']['session']} ---", CONFIG, level="simple")

if __name__ == "__main__":
    main()
