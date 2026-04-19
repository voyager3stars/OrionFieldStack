#!/usr/bin/env python3
import os
import json
import csv
import shutil
import argparse
import sys
from datetime import datetime

__version__ = "1.6.0"

class ImageFileHarmonizer:
    EXTENSIONS = ('.dng', '.raw', '.fits', '.fit', '.fts')

    def __init__(self, target_dir, json_path=None, csv_path=None, interactive=True):
        self.target_dir = os.path.abspath(os.path.expanduser(target_dir))
        self.interactive = interactive
        
        # Resolve log paths (default to shutter_log.json/csv in target_dir if not specified)
        self.json_path = json_path if json_path else os.path.join(self.target_dir, "shutter_log.json")
        self.csv_path = csv_path if csv_path else os.path.join(self.target_dir, "shutter_log.csv")
        
        self.trash_dir = os.path.join(self.target_dir, "trash")
        self.backup_dir = os.path.join(self.target_dir, "backups")

    def create_backup(self, file_path):
        """Create a backup of a log file."""
        if not os.path.exists(file_path):
            return
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)
            
        timestamp = datetime.now().strftime("%y%m%d%H%M%S")
        fname = os.path.basename(file_path)
        bak_name = f"{timestamp}_{fname}.bak"
        dest = os.path.join(self.backup_dir, bak_name)
        shutil.copy2(file_path, dest)
        return dest

    def get_disk_files(self):
        """List all image files in target_dir (non-recursive)."""
        files = []
        if not os.path.exists(self.target_dir):
            return []
        for f in os.listdir(self.target_dir):
            if f.lower().endswith(self.EXTENSIONS):
                files.append(f)
        return sorted(files)

    def load_json_filenames(self):
        """Returns a set of filenames mentioned in the JSON log."""
        if not os.path.exists(self.json_path):
            return set()
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            names = set()
            for entry in data:
                # Support both 1.6.x (record.file.name) and flat structure if any
                name = entry.get("record", {}).get("file", {}).get("name")
                if not name:
                    # Fallback to older or alternative structure
                    name = entry.get("file_name") or entry.get("filename")
                if name:
                    names.add(name)
            return names
        except Exception as e:
            print(f"  [Warning] Failed to read JSON: {e}")
            return set()

    def load_csv_filenames(self):
        """Returns a set of filenames mentioned in the CSV log."""
        if not os.path.exists(self.csv_path):
            return set()
        try:
            names = set()
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
                # Find header
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
                    # Look for 'Filename' or 'File_Name' or 'name' case-insensitive
                    name = row.get("Filename") or row.get("File_Name") or row.get("filename")
                    if name:
                        names.add(name)
            return names
        except Exception as e:
            print(f"  [Warning] Failed to read CSV: {e}")
            return set()

    def audit(self):
        print(f"\n==================================================")
        print(f"  ImageFileHarmonizer v{__version__} [Audit Mode]")
        print(f"==================================================")
        print(f"  Target Dir: {self.target_dir}")
        print(f"  JSON Log:   {os.path.basename(self.json_path)}")
        print(f"  CSV Log:    {os.path.basename(self.csv_path)}")
        print(f"==================================================\n")

        disk_files = set(self.get_disk_files())
        json_files = self.load_json_filenames()
        csv_files = self.load_csv_filenames()

        all_logged_files = json_files.union(csv_files)
        
        # 1. Orphans: On disk but NOT in any log
        orphans = sorted(list(disk_files - all_logged_files))
        
        # 2. Ghosts: In log but NOT on disk
        ghosts_json = sorted(list(json_files - disk_files))
        ghosts_csv = sorted(list(csv_files - disk_files))
        
        # 3. Log Sync status: entries in one log but missing in the other
        only_json = sorted(list(json_files - csv_files))
        only_csv = sorted(list(csv_files - json_files))

        has_diff = False

        # --- Display Orphans ---
        if orphans:
            has_diff = True
            print(f"  [Orphans] {len(orphans)} files found on disk but NOT in logs (to be trashed):")
            for f in orphans[:20]:
                print(f"    - {f}")
            if len(orphans) > 20:
                print(f"    ... and {len(orphans)-20} more.")
        else:
            print(f"  [Orphans] 0 files (All disk files are logged -> OK)")
        print("")

        # --- Display Ghosts ---
        if ghosts_json or ghosts_csv:
            has_diff = True
            print(f"  [Ghosts] Entries found in logs but missing from disk (Ghost records):")
            # Combine unique ghost names for display
            all_ghosts = sorted(list(set(ghosts_json).union(set(ghosts_csv))))
            for f in all_ghosts[:20]:
                print(f"    - {f}")
            if len(all_ghosts) > 20:
                print(f"    ... and {len(all_ghosts)-20} more.")
        else:
            print(f"  [Ghosts] 0 entries (All logged items exist on disk -> OK)")
        print("")

        # --- Display Log Sync Status ---
        if only_json or only_csv:
            # Informational mismatch between logs
            # This doesn't block orphans/ghosts but suggests LogHarmonizer
            print(f"  [Log Sync] Discrepancies between JSON and CSV logs:")
            if only_json:
                print(f"    - Unique to JSON: {len(only_json)} items")
            if only_csv:
                print(f"    - Unique to CSV:  {len(only_csv)} items")
            print("    (Tip: Use logharmonizer1_6.py to sync JSON and CSV content)")
        else:
            print(f"  [Log Sync] 0 discrepancies (JSON and CSV match -> OK)")
        print("")

        if not has_diff and not (only_json or only_csv):
            print(f"  >> SUCCESS: Filesystem and all logs (JSON/CSV) are perfectly synchronized.")
            return

        # Interactive phase
        if self.interactive:
            if orphans:
                print(f"ACTION: {len(orphans)} orphan files found.")
                ans = input("  Choose: [A]ll to trash / [I]ndividual check / [S]kip: ").strip().lower()
                if ans == 'a':
                    self.move_to_trash(orphans)
                elif ans == 'i':
                    to_move = []
                    for f in orphans:
                        sub_ans = input(f"    Move '{f}' to trash? [y/N]: ").strip().lower()
                        if sub_ans == 'y':
                            to_move.append(f)
                    if to_move:
                        self.move_to_trash(to_move)

            if ghosts_json or ghosts_csv:
                print(f"\nACTION: {len(ghosts_json) + len(ghosts_csv)} ghost entries found in logs.")
                ans = input("  Choose: [A]ll cleanup / [I]ndividual check / [S]kip: ").strip().lower()
                if ans == 'a':
                    self.cleanup_logs(ghosts_json, ghosts_csv)
                elif ans == 'i':
                    g_json_to_clean = []
                    g_csv_to_clean = []
                    # Union of all ghost files across logs
                    all_ghosts = sorted(list(set(ghosts_json).union(set(ghosts_csv))))
                    for f in all_ghosts:
                        sub_ans = input(f"    Remove record of '{f}' from logs? [y/N]: ").strip().lower()
                        if sub_ans == 'y':
                            if f in ghosts_json: g_json_to_clean.append(f)
                            if f in ghosts_csv: g_csv_to_clean.append(f)
                    
                    if g_json_to_clean or g_csv_to_clean:
                        self.cleanup_logs(g_json_to_clean, g_csv_to_clean)
        else:
            print("  [Notice] Dry-run completed. No changes made in non-interactive mode.")

    def move_to_trash(self, file_list):
        if not os.path.exists(self.trash_dir):
            os.makedirs(self.trash_dir)
            print(f"  Created trash directory: {self.trash_dir}")

        count = 0
        for f in file_list:
            src = os.path.join(self.target_dir, f)
            dst = os.path.join(self.trash_dir, f)
            try:
                shutil.move(src, dst)
                count += 1
            except Exception as e:
                print(f"  [Error] Failed to move {f}: {e}")
        
        print(f"  Done: Moved {count} files to trash.")

    def cleanup_logs(self, ghosts_json, ghosts_csv):
        # Backup first
        if ghosts_json and os.path.exists(self.json_path):
            bak = self.create_backup(self.json_path)
            print(f"  Backup created: {os.path.basename(bak)}")
            
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Filter
            new_data = []
            for entry in data:
                name = entry.get("record", {}).get("file", {}).get("name") or \
                       entry.get("file_name") or entry.get("filename")
                if name not in ghosts_json:
                    new_data.append(entry)
            
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, indent=4, ensure_ascii=False)
            print(f"  JSON log cleaned: removed {len(data) - len(new_data)} records.")

        if ghosts_csv and os.path.exists(self.csv_path):
            bak = self.create_backup(self.csv_path)
            print(f"  Backup created: {os.path.basename(bak)}")
            
            # Read CSV preserving headers and comments
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            
            new_lines = []
            header_found = False
            header_keys = []
            
            for line in lines:
                if line.startswith("#"):
                    new_lines.append(line)
                elif not header_found:
                    new_lines.append(line)
                    header_keys = [k.strip() for k in line.split(",")]
                    name_col_idx = -1
                    for idx, opt in enumerate(["Filename", "File_Name", "filename"]):
                        if opt in header_keys:
                            name_col_idx = idx
                            break
                    header_found = True
                else:
                    # Data row
                    parts = [p.strip() for p in line.split(",")]
                    if name_col_idx != -1 and name_col_idx < len(parts):
                        fname = parts[name_col_idx]
                        if fname not in ghosts_csv:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
            
            with open(self.csv_path, 'w', encoding='utf-8-sig') as f:
                f.writelines(new_lines)
            print(f"  CSV log cleaned.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"ImageFileHarmonizer v{__version__}: Logs vs Filesystem Auditor")
    parser.add_argument("directory", help="Target directory containing images and logs")
    parser.add_argument("--json", help="Override JSON log path")
    parser.add_argument("--csv", help="Override CSV log path")
    parser.add_argument("--no-interactive", action="store_false", dest="interactive", help="Dry-run audit without confirmation prompts")
    parser.set_defaults(interactive=True)
    
    args = parser.parse_args()
    
    harmonizer = ImageFileHarmonizer(args.directory, json_path=args.json, csv_path=args.csv, interactive=args.interactive)
    harmonizer.audit()
