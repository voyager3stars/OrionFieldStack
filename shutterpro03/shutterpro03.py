#!/usr/bin/env python3
# ==============================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 (Main Engine)
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      14.1.1 (JSON Spec v1.4.1 Compliance)
# License:      MIT
# Description:  A professional GPIO-based camera shutter controller designed 
#               for Raspberry Pi. It orchestrates hardware triggering, 
#               INDI telemetry collection, and automated wireless image 
#               downloading via FlashAir.
# ==============================================================================

__version__ = "14.1.1"
__json_spec__ = "1.4.2"

import os
import sys
import time
import json
import queue
import threading
import requests
import subprocess
import logging
import re
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

# --- External Dependencies ---
# Suppress internal logging from exifread to keep console output clean.
# This prevents library debug noise from cluttering the status display.
logging.getLogger('exifread').setLevel(logging.ERROR)

# --- GPIO Backend Configuration ---
# Forces the use of the 'lgpio' factory. This is critical for compatibility 
# with newer Raspberry Pi hardware (Pi 5) and newer OS versions (Bookworm).
os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"
from gpiozero import LED

# --- Project-Specific Modules ---
# These modules are assumed to be in the same directory or python path.
import sp03_utils as utils
from sp03_logger import ShotRecord, analyzer_worker

# ==============================================================================
# 1. Global Configuration & Default Settings
# ==============================================================================
# Numerical weights for log level filtering to control verbosity.
LOG_LEVELS = {"full": 3, "simple": 2, "off": 1}

CONFIG = {
    # --- SYSTEM HARDWARE & PATHS ---
    "VERSION": __version__,         # Current version of ShutterPro03
    "JSON_SPEC": __json_spec__,     # JSON metadata specification version
    
    "GPIO_SHUTTER": 27,             # GPIO pin (BCM) connected to the shutter relay/optocoupler
    "DEFAULT_BULB_SEC": 10.0,       # Default exposure time for Bulb mode if not specified
    "TRIGGER_PULSE_SEC": 1.0,       # Duration of the trigger pulse for standard (non-Bulb) shots
    "SHUTTER_COMPENSATION": 0.35,   # Latency offset to account for mechanical shutter lag
    "SHUTTER_OFF_SEC": 1.0,         # Mandatory settle time/cooldown between consecutive shots
    "DISPLAY_MODE": "full",         # Verbosity level of console output (full/simple/off)
    
    # Network & Storage
    "FLASHAIR_URL": "http://192.168.50.200",      # IP address of the FlashAir W-04 card
    "SAVE_DIR": os.path.expanduser("~/Pictures"), # Local directory to save downloaded images
    "LOG_FILE_NAME": "shutter_log.csv",           # Filename for the CSV session log
    "LATEST_JSON_NAME": "latest_shot.json",       # Filename for the most recent shot's metadata
    "HISTORY_JSON_NAME": "shutter_log.json",      # Filename for the cumulative JSON log
    "LOG_DEST": "s2cur",                          # Log destination policy (e.g., specific folder structure)

    # --- INDI SERVER SETTINGS ---
    "INDI_MOUNT": "LX200 OnStep",           # Device name for the Telescope Mount in INDI
    "INDI_WEATHER": "LX200 OnStep",         # Device name for the Weather station/Sensor in INDI
    "PROP_COORD": "EQUATORIAL_EOD_COORD",   # INDI property key for RA/DEC coordinates
    "PROP_GEO": "GEOGRAPHIC_COORD",         # INDI property key for observer location (Lat/Lon)
    "PROP_WEATHER": "WEATHER_PARAMETERS",   # INDI property key for environmental data (Temp/Pres)
    
    # Default Location Fallbacks (used if INDI is unavailable)
    "DEFAULT_SITE_NAME": "Akashi Municipal Planetarium (JST Meridian)",
    "LAST_LATITUDE": 34.6493,
    "LAST_LONGITUDE": 135.0015,
    "LAST_ELEVATION": 54.0,

    # --- OBSERVATION CONTEXT ---
    # Metadata describing the current imaging session.
    "CONTEXT": {
        "session": "def",           # Session ID (auto-generated timestamp if "def")
        "objective": "Test Target", # Name of the celestial target being imaged
        "frame_type": "test"        # Type of frame (Light, Dark, Flat, Bias, Test)
    },

    # --- OPTICAL EQUIPMENT METADATA ---
    # Used for calculating FOV, image scale, and logging context.
    "EQUIPMENT": {
        "telescope": "N/A",
        "optics": "N/A",
        "filter": "N/A",
        "camera": "Generic Camera", 
        "focal_length_mm": 800,
        "aperture_mm": 200,         
        "pixel_size_um": 4.88       
    }
}

# ==============================================================================
# 2. Worker Thread: Image Downloader
# ==============================================================================
def downloader_worker(download_queue, analysis_queue, stop_event):
    """
    Background worker that polls the FlashAir card for new images.
    
    This function monitors the latest DCIM directory on the FlashAir card.
    It identifies newly created DNG/JPG files, waits for the camera to finish 
    writing (by monitoring file size stability), and downloads them to the 
    local SAVE_DIR.
    
    Args:
        download_queue (Queue): Receives 'ShotRecord' objects from the main thread 
                                when a shutter trigger occurs.
        analysis_queue (Queue): Sends completed 'ShotRecord' objects (with file paths) 
                                to the analysis/logger thread.
        stop_event (Event): Threading event to signal shutdown.
    """
    base_url = CONFIG["FLASHAIR_URL"]
    save_dir = CONFIG["SAVE_DIR"]
    known_files = set() # Keeps track of files we have already seen or processed
    last_target = ""    # The last DCIM directory we scanned

    while not (stop_event.is_set() and download_queue.empty()):
        target = None
        try:
            # Step 1: Discover the latest directory (e.g., 100__TSB) under /DCIM
            # FlashAir command op=100 lists files/dirs.
            r = requests.get(f"{base_url}/command.cgi?op=100&DIR=/DCIM", timeout=5)
            # Parse response to find directories (usually containing '_')
            dirs = [l.split(',')[1] for l in r.text.strip().splitlines()[1:] if '_' in l.split(',')[1]]
            if dirs:
                dirs.sort()
                target = f"/DCIM/{dirs[-1]}" # Select the last (newest) directory
        except Exception: 
            # Connection glitch or timeout; wait and retry
            time.sleep(2); continue

        if not target: 
            time.sleep(2); continue
            
        # Optimization: Only reset/log if the directory has changed
        if target != last_target: 
            last_target = target

        try:
            # Step 2: List files in the target directory
            r = requests.get(f"{base_url}/command.cgi", params={"op": "100", "DIR": target}, timeout=5)
            if r.status_code == 200:
                for line in r.text.strip().splitlines()[1:]:
                    parts = line.split(',')
                    if len(parts) < 3: continue
                    
                    fname = parts[1]
                    fsize = int(parts[2])
                    full_remote = f"{target}/{fname}"
                    ext = os.path.splitext(fname)[1].lower()

                    # Step 3: Filter for valid image formats (RAW/DNG/JPG)
                    if ext in ['.dng', '.jpg'] and full_remote not in known_files:
                        
                        # Startup Condition: If this is the first scan, just mark existing files 
                        # as 'known' so we don't download old photos from the card.
                        if not known_files and last_target == "":
                            known_files.add(full_remote); continue
                            
                        # If the main thread has signaled a shot was taken...
                        if not download_queue.empty():
                            # Retrieve the metadata (ShotRecord) associated with this capture
                            shot_data = download_queue.get()
                            
                            # Create a local filename: YYMMDD_OriginalName.ext
                            date_prefix = datetime.now().strftime('%y%m%d')
                            new_fname = f"{date_prefix}_{fname}"
                            local_path = os.path.join(save_dir, new_fname)
                            
                            # Step 4: Stability Check (Wait for write completion)
                            # Cameras take time to write large RAW files. We poll the file size
                            # until it stops changing.
                            current_fsize = fsize
                            # Max wait: 25 seconds
                            for _ in range(25): 
                                time.sleep(1)
                                try:
                                    chk = requests.get(f"{base_url}/command.cgi", params={"op": "100", "DIR": target}, timeout=5)
                                    # Parse the size of the specific file again
                                    new_size = next((int(l.split(',')[2]) for l in chk.text.strip().splitlines() if fname in l), 0)
                                    # If size is > 0 and hasn't changed since last second, it's done.
                                    if new_size > 0 and new_size == current_fsize: 
                                        break
                                    current_fsize = new_size
                                except: continue
                            
                            utils.sp_print(f"Downloading: {new_fname}", CONFIG, level="full")
                            
                            try:
                                # Step 5: Download the binary content
                                resp = requests.get(f"{base_url}{full_remote}", timeout=60)
                                with open(local_path, 'wb') as f:
                                    f.write(resp.content)
                                    # Ensure data is physically written to disk
                                    f.flush()
                                    os.fsync(f.fileno())
                                
                                # Step 6: Update ShotRecord and pass to Analysis/Logger
                                shot_data.local_path = local_path
                                shot_data.filename = new_fname
                                shot_data.file_format = ext[1:].upper()
                                shot_data.file_size_mb = current_fsize / (1024 * 1024)
                                
                                analysis_queue.put(shot_data)
                                download_queue.task_done()
                                known_files.add(full_remote)
                                
                            except Exception as e:
                                utils.sp_print(f"Download Error: {e}", CONFIG, level="simple")
                                # If download fails, return the task to queue to retry (risky if file is corrupt)
                                download_queue.put(shot_data) 
                        else:
                            # Use Case: Manual shutter release (not via script).
                            # We mark it as known to ignore it, or we could auto-download without metadata.
                            # Current logic: Ignore manual shots.
                            pass
                            known_files.add(full_remote)
        except Exception: 
            pass
        
        # Idle briefy before next poll
        time.sleep(1)


# ==============================================================================
# 3. Main Execution Control
# ==============================================================================
def main():
    """
    Main application entry point. 
    1. Loads configuration.
    2. Parses CLI arguments.
    3. Initializes hardware (GPIO) and Network (INDI).
    4. Runs the capture loop (Trigger -> Wait -> Telemetry -> Queue).
    """
    global CONFIG
    

    # Load external config.json if present to override defaults
    CONFIG = utils.load_config_file(CONFIG)
    
    # --- Argument Parsing ---
    # Separate "Key=Value" configuration overrides from positional capture parameters.
    # Example: python3 shutterpro03.py 10 bulb 300 target=Andromeda
    args_kv = [arg for arg in sys.argv[1:] if "=" in arg]
    args_pos = [arg for arg in sys.argv[1:] if "=" not in arg and not arg.startswith("-")]

    # Display Help Screen
    if "-h" in sys.argv or "--help" in sys.argv:
        utils.print_help(CONFIG); sys.exit(0)

    # Process Configuration Overrides (Key=Value format)
    for arg in args_kv:
        key, val = [x.strip() for x in arg.split("=", 1)]
        k = key.lower()
        
        # [CONTEXT] Session/Target info
        if k in ["objective", "obj"]:   CONFIG["CONTEXT"]["objective"] = val
        elif k in ["session", "sess"]:  CONFIG["CONTEXT"]["session"] = val
        elif k in ["type", "t"]:        CONFIG["CONTEXT"]["frame_type"] = val
        
        # [EQUIPMENT] Telescope/Camera info
        elif k in ["telescope", "tel"]: CONFIG["EQUIPMENT"]["telescope"] = val
        elif k in ["optics", "opt"]:    CONFIG["EQUIPMENT"]["optics"] = val
        elif k in ["camera", "cam"]:    CONFIG["EQUIPMENT"]["camera"] = val
        elif k in ["filter", "fil"]:    CONFIG["EQUIPMENT"]["filter"] = val
        elif k in ["focal", "f"]:
            try: CONFIG["EQUIPMENT"]["focal_length_mm"] = int(val)
            except: pass
            
        # [SYSTEM / INDI] Hardware & Paths
        elif k == "dir":      CONFIG["SAVE_DIR"] = os.path.abspath(os.path.expanduser(val))
        elif k == "display":  CONFIG["DISPLAY_MODE"] = val.lower()
        elif k == "log_dest": CONFIG["LOG_DEST"] = val.lower()
        elif k in ["mount", "mnt"]:   CONFIG["INDI_MOUNT"] = val
        elif k in ["weather", "wth"]: CONFIG["INDI_WEATHER"] = val

    # Process Positional Capture Parameters: [shots] [mode] [exposure_sec]
    try:
        # Arg 1: Number of shots (Default: 1)
        target_shots = int(args_pos[0]) if len(args_pos) > 0 else 1
        # Arg 2: Mode (camera/bulb) (Default: camera)
        shot_mode = args_pos[1].lower() if len(args_pos) > 1 else "camera"
        # Arg 3: Bulb Duration in seconds (Default: Config value)
        bulb_sec = float(args_pos[2]) if len(args_pos) > 2 else CONFIG["DEFAULT_BULB_SEC"]
    except ValueError:
        print("Error: Invalid arguments provided.")
        utils.print_help(CONFIG); sys.exit(1)

    # Initialize Session ID if not manually specified (Format: YYYYMMDD_HHMM)
    if CONFIG["CONTEXT"]["session"] == "def":
        CONFIG["CONTEXT"]["session"] = datetime.now().strftime('%Y%m%d_%H%M')

    # Ensure the local save directory exists
    if not os.path.exists(CONFIG["SAVE_DIR"]):
        os.makedirs(CONFIG["SAVE_DIR"], exist_ok=True)

    # --- Hardware & Threading Setup ---
    shutter = LED(CONFIG["GPIO_SHUTTER"])

    # Startup Status Report
    utils.sp_print(f"=== ShutterPro03 (v{CONFIG['VERSION']}) === Engine Online =============", CONFIG, level="simple")
    utils.sp_print(f" - Session: {CONFIG['CONTEXT']['session']} / Target: {CONFIG['CONTEXT']['objective']}", CONFIG, level="simple")
    utils.sp_print(f" - Equip: {CONFIG['EQUIPMENT']['telescope']} + {CONFIG['EQUIPMENT']['optics']} ({CONFIG['EQUIPMENT']['focal_length_mm']}mm)", CONFIG, level="simple")
    utils.sp_print(f"==========================================================", CONFIG, level="simple")
    
    ## --- Communication with INDI
    utils.sp_print("...Connecting to INDI server and waiting for devices...", CONFIG, level="simple")
    
    try:
        indi = utils.IndiClient(CONFIG)
        # To attempt device connection internally, perform a test acquisition here.
        test_data = indi.get_observation_data()
        
        if test_data:
            # When data is available
            utils.sp_print("...INDI connection established successfully.", CONFIG, level="simple")
        else:
            # When data is empty (e.g., device not found)
            utils.sp_print("...INDI connection warning: Server responded but no device data found.", CONFIG, level="simple")
    except Exception as e:
        utils.sp_print(f"...INDI connection failed: {e}", CONFIG, level="simple")

    # ------------------------------------------------------------------
    
    download_q, analysis_q = queue.Queue(), queue.Queue()
    stop_event = threading.Event()

    # Launch background worker threads
    # t_down: Handles FlashAir downloading
    # t_anal: Handles EXIF analysis and CSV logging
    t_down = threading.Thread(target=downloader_worker, args=(download_q, analysis_q, stop_event))
    t_anal = threading.Thread(target=analyzer_worker, args=(analysis_q, stop_event, CONFIG))
    t_down.start(); t_anal.start()


    shot_count = 0
    try:
        # --- Core Capture Loop ---
        while (target_shots <= 0) or shot_count < target_shots:
            shot_count += 1
            
            # --- 1. Acquire Telemetry ---
            # Fetch current coordinates, weather, etc. from INDI
            obs_data = indi.get_observation_data()

            # --- 2. Calculate Timezone-aware Local Time ---
            now_utc = datetime.now(timezone.utc)
            try:
                # Robustly parse the UTC offset string (e.g., "+09:00" or "-05:30")
                offset_str = obs_data.get('utc_offset', "+00:00")
                # Parse hour and minute parts safely
                match = re.match(r"([+-])(\d{2}):(\d{2})", offset_str)
                if match:
                    sign = 1 if match.group(1) == '+' else -1
                    h_off = int(match.group(2)) * sign
                    m_off = int(match.group(3)) * sign
                    tz_delta = timedelta(hours=h_off, minutes=m_off if h_off >= 0 else -m_off)
                    current_tz = timezone(tz_delta)
                else:
                    # Fallback to UTC if format is unrecognized
                    current_tz = timezone.utc
            except Exception:
                current_tz = timezone.utc

            now_local = now_utc.astimezone(current_tz)
            
            # Construct ISO 8601 Timestamp: e.g., 2026-02-15T20:24:00.123+09:00
            iso_timestamp = now_local.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + obs_data.get('utc_offset', "+00:00")
            ts_utc_str = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + "Z"
            
            utils.sp_print(f"[{iso_timestamp}] Shutter ON ({shot_count}/{'Inf' if target_shots <= 0 else target_shots})", CONFIG, level="simple")
            
            # --- 3. GPIO Triggering Block ---
            start = time.monotonic()
            shutter.on()
            
            if shot_mode == "bulb":
                # BULB MODE:
                # Hold the shutter open for the specified duration.
                # 'SHUTTER_COMPENSATION' adjusts for mechanical latency.
                target_time = start + bulb_sec + CONFIG["SHUTTER_COMPENSATION"]
                while time.monotonic() < target_time: 
                    time.sleep(0.01) # Short sleep to prevent CPU hogging
            else:
                # CAMERA MODE:
                # Send a short pulse; Camera determines exposure time internally.
                time.sleep(CONFIG["TRIGGER_PULSE_SEC"])
                
            shutter.off()
            actual_exposure_ms = (time.monotonic() - start) * 1000
            # -----------------------------
            
            # --- 4. Queue for Processing ---
            # Create a ShotRecord and push it to the Downloader Queue.
            # The Downloader will pick this up and look for the corresponding file on FlashAir.
            download_q.put(ShotRecord(
                ts_utc_str, 
                iso_timestamp, 
                actual_exposure_ms, 
                obs_data, 
                shot_mode, 
                now_local
            ))
            
            # Mandatory cool-down period between shots to ensure camera buffer clears
            time.sleep(CONFIG["SHUTTER_OFF_SEC"])
            
            # Check exit condition
            if target_shots > 0 and shot_count >= target_shots: 
                break
                
        # --- Cleanup ---
        utils.sp_print("Waiting for background tasks to complete...", CONFIG, level="simple")
        
        # 1. まず、キューに仕事が入るのを少し待つ (FlashAirの検知ラグ対策)
        time.sleep(3)
        
        # 2. キューが空になるまで待機
        while not (download_q.empty() and analysis_q.empty()):
            time.sleep(1)

    except KeyboardInterrupt:
        utils.sp_print("\n--- Interrupted by User (Ctrl+C) ---", CONFIG, level="simple")
    finally:
        # --- ここが重要：以前のバージョンのロジックを適用 ---
        
        # シャッターを確実にオフにする
        shutter.off()

        # stop_eventをセットする「前」に、キューの完了を待つ
        # これにより、解析スレッドが最後の仕事を終えるまで待機させます
        download_q.join()
        analysis_q.join()

        # すべて終わってからスレッドを停止させる
        stop_event.set()

        # スレッドの完全終了を待つ
        if t_down.is_alive(): t_down.join(timeout=5.0)
        if t_anal.is_alive(): t_anal.join(timeout=5.0)
        
        utils.sp_print(f"### Finished Session: {CONFIG['CONTEXT']['session']} ###", CONFIG, level="simple")

if __name__ == "__main__":
    main()
