# =================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 Utils
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      13.12.0
# License:      MIT
# Description:  Core utility module providing INDI client capabilities,
#               coordinate conversion (decimal to HMS/DMS), colorized
#               console logging, and configuration management.
# =================================================================

import os
import sys
import json
import time
import subprocess
from datetime import datetime

class IndiClient:
    """
    IndiClient handles communication with an INDI server via shell commands.
    It retrieves astronomical telemetry such as coordinates, pier side, 
    and environmental data using 'indi_getprop'.
    """
    def __init__(self, config):
        """
        Initializes the client with a reference to the global configuration.
        """
        self.config = config  # Stores the configuration internally for property mapping
    
    def _get_prop(self, device, property_name, element_name):
        """
        Internal method to fetch a single property value from the INDI server.
        
        Uses a subprocess to call 'indi_getprop' with a 1-second timeout
        to prevent the entire application from hanging on network issues.
        """
        full_prop = f"{device}.{property_name}.{element_name}"
        try:
            # Executes the command: indi_getprop -1 <device>.<property>.<element>
            result = subprocess.run(
                ["indi_getprop", "-1", full_prop], 
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, 
                text=True, timeout=1
            )
            # Parse the output which typically looks like "device.property.element=value"
            if result.returncode == 0 and "=" in result.stdout: 
                return result.stdout.strip().split("=")[1]
        except: 
            pass
        return None

    def _to_hms(self, val):
        """
        Converts a decimal hour value to a formatted HH:MM:SS string.
        Typically used for Right Ascension (RA).
        """
        if val is None: return "00:00:00"
        try:
            val = float(val)
            h = int(val)
            m = int((val - h) * 60)
            s = int((((val - h) * 60) - m) * 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        except: 
            return "00:00:00"

    def _to_dms(self, val):
        """
        Converts a decimal degree value to a formatted +DD:MM:SS string.
        Typically used for Declination (DEC) or geographic latitude/longitude.
        """
        if val is None: return "00:00:00"
        try:
            val = float(val)
            sign = "-" if val < 0 else "+"
            val = abs(val)
            d = int(val)
            m = int((val - d) * 60)
            s = int((((val - d) * 60) - m) * 60)
            return f"{sign}{d:02d}:{m:02d}:{s:02d}"
        except: 
            return "+00:00:00"

    def get_observation_data(self):
        """
        Aggregates all relevant telemetry data from the mount and weather station.
        
        Returns:
            dict: A collection of current astronomical and environmental parameters.
        """
        mount = self.config["INDI_MOUNT"]
        weather = self.config["INDI_WEATHER"]
        
        # Retrieve raw RA/DEC values
        ra_raw = self._get_prop(mount, self.config["PROP_COORD"], "RA")
        dec_raw = self._get_prop(mount, self.config["PROP_COORD"], "DEC")
        ra_val = float(ra_raw) if ra_raw else None
        dec_val = float(dec_raw) if dec_raw else None

        # Build the telemetry dictionary
        data = {
            "ra": ra_raw, 
            "dec": dec_raw,
            "ra_deg": ra_val * 15.0 if ra_val else None, # RA hours to degrees
            "dec_deg": dec_val,
            "ra_hms": self._to_hms(ra_val),
            "dec_dms": self._to_dms(dec_val),
            "status": self._get_prop(mount, "EQUATORIAL_EOD_COORD", "STATE"),
            "side_of_pier": self._get_prop(mount, "SIDE_OF_PIER", "PIER_SIDE"),
            "lat": self._get_prop(mount, self.config["PROP_GEO"], "LAT"), 
            "lon": self._get_prop(mount, self.config["PROP_GEO"], "LONG"),
            "alt": self._get_prop(mount, self.config["PROP_GEO"], "ELEV"), 
            "weather_temp": self._get_prop(weather, self.config["PROP_WEATHER"], "WEATHER_TEMPERATURE"),
            "weather_hum": self._get_prop(weather, self.config["PROP_WEATHER"], "WEATHER_HUMIDITY"), 
            "weather_pres": self._get_prop(weather, self.config["PROP_WEATHER"], "WEATHER_BAROMETER"),
            "weather_dew": self._get_prop(weather, self.config["PROP_WEATHER"], "WEATHER_DEWPOINT"), 
            "cpu_temp": self._get_prop(weather, self.config["PROP_WEATHER"], "WEATHER_CPU_TEMPERATURE")
        }
        return data

def sp_print(message, config, level="full"):
    """
    ShutterPro-specific colorized print function.
    
    Filters output based on the user-defined DISPLAY_MODE in CONFIG.
    
    Args:
        message (str): The string to be displayed.
        config (dict): Global configuration containing DISPLAY_MODE.
        level (str): Importance of the message ("full", "simple", "off").
    """
    # Define priority weights for log level filtering
    LOG_LEVELS = {"full": 3, "simple": 2, "off": 1}
    
    # Get current mode, default to 'full' if unspecified
    current_mode = config.get("DISPLAY_MODE", "full")
    
    # Display logic: Show message only if its level is within the current threshold
    if LOG_LEVELS.get(current_mode, 3) >= LOG_LEVELS.get(level, 3):
        if current_mode == "off":
            return
            
        # ANSI Escape Sequences for orange color output (256-color palette index 208)
        print(f"\033[38;5;208m SP03>> {message}\033[0m")

def print_help(config):
    """
    Displays the interactive help menu with colorized keys and current values.
    Provides a quick overview of command-line arguments and current settings.
    """
    
    # Formatting for the session ID display
    C_RESET, C_HEAD, C_KEY, C_VAL = "\033[0m", "\033[1;36m", "\033[32m", "\033[36m"
    
    sw_ver = config.get('VERSION', 'unknown')
    js_ver = config.get('JSON_SPEC', 'unknown')
    
    print(f"{C_HEAD}ShutterPro03 (v{sw_ver} / JSON Spec v{js_ver}) - Interactive Help{C_RESET}")
    print(f"Default settings loaded from 'config.json'. Arguments override these values.\n")

    print(f"{C_HEAD}[USAGE]{C_RESET}")
    print(f"  python3 shutterpro03.py [shots] [mode] [exposure_sec] [options...]\n")
    print(f"  Example (10 shots, 60s Bulb, Target M42, Telescope R200SS):")
    print(f"    python3 shutterpro03.py 10 bulb 60 obj=M42 tel=R200SS t=Light\n")

    def p_opt(key, desc, current):
        print(f"  {C_KEY}{key:<20}{C_RESET}: {desc:<35}{C_VAL}[Current: {current}]{C_RESET}")

    print(f" {C_HEAD}[CONTEXT]{C_RESET}")
    p_opt("objective (obj)=", "Target name / Object ID", config['CONTEXT']['objective'])
    p_opt("session (sess)=",  "Unique Session ID (auto if 'def')", config['CONTEXT']['session'])
    p_opt("type (t)=",        "Frame type (Light/Dark/Flat/Bias)", config['CONTEXT']['frame_type'])

    print(f"\n {C_HEAD}[EQUIPMENT]{C_RESET}")
    p_opt("telescope (tel)=", "Telescope / OTA model name", config['EQUIPMENT']['telescope'])
    p_opt("optics (opt)=",    "Corrector / Reducer / Barlow", config['EQUIPMENT']['optics'])
    p_opt("filter (fil)=",    "Filter name (e.g. L-Pro, Ha)", config['EQUIPMENT']['filter'])
    p_opt("camera (cam)=",    "Imaging camera model", config['EQUIPMENT']['camera'])
    p_opt("focal (f)=",       "Effective focal length (mm)", config['EQUIPMENT']['focal_length_mm'])

    print(f"\n {C_HEAD}[SYSTEM]{C_RESET}")
    p_opt("dir=",             "Image download directory", config['SAVE_DIR'])
    p_opt("display=",         "Log verbosity (full/simple/off)", config['DISPLAY_MODE'])
    p_opt("log_dest=",        "Log Destination Policy", config['LOG_DEST'])
    print(f"                       - s2cur : Save logs in Current Directory")
    print(f"                       - s2save: Save logs in Image Download Directory")

    print(f"\n {C_HEAD}[INDI PROPERTIES]{C_RESET}")
    p_opt("mount (mnt)=",     "INDI Mount device driver name", config['INDI_MOUNT'])
    p_opt("weather (wth)=",   "INDI Weather station device name", config['INDI_WEATHER'])
    print("")

def load_config_file(base_config):
    """
    Attempts to find and load 'config.json' from the script's directory.
    If found, it merges the external file into the base_config dictionary.
    
    Returns:
        dict: The updated configuration with external overrides.
    """
    # Resolve path to config.json relative to the utility file
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                ext_conf = json.load(f)
            
            # 1. Selective overwrite of the SYSTEM section
            if "SYSTEM" in ext_conf:
                for k, v in ext_conf["SYSTEM"].items():
                    # Only overwrite existing keys to prevent config corruption
                    if k in base_config:
                        base_config[k] = v
                    # Expand user path (e.g., '~') if the key is SAVE_DIR
                    if k == "SAVE_DIR":
                        base_config["SAVE_DIR"] = os.path.expanduser(v)
            
            # 2. Update CONTEXT section (Session, Target, etc.)
            if "CONTEXT" in ext_conf:
                base_config["CONTEXT"].update(ext_conf["CONTEXT"])
            
            # 3. Update EQUIPMENT section (Telescope, Camera, etc.)
            if "EQUIPMENT" in ext_conf:
                base_config["EQUIPMENT"].update(ext_conf["EQUIPMENT"])
                
        except Exception as e:
            # Fallback to standard print to avoid recursive dependency on sp_print
            print(f" SP03>> Error loading config.json: {e}")
    
    return base_config
