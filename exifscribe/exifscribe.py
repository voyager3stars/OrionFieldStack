#!/usr/bin/env python3
"""
ExifScribe v1.0.0
Reads EXIF metadata from DNG files and patches shutter_log.json
(record.exif / record.file sections only).

Features:
  - Case-insensitive filename matching between DNG files and JSON entries
  - Session-based backup before any modification
  - Interactive per-file resolution for mismatches, missing files, and new entries
  - --dry-run mode: preview only, no changes made
  - --force mode: re-process all fields even if already filled
  - Does NOT modify record.analysis, record.mount, or any other sections
"""

import json
import os
import shutil
import argparse
import sys
import tty
import termios
from datetime import datetime
from fractions import Fraction

try:
    import exifread
except ImportError:
    print("Error: 'exifread' library is required.")
    print("  Install with: pip install exifread")
    sys.exit(1)

VERSION = "1.6.0"

# ---------------------------------------------------------------------------
# Constants & Mappings
# ---------------------------------------------------------------------------

EXIF_FIELD_MAP = {
    # exif_key: (json section path, field name)
    "iso":               ("record", "exif", "iso"),
    "shutter_sec":       ("record", "exif", "shutter_sec"),
    "datetime_original": ("record", "exif", "datetime_original"),
    "model":             ("record", "exif", "model"),
    "lat":               ("record", "exif", "lat"),
    "lon":               ("record", "exif", "lon"),
    "alt":               ("record", "exif", "alt"),
    "width":             ("record", "file", "width"),
    "height":            ("record", "file", "height"),
    "size_mb":           ("record", "file", "size_mb"),
}


# ---------------------------------------------------------------------------
# EXIF extraction
# ---------------------------------------------------------------------------

def _ratio_to_float(value):
    """Convert an IFDRational or Ratio or string fraction to float."""
    try:
        # exifread returns objects with .num and .den
        return float(value.num) / float(value.den)
    except AttributeError:
        pass
    try:
        return float(Fraction(str(value)))
    except Exception:
        return None


def _dms_to_decimal(dms_values, ref):
    """Convert GPS DMS list [deg, min, sec] and ref string to signed decimal degrees."""
    try:
        d = _ratio_to_float(dms_values[0])
        m = _ratio_to_float(dms_values[1])
        s = _ratio_to_float(dms_values[2])
        if None in (d, m, s):
            return None
        decimal = d + m / 60.0 + s / 3600.0
        if ref in ('S', 'W'):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def extract_exif(filepath):
    """
    Extract EXIF fields from a DNG/RAW file.
    Returns a dict with keys matching the JSON spec:
        iso, shutter_sec, datetime_original, model,
        lat, lon, alt, width, height, size_mb
    Missing fields are represented as None (not written to JSON).
    """
    result = {}

    # File size (always available)
    try:
        size_bytes = os.path.getsize(filepath)
        result["size_mb"] = round(size_bytes / (1024 * 1024), 2)
    except Exception:
        result["size_mb"] = None

    try:
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f, details=False)
    except Exception as e:
        print(f"  [Error] Failed to read EXIF from {filepath}: {e}")
        return result

    # ISO
    iso_tag = tags.get("EXIF ISOSpeedRatings")
    if iso_tag:
        try:
            result["iso"] = int(str(iso_tag))
        except Exception:
            result["iso"] = None

    # Shutter speed
    exp_tag = tags.get("EXIF ExposureTime")
    if exp_tag:
        val = _ratio_to_float(exp_tag.values[0]) if hasattr(exp_tag, 'values') else _ratio_to_float(exp_tag)
        result["shutter_sec"] = round(val, 3) if val is not None else None

    # DateTimeOriginal
    dt_tag = tags.get("EXIF DateTimeOriginal")
    if dt_tag:
        result["datetime_original"] = str(dt_tag)

    # Camera model
    model_tag = tags.get("Image Model")
    if model_tag:
        result["model"] = str(model_tag).strip()

    # GPS Latitude
    lat_tag = tags.get("GPS GPSLatitude")
    lat_ref_tag = tags.get("GPS GPSLatitudeRef")
    if lat_tag and lat_ref_tag:
        lat = _dms_to_decimal(lat_tag.values, str(lat_ref_tag))
        result["lat"] = round(lat, 6) if lat is not None else None

    # GPS Longitude
    lon_tag = tags.get("GPS GPSLongitude")
    lon_ref_tag = tags.get("GPS GPSLongitudeRef")
    if lon_tag and lon_ref_tag:
        lon = _dms_to_decimal(lon_tag.values, str(lon_ref_tag))
        result["lon"] = round(lon, 6) if lon is not None else None

    # GPS Altitude
    alt_tag = tags.get("GPS GPSAltitude")
    alt_ref_tag = tags.get("GPS GPSAltitudeRef")
    if alt_tag:
        alt_val = _ratio_to_float(alt_tag.values[0]) if hasattr(alt_tag, 'values') else _ratio_to_float(alt_tag)
        if alt_val is not None:
            # Ref: 0 = above sea level, 1 = below
            if alt_ref_tag and str(alt_ref_tag) == "1":
                alt_val = -alt_val
            result["alt"] = round(alt_val, 1)

    # Image dimensions: prefer full-resolution Image tags over EXIF (which may be thumbnail)
    # Priority: Image ImageWidth > EXIF ExifImageWidth
    w_tag = tags.get("Image ImageWidth") or tags.get("EXIF ExifImageWidth")
    h_tag = tags.get("Image ImageLength") or tags.get("EXIF ExifImageLength")
    if w_tag:
        try:
            result["width"] = int(str(w_tag))
        except Exception:
            pass
    if h_tag:
        try:
            result["height"] = int(str(h_tag))
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def get_nested(d, *keys):
    """Safely retrieve a nested dict value."""
    for key in keys:
        if isinstance(d, dict) and key in d:
            d = d[key]
        else:
            return None
    return d


def set_nested(d, keys, value):
    """Set a nested dict value, creating intermediate dicts as needed."""
    for key in keys[:-1]:
        if key not in d or not isinstance(d[key], dict):
            d[key] = {}
        d = d[key]
    d[keys[-1]] = value


def get_file_name(entry):
    """Extract the filename from a JSON record."""
    return get_nested(entry, "record", "file", "name")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def create_backup(json_path, backup_base_dir, dry_run=False):
    """Create a timestamped backup folder and copy the JSON into it."""
    if dry_run:
        print("[DRY-RUN] Backup would be created (skipped in dry-run mode).")
        return None

    os.makedirs(backup_base_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%y%m%d%H%M")
    session_dir = os.path.join(backup_base_dir, f"{timestamp}_exifscribe")
    os.makedirs(session_dir, exist_ok=True)

    dest = shutil.copy2(json_path, session_dir)
    print(f"Backup created: {dest}")
    return session_dir


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def format_value(key, value):
    """Return a human-readable string for a field value."""
    if value is None:
        return "null"
    return str(value)


def compare_exif_to_json(exif_data, json_entry):
    """
    Compare extracted EXIF values against the existing JSON record.
    Returns:
        needs_fill   : dict of {field: exif_value} for fields that are None in JSON
        mismatches   : dict of {field: (json_value, exif_value)} where values differ
        all_match    : bool - True if all present fields are identical
    """
    needs_fill = {}
    mismatches = {}

    for field, path in EXIF_FIELD_MAP.items():
        exif_val = exif_data.get(field)
        if exif_val is None:
            # EXIF field not available in file – skip, do not overwrite JSON
            continue
        json_val = get_nested(json_entry, *path)
        if json_val is None:
            needs_fill[field] = exif_val
        elif json_val != exif_val:
            mismatches[field] = (json_val, exif_val)
        # else: values match, nothing to do

    all_match = (len(needs_fill) == 0 and len(mismatches) == 0)
    return needs_fill, mismatches, all_match


def apply_exif_to_entry(json_entry, exif_data, fields=None):
    """
    Write EXIF values into the JSON entry.
    If `fields` is given, only write those keys; otherwise write all available.
    Only updates record.exif and record.file – never touches other sections.
    """
    keys_to_write = fields if fields is not None else list(EXIF_FIELD_MAP.keys())
    for field in keys_to_write:
        val = exif_data.get(field)
        if val is None:
            continue
        path = EXIF_FIELD_MAP.get(field)
        if path:
            # Ensure intermediate dicts exist
            curr = json_entry
            for k in path[:-1]:
                if k not in curr or not isinstance(curr[k], dict):
                    curr[k] = {}
                curr = curr[k]
            curr[path[-1]] = val


def build_minimal_entry(filename, exif_data):
    """
    Build a minimal JSON entry from EXIF data for a previously unknown DNG file.
    Only record.file.name and record.exif / record.file EXIF fields are populated.
    All other sections are left empty/null.
    """
    entry = {
        "version": VERSION,
        "session_id": None,
        "objective": None,
        "equipment": {
            "telescope": None,
            "optics": None,
            "filter": None,
            "camera": None
        },
        "record": {
            "meta": {
                "iso_timestamp": None,
                "timestamp_utc": None,
                "frame_type": "Light"
            },
            "file": {
                "name": filename,
                "path": None,
                "format": os.path.splitext(filename)[1].upper().lstrip("."),
            },
            "exif": {},
            "mount": {},
            "location": {},
            "environment": {},
            "analysis": {
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
        }
    }
    apply_exif_to_entry(entry, exif_data)
    return entry


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _getch():
    """Read a single character from stdin without requiring Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def ask(prompt, choices):
    """Display prompt and return the lowercase single-character answer (no Enter needed)."""
    choices_lower = [c.lower() for c in choices]
    while True:
        print(prompt, end='', flush=True)
        ch = _getch().lower()
        print(ch)  # echo the character
        if ch in choices_lower:
            return ch
        print(f"  Please enter one of: {', '.join(choices)}")


def confirm(prompt):
    """Ask a y/n question, return True for 'y'. No Enter needed."""
    print(prompt, end='', flush=True)
    ch = _getch().lower()
    print(ch)  # echo
    return ch == 'y'


# ---------------------------------------------------------------------------
# Main ExifScribe class
# ---------------------------------------------------------------------------

class ExifScribe:

    def __init__(self, scan_dir, json_path, backup_dir, force=False, dry_run=False, ext=".dng"):
        self.scan_dir = os.path.abspath(scan_dir)
        self.json_path = os.path.abspath(json_path)
        self.backup_dir = os.path.abspath(backup_dir)
        self.force = force
        self.dry_run = dry_run
        self.ext = ext.lower()

        # Counters
        self.cnt_updated = 0
        self.cnt_skipped = 0
        self.cnt_added = 0
        self.cnt_deleted = 0
        self.cnt_errors = 0

        # Per-session "skip all mismatches" flag
        self._skip_all_mismatches = False
        # Per-session "skip all missing" flag
        self._skip_all_missing = False

    # -----------------------------------------------------------------------
    # File scanning
    # -----------------------------------------------------------------------

    def scan_dng_files(self):
        """Return a list of DNG filenames (basename only, original case) in scan_dir."""
        files = []
        for fname in os.listdir(self.scan_dir):
            if fname.lower().endswith(self.ext):
                files.append(fname)
        return sorted(files)

    # -----------------------------------------------------------------------
    # JSON load/save
    # -----------------------------------------------------------------------

    def load_json(self):
        if os.path.isdir(self.json_path):
            print(f"Error: JSON path is a directory, not a file: {self.json_path}")
            print(f"  Hint: Did you mean {os.path.join(self.json_path, 'shutter_log.json')} ?")
            sys.exit(1)
        if not os.path.exists(self.json_path):
            print(f"Error: JSON file not found: {self.json_path}")
            sys.exit(1)
        with open(self.json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_json(self, data):
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"JSON saved: {self.json_path}")

    # -----------------------------------------------------------------------
    # Build case-insensitive lookup: filename_lower -> index in json_data
    # -----------------------------------------------------------------------

    def build_json_index(self, json_data):
        index = {}
        for i, entry in enumerate(json_data):
            name = get_file_name(entry)
            if name:
                index[name.lower()] = i
        return index

    # -----------------------------------------------------------------------
    # Processing cases
    # -----------------------------------------------------------------------

    def process_case_d_auto(self, entry, exif_data, fname):
        """Case D: JSON entry found, EXIF fields are empty → auto-fill (no prompt)."""
        needs_fill, _, _ = compare_exif_to_json(exif_data, entry)
        if not needs_fill and not self.force:
            return False  # nothing needs filling
        fields_to_write = list(needs_fill.keys()) if not self.force else None
        if self.dry_run:
            print(f"  [AUTO-FILL] {fname}: would fill {list(needs_fill.keys())}")
        else:
            apply_exif_to_entry(entry, exif_data, fields=fields_to_write)
        return True

    def process_case_b_mismatch(self, entry, exif_data, fname, mismatches):
        """Case B: EXIF value differs from JSON → ask per file."""
        if self._skip_all_mismatches:
            print(f"  [SKIP] {fname}: mismatch skipped (skip-all active).")
            return False

        print(f"\n[≠] Mismatch: {fname}")
        for field, (json_val, exif_val) in mismatches.items():
            print(f"      {field}: JSON={format_value(field, json_val)}  vs  EXIF={format_value(field, exif_val)}")

        if self.dry_run:
            print(f"  [DRY-RUN] Would prompt for action.")
            return False

        ans = ask("  Action? [O]verwrite with EXIF / [K]eep JSON value / [S]kip all mismatches: ", ['o', 'k', 's'])
        if ans == 'o':
            apply_exif_to_entry(entry, exif_data, fields=list(mismatches.keys()))
            return True
        elif ans == 's':
            self._skip_all_mismatches = True
            return False
        else:  # 'k'
            return False

    def process_case_a_new(self, fname, exif_data, json_data):
        """Case A: DNG exists but no JSON entry → ask to add."""
        print(f"\n[+] New: {fname} is not in JSON.")

        if self.dry_run:
            print(f"  [DRY-RUN] Would prompt to add new entry.")
            return

        ans = ask("  Action? [A]dd new entry / [S]kip: ", ['a', 's'])
        if ans == 'a':
            filepath = os.path.join(self.scan_dir, fname)
            new_entry = build_minimal_entry(fname, exif_data)
            json_data.append(new_entry)
            self.cnt_added += 1
            print(f"  [Added] {fname}")

    def process_case_c_missing(self, entry, fname, json_data, indices_to_delete):
        """Case C: JSON entry exists but DNG file is missing → ask to delete."""
        if self._skip_all_missing:
            print(f"  [KEEP] {fname}: no file, kept (skip-all active).")
            return

        print(f"\n[?] Missing: {fname} is in JSON but DNG file not found.")

        if self.dry_run:
            print(f"  [DRY-RUN] Would prompt to delete or keep.")
            return

        ans = ask("  Action? [D]elete from JSON / [K]eep as is / [S]kip all missing: ", ['d', 'k', 's'])
        if ans == 'd':
            indices_to_delete.append(id(entry))
            self.cnt_deleted += 1
            print(f"  [Deleted] {fname}")
        elif ans == 's':
            self._skip_all_missing = True

    # -----------------------------------------------------------------------
    # Main run
    # -----------------------------------------------------------------------

    def run(self):
        print("=" * 60)
        print(f"  ExifScribe v{VERSION}")
        print("=" * 60)
        print(f"  Scan dir  : {self.scan_dir}")
        print(f"  JSON      : {self.json_path}")
        print(f"  Backup dir: {self.backup_dir}")
        print(f"  Ext       : {self.ext}")
        print(f"  Force     : {self.force}")
        print(f"  Dry-run   : {self.dry_run}")
        print("=" * 60)

        if not self.dry_run:
            ans = input("\nProceed? [y/N]: ").strip().lower()
            if ans != 'y':
                print("Cancelled.")
                sys.exit(0)

        # Load JSON
        json_data = self.load_json()

        # Backup before any modification
        if not self.dry_run:
            create_backup(self.json_path, self.backup_dir, dry_run=False)
        else:
            print("[DRY-RUN] Backup skipped.")

        # Scan DNG files
        dng_files = self.scan_dng_files()
        print(f"\nFound {len(dng_files)} DNG file(s) in {self.scan_dir}")

        # Build JSON index (case-insensitive)
        json_index = self.build_json_index(json_data)

        # Track which JSON entries were matched
        matched_json_indices = set()

        print("\n--- Processing DNG files ---")

        for fname in dng_files:
            fname_lower = fname.lower()
            filepath = os.path.join(self.scan_dir, fname)

            # Extract EXIF
            exif_data = extract_exif(filepath)
            if not exif_data:
                print(f"  [Error] No EXIF data from {fname}.")
                self.cnt_errors += 1
                continue

            if fname_lower in json_index:
                idx = json_index[fname_lower]
                matched_json_indices.add(idx)
                entry = json_data[idx]

                needs_fill, mismatches, all_match = compare_exif_to_json(exif_data, entry)

                if all_match and not self.force:
                    # Case D complete / no changes needed
                    print(f"  [Skip] {fname}: all EXIF fields match JSON.")
                    self.cnt_skipped += 1
                elif needs_fill and not self.force:
                    # Case D: auto-fill empty fields
                    did_fill = self.process_case_d_auto(entry, exif_data, fname)
                    if did_fill:
                        print(f"  [Fill] {fname}: auto-filled {list(needs_fill.keys())}")
                        self.cnt_updated += 1
                    else:
                        self.cnt_skipped += 1

                    # Also handle mismatches on top
                    if mismatches:
                        did_update = self.process_case_b_mismatch(entry, exif_data, fname, mismatches)
                        if did_update:
                            self.cnt_updated += 1
                elif mismatches:
                    # Case B: mismatch handling
                    did_update = self.process_case_b_mismatch(entry, exif_data, fname, mismatches)
                    if did_update:
                        self.cnt_updated += 1
                    else:
                        self.cnt_skipped += 1
                elif self.force:
                    # Force re-apply everything
                    if self.dry_run:
                        print(f"  [DRY-RUN] {fname}: force re-apply all fields.")
                    else:
                        apply_exif_to_entry(entry, exif_data)
                        print(f"  [Force] {fname}: all fields re-applied.")
                        self.cnt_updated += 1
            else:
                # Case A: DNG not in JSON
                before_count = len(json_data)
                self.process_case_a_new(fname, exif_data, json_data)
                if len(json_data) > before_count:
                    # Re-build index to pick up new entry
                    json_index = self.build_json_index(json_data)

        # Case C: JSON entries with no matching DNG
        print("\n--- Checking for JSON entries without DNG files ---")
        indices_to_delete_ids = []

        for i, entry in enumerate(json_data):
            if i in matched_json_indices:
                continue
            fname = get_file_name(entry)
            if not fname:
                continue
            # Only process entries whose format matches the target extension
            entry_ext = os.path.splitext(fname)[1].lower()
            if entry_ext != self.ext:
                continue
            self.process_case_c_missing(entry, fname, json_data, indices_to_delete_ids)

        # Remove marked entries
        if indices_to_delete_ids:
            json_data = [e for e in json_data if id(e) not in set(indices_to_delete_ids)]

        # Summary
        print("\n" + "=" * 60)
        print(f"  Summary: Updated={self.cnt_updated}, Skipped={self.cnt_skipped}, "
              f"Added={self.cnt_added}, Deleted={self.cnt_deleted}, Errors={self.cnt_errors}")
        print("=" * 60)

        total_changes = self.cnt_updated + self.cnt_added + self.cnt_deleted
        if total_changes == 0:
            print("No changes to save.")
            return

        if self.dry_run:
            print("[DRY-RUN] No changes written.")
            return

        ans = input("\nSave changes to JSON? [Y]es / [N]o: ").strip().lower()
        if ans == 'y':
            self.save_json(json_data)
        else:
            print("Changes discarded.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"ExifScribe v{VERSION} - Patch shutter_log.json with DNG EXIF metadata",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "dir",
        nargs="?",
        default=".",
        help="Directory containing DNG files (default: current directory)"
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Path to shutter_log.json (default: <dir>/shutter_log.json)"
    )
    parser.add_argument(
        "--backup",
        default=None,
        help="Backup directory (default: <dir>/backups/)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process all EXIF fields even if already filled"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying any files"
    )
    parser.add_argument(
        "--ext",
        default=".dng",
        help="Target file extension (default: .dng, case-insensitive)"
    )

    args = parser.parse_args()

    scan_dir = os.path.abspath(args.dir)
    if not os.path.isdir(scan_dir):
        print(f"Error: Directory not found: {scan_dir}")
        sys.exit(1)

    # Resolve JSON path: if a directory is given, append the default filename
    raw_json = args.json or os.path.join(scan_dir, "shutter_log.json")
    raw_json = os.path.expanduser(raw_json)
    if os.path.isdir(raw_json):
        json_path = os.path.join(raw_json, "shutter_log.json")
        print(f"Note: --json pointed to a directory. Using: {json_path}")
    else:
        json_path = raw_json

    backup_dir = args.backup or os.path.join(scan_dir, "backups")

    ext = args.ext if args.ext.startswith(".") else f".{args.ext}"

    scribe = ExifScribe(
        scan_dir=scan_dir,
        json_path=json_path,
        backup_dir=backup_dir,
        force=args.force,
        dry_run=args.dry_run,
        ext=ext,
    )
    scribe.run()


if __name__ == "__main__":
    main()
