#!/usr/bin/env python3
"""
LogHarmonizer1_6 v1.6.2
Bidirectional synchronization between shutter_log.csv and shutter_log.json.
Modes: [c2j] CSV to JSON (Default), [j2c] JSON to CSV.
Precision synchronization with ShutterPro03, SSE, and StarFlux (v1.6.2 Spec).
"""

import json
import csv
import os
import shutil
import argparse
import sys
from datetime import datetime

class LogHarmonizer:
    # Full mapping definition for v1.6.2 Spec Compliance
    # csv_header: (json_hierarchical_path, display_name)
    MAPPING = {
        "JSON_ver": "version",
        "Session_ID": "session_id",
        "Objective": "objective",
        "Telescope": ("equipment", "telescope"),
        "Opt": ("equipment", "optics"),
        "Filter": ("equipment", "filter"),
        "Camera": ("equipment", "camera"),
        "Aperture": ("equipment", "aperture_mm"),
        "Focal_L": ("equipment", "focal_length_mm"),
        "F_num": ("equipment", "f_number"),
        "Pixel_Size": ("equipment", "pixel_size_um"),
        "Pixel_Scale": ("equipment", "pixel_scale"),
        "LocalTime": ("record", "meta", "iso_timestamp"),
        "UTC_Time": ("record", "meta", "timestamp_utc"),
        "UTC_Offset": ("record", "meta", "utc_offset"),
        "LST": ("record", "meta", "lst_hms"),
        "UnixTime": ("record", "meta", "unixtime"),
        "Sf_Exp_t": ("record", "meta", "exposure_actual_sec"),
        "Diff Sf-Exif": ("record", "meta", "exposure_diff_sec"),
        "Mode": ("record", "meta", "shot_mode"),
        "Type": ("record", "meta", "frame_type"),
        "Filename": ("record", "file", "name"),
        "SavedDir": ("record", "file", "path"),
        "Format": ("record", "file", "format"),
        "FileSize": ("record", "file", "size_mb"),
        "Width": ("record", "file", "width"),
        "Height": ("record", "file", "height"),
        "ISO_Exif": ("record", "exif", "iso"),
        "Exposure_Exif": ("record", "exif", "shutter_sec"),
        "DateTime_Exif": ("record", "exif", "datetime_original"),
        "Model": ("record", "exif", "model"),
        "Lat_Exif": ("record", "exif", "lat"),
        "Lon_Exif": ("record", "exif", "lon"),
        "Alt_Exif": ("record", "exif", "alt"),
        "RA": ("record", "mount", "ra_deg"),
        "DEC": ("record", "mount", "dec_deg"),
        "RA_HMS": ("record", "mount", "ra_hms"),
        "DEC_DMS": ("record", "mount", "dec_dms"),
        "MT_Status": ("record", "mount", "status"),
        "Side": ("record", "mount", "side_of_pier"),
        "HourAngle": ("record", "mount", "hour_angle"),
        "Site_Name": ("record", "location", "site_name"),
        "Lat_INDI": ("record", "location", "latitude"),
        "Lon_INDI": ("record", "location", "longitude"),
        "Alt_INDI": ("record", "location", "elevation"),
        "TZ_Source": ("record", "location", "tz_source"),
        "Temp_Ext_C": ("record", "environment", "temp_c"),
        "Humidity_pct": ("record", "environment", "humidity_pct"),
        "Pressure_hPa": ("record", "environment", "pressure_hPa"),
        "DewPoint_C": ("record", "environment", "dew_point_c"),
        "Mnt_CPU_Temp_C": ("record", "environment", "cpu_temp_mount_c"),
        "RPi_CPU_Temp_C": ("record", "environment", "cpu_temp_rpi_c"),
        "SSE_Version": ("analysis", "SSE", "sse_version"),
        "Solve_Status": ("analysis", "SSE", "solve_status"),
        "Solve_Path": ("analysis", "SSE", "solve_path"),
        "Solve_Confidence": ("analysis", "SSE", "confidence"),
        "Solve_Timestamp": ("analysis", "SSE", "timestamp"),
        "Solve_RA": ("analysis", "SSE", "solved_coords", "ra_deg"),
        "Solve_DEC": ("analysis", "SSE", "solved_coords", "dec_deg"),
        "Solve_Orientation": ("analysis", "SSE", "solved_coords", "orientation"),
        "Solve_RA_hms": ("analysis", "SSE", "solved_coords", "ra_hms"),
        "Solve_DEC_dms": ("analysis", "SSE", "solved_coords", "dec_dms"),
        "Matched_Stars": ("analysis", "SSE", "process_stats", "matched_stars"),
        "Solve_Time_sec": ("analysis", "SSE", "process_stats", "solve_duration_sec"),
        "sf_version": ("analysis", "SF", "sf_version"),
        "sf_status": ("analysis", "SF", "sf_status"),
        "sf_timestamp": ("analysis", "SF", "sf_timestamp"),
        "sf_stars": ("analysis", "SF", "quality", "sf_stars"),
        "sf_fwhm_med": ("analysis", "SF", "quality", "sf_fwhm_med"),
        "sf_fwhm_mean": ("analysis", "SF", "quality", "sf_fwhm_mean"),
        "sf_fwhm_std": ("analysis", "SF", "quality", "sf_fwhm_std"),
        "sf_ell_med": ("analysis", "SF", "quality", "sf_ell_med"),
        "sf_ell_mean": ("analysis", "SF", "quality", "sf_ell_mean"),
        "sf_ell_std": ("analysis", "SF", "quality", "sf_ell_std")
    }

    # Target precision for CSV output (Consistent with ShutterPro03, SSE, and StarFlux)
    PRECISION_MAP = {
        # 8 digits: SSE coordinates
        "Solve_RA": 8, "Solve_DEC": 8,
        # 6 digits: Basic coordinates and offset
        "RA": 6, "DEC": 6, "Lat_INDI": 6, "Lon_INDI": 6, 
        "Lat_Exif": 6, "Lon_Exif": 6, "Diff Sf-Exif": 6,
        # 4 digits: Hour angle
        "HourAngle": 4,
        # 3 digits: Time and Quality stats
        "UnixTime": 3, "Sf_Exp_t": 3, "Exposure_Exif": 3, 
        "sf_fwhm_med": 3, "sf_fwhm_mean": 3, "sf_fwhm_std": 3, 
        "sf_ell_med": 3, "sf_ell_mean": 3, "sf_ell_std": 3,
        # 2 digits: Performance and Reliability
        "Solve_Confidence": 2, "Solve_Orientation": 2, "FileSize": 2, "Pixel_Scale": 2,
        # 1 digit: Environment and Equipment
        "Alt_INDI": 1, "Temp_Ext_C": 1, "Humidity_pct": 1, "Pressure_hPa": 1, 
        "DewPoint_C": 1, "Mnt_CPU_Temp_C": 1, "RPi_CPU_Temp_C": 1, "Alt_Exif": 1, "F_num": 1
    }

    def __init__(self, config_path="config.json", interactive=True):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = script_dir
        config_abs_path = self.resolve_path(config_path)
        
        if os.path.isdir(config_abs_path):
            self.base_dir = config_abs_path
            config_file = os.path.join(config_abs_path, "config.json")
            if not os.path.exists(config_file):
                config_abs_path = os.path.join(script_dir, "config.json")
            else:
                config_abs_path = config_file
        else:
            self.base_dir = os.path.dirname(config_abs_path)
            
        with open(config_abs_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
            
        self.master_json_path = self.resolve_path(self.config["SYSTEM"]["MASTER_JSON"])
        self.edit_csv_path = self.resolve_path(self.config["SYSTEM"]["EDIT_CSV"])
        self.backup_dir = self.resolve_path(self.config["SYSTEM"]["BACKUP_DIR"])
        self.version = "1.6.2" # Enforce 1.6.2
        self.interactive = interactive

    def resolve_path(self, path):
        if path.startswith("~"):
            return os.path.expanduser(path)
        if not os.path.isabs(path):
            return os.path.normpath(os.path.join(self.base_dir, path))
        return path

    def load_json(self):
        if not os.path.exists(self.master_json_path):
            print(f"Error: Master JSON not found at {self.master_json_path}")
            return []
        with open(self.master_json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_csv(self):
        if not os.path.exists(self.edit_csv_path):
            print(f"Error: Edit CSV not found at {self.edit_csv_path}")
            return []
        rows = []
        with open(self.edit_csv_path, 'r', encoding='utf-8-sig') as f: # Use utf-8-sig to handle BOM
            lines = f.readlines()
            # Find the header line (first line without #)
            header_idx = 0
            for i, line in enumerate(lines):
                if not line.startswith("#"):
                    header_idx = i
                    break
            
            f.seek(0)
            for _ in range(header_idx):
                f.readline()
                
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def get_key(self, record):
        """Generate a unique key for record matching."""
        if isinstance(record, dict) and "record" in record:
            name = record.get("record", {}).get("file", {}).get("name")
            ts = record.get("record", {}).get("meta", {}).get("iso_timestamp")
        else:
            name = record.get("Filename")
            ts = record.get("LocalTime")
        
        # Consistent string conversion for keys
        val_name = str(name) if name is not None else ""
        val_ts = str(ts) if (ts is not None and ts != "") else ""
        return f"{val_name}_{val_ts}"

    def create_session_backup(self, mode):
        """Create a backup folder for both JSON and CSV before any modification."""
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)
            
        timestamp = datetime.now().strftime("%y%m%d%H%M") # YYMMDDHHMM
        session_bak_dir = os.path.join(self.backup_dir, f"{timestamp}_{mode}")
        
        if not os.path.exists(session_bak_dir):
            os.makedirs(session_bak_dir)
        
        # Backup JSON if exists
        if os.path.exists(self.master_json_path):
            shutil.copy2(self.master_json_path, session_bak_dir)
        
        # Backup CSV if exists
        if os.path.exists(self.edit_csv_path):
            shutil.copy2(self.edit_csv_path, session_bak_dir)
            
        print(f"Session backup created: {session_bak_dir}")

    def confirm_execution(self, mode):
        """Show summary and confirm before proceeding."""
        source = self.edit_csv_path if mode == "c2j" else self.master_json_path
        target = self.master_json_path if mode == "c2j" else self.edit_csv_path
        mode_desc = "[CSV -> JSON] Sync Edit to Master" if mode == "c2j" else "[JSON -> CSV] Export Master to Edit"
        
        print("\n" + "="*50)
        print(f"  LogHarmonizer1_6 v1.6.2")
        print("="*50)
        print(f"  Mode:   {mode_desc}")
        print(f"  Source: {source}")
        print(f"  Target: {target}")
        print("="*50)
        
        if self.interactive:
            ans = input("\nProceed with this operation? [y/N]: ").strip().lower()
            if ans != 'y':
                print("Operation cancelled by user.")
                sys.exit(0)

    def get_json_val(self, record, path):
        """Retrieve value from nested dictionary using path tuple."""
        if isinstance(path, str):
            return record.get(path)
        
        curr = record
        for key in path:
            if isinstance(curr, dict) and key in curr:
                curr = curr[key]
            else:
                return None
        return curr

    def set_json_val(self, record, path, value):
        """Set value in nested dictionary using path tuple. Creates sub-dicts if missing."""
        if isinstance(path, str):
            record[path] = value
            return

        curr = record
        for i, key in enumerate(path[:-1]):
            if key not in curr or not isinstance(curr[key], dict):
                curr[key] = {}
            curr = curr[key]
        
        # Determine value type (convert if possible)
        try:
            if value == "" or value is None:
                final_val = None
            elif "." in value:
                final_val = float(value)
            elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
                final_val = int(value)
            else:
                final_val = value
        except:
            final_val = value
            
        curr[path[-1]] = final_val

    def create_json_record(self, csv_row):
        """Convert a CSV row to a new JSON record structure using mapping."""
        rec = {"version": self.version}
        for csv_key, json_path in self.MAPPING.items():
            val = csv_row.get(csv_key)
            if val is not None and val != "":
                self.set_json_val(rec, json_path, val)
        
        # Ensure minimal structure for analysis if missing
        if "record" not in rec: rec["record"] = {}
        if "analysis" not in rec: 
            rec["analysis"] = {
                "SSE": {
                    "solve_status": "pending",
                    "solved_coords": {},
                    "process_stats": {}
                },
                "SF": {
                    "sf_status": "pending",
                    "quality": {}
                }
            }
        return rec

    def update_json_record(self, json_rec, csv_row):
        """Update existing JSON record fields from CSV row using mapping."""
        for csv_key, json_path in self.MAPPING.items():
            val = csv_row.get(csv_key)
            if val is not None:
                self.set_json_val(json_rec, json_path, val)

    def run_csv_to_json(self):
        self.confirm_execution("c2j")
        print("\nProcessing Synchronize...")
        self.create_session_backup("c2j")

        json_data = self.load_json()
        csv_data = self.load_csv()
        
        json_map = {self.get_key(r): r for r in json_data}
        csv_map = {self.get_key(r): r for r in csv_data}
        processed_keys = set()
        new_json_data = []
        
        updated_count = 0
        added_count = 0
        deleted_count = 0
        ignored_count = 0

        # Preserve order from JSON if possible
        for json_rec in json_data:
            key = self.get_key(json_rec)
            processed_keys.add(key)
            
            if key in csv_map:
                self.update_json_record(json_rec, csv_map[key])
                new_json_data.append(json_rec)
                updated_count += 1
            else:
                if self.interactive:
                    fname = json_rec.get("record", {}).get("file", {}).get("name") or "Unknown"
                    ltime = json_rec.get("record", {}).get("meta", {}).get("iso_timestamp") or "Unknown"
                    print(f"\n[?] Record missing in CSV: {fname} ({ltime})")
                    ans = input("   Action? [D]elete / [M]ark as ignore / [K]eep as is: ").strip().lower()
                else:
                    ans = 'k' # Default to Keep as is for safety

                if ans == 'd':
                    deleted_count += 1
                elif ans == 'm':
                    if "analysis" not in json_rec: json_rec["analysis"] = {}
                    if "SSE" not in json_rec["analysis"]: json_rec["analysis"]["SSE"] = {}
                    json_rec["analysis"]["SSE"]["ignore"] = True
                    new_json_data.append(json_rec)
                    ignored_count += 1
                else:
                    new_json_data.append(json_rec)

        # Add new from CSV
        for csv_row in csv_data:
            # Check if the entire row is empty (just commas)
            if not any(str(v).strip() for v in csv_row.values() if v is not None):
                continue
                
            key = self.get_key(csv_row)
            if key not in processed_keys:
                if self.interactive:
                    fname = csv_row.get('Filename') or csv_row.get('File_Name') or ""
                    ltime = csv_row.get('LocalTime') or csv_row.get('ISO_Timestamp') or ""
                    
                    if not fname and not ltime:
                        preview_items = [f"{k}: {v}" for k, v in csv_row.items() if v and str(v).strip()]
                        preview = ", ".join(preview_items[:5])
                        if len(preview_items) > 5:
                            preview += ", ..."
                        print(f"\n[+] New record found in CSV (Unknown File/Time) -> {preview}")
                    else:
                        print(f"\n[+] New record found in CSV: {fname} ({ltime})")
                        
                    ans = input("   Action? [A]dd to JSON / [S]kip: ").strip().lower()
                else:
                    ans = 'a' # Default to Add to JSON

                if ans == 'a':
                    new_json_data.append(self.create_json_record(csv_row))
                    added_count += 1

        print(f"\nSummary: Updated={updated_count}, Added={added_count}, Deleted={deleted_count}, Ignored={ignored_count}")
        if (updated_count + added_count + deleted_count + ignored_count) > 0:
            if not self.interactive or input("\nSave changes to JSON? [Y]es / [N]o: ").strip().lower() == 'y':
                with open(self.master_json_path, 'w', encoding='utf-8') as f:
                    json.dump(new_json_data, f, indent=4, ensure_ascii=False)
                print("Master JSON updated.")
                
                # Update latest_shot.json
                if new_json_data:
                    latest_name = self.config["SYSTEM"].get("LATEST_JSON", "latest_shot.json")
                    latest_path = os.path.join(os.path.dirname(self.master_json_path), latest_name)
                    with open(latest_path, 'w', encoding='utf-8') as f:
                        json.dump(new_json_data[-1], f, indent=4, ensure_ascii=False)
        else:
            print("No changes to save.")

    def run_json_to_csv(self):
        self.confirm_execution("j2c")
        print("\nProcessing Export...")
        self.create_session_backup("j2c")
        
        json_data = self.load_json()
        if not json_data:
            print("No data in JSON to export.")
            return

        headers = list(self.MAPPING.keys())
        
        # Encoding utf-8-sig for Excel compatibility (adds BOM)
        with open(self.edit_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(f"# OrionFieldStack CSV Log Spec v{self.version}\n")
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            
            for json_rec in json_data:
                row = {}
                for csv_key, json_path in self.MAPPING.items():
                    val = self.get_json_val(json_rec, json_path)
                    
                    if isinstance(val, (int, float)):
                        prec = self.PRECISION_MAP.get(csv_key)
                        if prec is not None:
                            row[csv_key] = f"{val:.{prec}f}"
                        else:
                            row[csv_key] = str(val)
                    elif val is not None:
                        row[csv_key] = val
                    else:
                        row[csv_key] = ""
                        
                writer.writerow(row)
        
        print(f"CSV exported successfully with {len(json_data)} records.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LogHarmonizer1_6 v1.6.2")
    parser.add_argument("-m", "--mode", choices=["c2j", "j2c"], default="c2j", 
                        help="Mode: c2j (CSV to JSON, default), j2c (JSON to CSV)")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--csv", help="Override CSV file path")
    parser.add_argument("--json", help="Override Master JSON file path")
    parser.add_argument("-i", "--interactive", dest="interactive", action="store_true", help="Prompt for each discrepancy (Default)")
    parser.add_argument("--no-interactive", dest="interactive", action="store_false", help="Skip per-file prompts (Batch mode)")
    parser.set_defaults(interactive=True)
    args = parser.parse_args()

    harmonizer = LogHarmonizer(config_path=args.config, interactive=args.interactive)
    
    if args.csv:
        csv_p = harmonizer.resolve_path(args.csv)
        harmonizer.edit_csv_path = csv_p if not os.path.isdir(csv_p) else os.path.join(csv_p, "shutter_log.csv")
        
    if args.json:
        json_p = harmonizer.resolve_path(args.json)
        harmonizer.master_json_path = json_p if not os.path.isdir(json_p) else os.path.join(json_p, "shutter_log.json")

    if args.mode == "c2j":
        harmonizer.run_csv_to_json()
    else:
        harmonizer.run_json_to_csv()
