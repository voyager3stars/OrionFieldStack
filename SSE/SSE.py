#!/usr/bin/env python3
# =================================================================
# Project:      OrionFieldStack
# Component:    SkySolverEngine (SSE)
# Version:      2.0.3
# Author:       OrionFieldStack Dev Team
# Description:  
#   v2.0.2:
#   - latestモードでの「指紋照合（ファイル名一致チェック）」を実装。
#   - ポスト処理中の latest_shot.json 汚染を防止。
# =================================================================

__version__ = "2.0.3"
__json_spec__ = "1.4.1"

import os
import sys
import json
import csv
import subprocess
import argparse
import re
import time
import datetime
import rawpy
import imageio
import math

class SkySolverEngine:
    def __init__(self, workdir="/tmp/skysolver", all_sky_enabled=False, force_mode=False):
        self.workdir = workdir
        self.all_sky_enabled = all_sky_enabled
        self.force_mode = force_mode
        if not os.path.exists(self.workdir):
            os.makedirs(self.workdir)

    def deg_to_hms(self, ra_deg):
        ra_hours = (ra_deg % 360) / 15.0
        h = int(ra_hours); m = int((ra_hours - h) * 60); s = (ra_hours - h - m/60) * 3600
        return f"{h:02d}:{m:02d}:{s:05.2f}"

    def deg_to_dms(self, dec_deg):
        d = int(dec_deg); abs_d = abs(dec_deg); m = int((abs_d - abs(d)) * 60); s = (abs_d - abs(d) - m/60) * 3600
        sign = "+" if dec_deg >= 0 else "-"
        return f"{sign}{abs(d):02d}:{m:02d}:{s:05.2f}"

    def get_star_rating(self, stars):
        if stars >= 50: return "★★★★★"
        if stars >= 30: return "★★★★☆"
        if stars >= 15: return "★★★☆☆"
        if stars >= 10: return "★★☆☆☆"
        return "★☆☆☆☆"

    def prepare_image(self, image_path):
        if image_path.lower().endswith(('.dng', '.raw')):
            tmp_jpg = os.path.join(self.workdir, "solve_input.jpg")
            try:
                with rawpy.imread(image_path) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True)
                    imageio.imsave(tmp_jpg, rgb)
                return tmp_jpg
            except Exception as e:
                print(f"  [Error] Image conversion failed: {e}"); return None
        return image_path

    def solve(self, image_path, ra_hint=None, dec_hint=None):
        start_time = time.time()
        timestamp = datetime.datetime.now().isoformat(timespec='seconds')
        
        if ra_hint is None and not self.all_sky_enabled:
            return {"success": False, "duration": 0.0, "timestamp": timestamp}

        src = self.prepare_image(image_path)
        if not src: return {"success": False, "duration": 0.0, "timestamp": timestamp}

        base_cmd = ["solve-field", src, "--dir", self.workdir, "--overwrite", "--no-plots",
                    "--scale-low", "1.0", "--scale-high", "15.0", "--scale-units", "app", "--cpulimit", "20"]

        def try_solve(pass_label, sigma, ds, extra_args, timeout=25):
            print(f"  [Solve] {pass_label}: (sigma={sigma}, ds={ds})...", end="\r")
            full_cmd = base_cmd + ["--sigma", str(sigma), "--downsample", str(ds)] + extra_args
            res_cmd = self._run_solve_cmd(full_cmd, timeout=timeout)
            if res_cmd["success"]:
                res_cmd["solve_path"] = pass_label
                print(f"  [Match] {res_cmd.get('hitmiss', '')} [SUCCESS!]")
            return res_cmd

        res = {"success": False}
        hint_args = ["--ra", str(ra_hint), "--dec", str(dec_hint), "--radius", "10.0"] if ra_hint is not None else []

        if hint_args:
            res = try_solve("Pass 1", sigma=30, ds=4, extra_args=hint_args + ["--objs", "100"])
            if not res["success"]:
                res = try_solve("Pass 2", sigma=15, ds=4, extra_args=hint_args + ["--objs", "100"])
            if not res["success"]:
                res = try_solve("Pass 3", sigma=10, ds=4, extra_args=hint_args + ["--objs", "150"])

        if not res["success"] and self.all_sky_enabled:
            res = try_solve("Pass 4", sigma=30, ds=4, extra_args=["--objs", "100"], timeout=45)
            if not res["success"]:
                res = try_solve("Pass 5", sigma=15, ds=4, extra_args=["--objs", "100"], timeout=45)
            if not res["success"]:
                res = try_solve("Pass 6", sigma=10, ds=4, extra_args=["--objs", "100"], timeout=45)

        res["duration"] = round(time.time() - start_time, 2)
        res["timestamp"] = timestamp
        res["sse_version"] = __version__
        return res

    def _run_solve_cmd(self, cmd, timeout):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if "Field 1: solved" in res.stdout:
                m_coord = re.search(r"Field center: \(RA,Dec\) = \(([\d\.-]+), ([\d\.-]+)\) deg", res.stdout)
                m_orient = re.search(r"Field rotation angle: up is ([\d\.-]+) degrees", res.stdout)
                m_stars = re.search(r"found (\d+) sources", res.stdout)
                m_conf = re.search(r"log-odds ratio ([\d\.]+)", res.stdout)
                m_hm = re.search(r"Hit/miss: ([\+\-]+)", res.stdout)
                
                return {
                    "success": True, 
                    "ra": float(m_coord.group(1)) if m_coord else 0.0, 
                    "dec": float(m_coord.group(2)) if m_coord else 0.0,
                    "orientation": float(m_orient.group(1)) if m_orient else None,
                    "stars": int(m_stars.group(1)) if m_stars else None,
                    "confidence": float(m_conf.group(1)) if m_conf else 0.0,
                    "hitmiss": m_hm.group(1)[:15] if m_hm else "" 
                }
            return {"success": False}
        except Exception: return {"success": False}

    def print_dashboard(self, res, ra_hint, dec_hint):
        print(f"\n-----------------[ ANALYSIS REPORT ]-----------------")
        status_str = "SUCCESS" if res["success"] else "FAILED"
        print(f" Result: {status_str} ({res.get('solve_path', 'N/A')}) / Time: {res.get('duration')}s")
        
        if res["success"]:
            stars = res.get('stars', 0)
            print(f" Confidence: {res.get('confidence', 0.0):.2f} (log-odds)")
            print(f" Stars: [ {self.get_star_rating(stars)} ] {stars} matched")
            print(f"-----------------------------------------------------")
            print(f" Position: RA {self.deg_to_hms(res['ra'])} / Dec {self.deg_to_dms(res['dec'])}")
            print(f" Rotation: {res.get('orientation', 0.0):.2f}° (E of N)")
            
            if ra_hint is not None:
                dra = res['ra'] - ra_hint
                ddec = res['dec'] - dec_hint
                dist = math.sqrt((dra * math.cos(math.radians(dec_hint)))**2 + ddec**2) * 60
                print(f"-----------------------------------------------------")
                print(f" Mount Drift (Offset):")
                print(f"  ΔRA: {dra:+.3f}° / ΔDec: {ddec:+.3f}°")
                print(f"  Total Dist: {dist:.1f}' {'[ Excellent ]' if dist < 5 else '[ Need Sync ]'}")
        print(f"-----------------------------------------------------\n")

    def update_logs(self, img_path, res):
        img_dir = os.path.dirname(os.path.abspath(img_path))
        img_name = os.path.basename(img_path)
        h_path = os.path.join(img_dir, "shutter_log.json")
        if os.path.exists(h_path): self._update_json_file(h_path, img_name, res)
        csv_path = os.path.join(img_dir, "shutter_log.csv")
        if os.path.exists(csv_path): self._update_csv_file(csv_path, img_name, res)

    def _update_json_file(self, filepath, target_filename, res):
        try:
            with open(filepath, 'r+', encoding='utf-8') as f:
                data = json.load(f)
                updated = False
                for entry in data:
                    if entry["record"]["file"]["name"] in target_filename:
                        self._apply_res_to_dict(entry, res)
                        updated = True
                if updated:
                    f.seek(0); json.dump(data, f, indent=4, ensure_ascii=False); f.truncate()
        except Exception as e: print(f"  [Warning] JSON Update Failed: {e}")

    def _apply_res_to_dict(self, target_dict, res):
        new_analysis = {
            "solve_status": "success" if res["success"] else "failed",
            "solve_path": res.get("solve_path", "N/A"),
            "sse_version": __version__,
            "timestamp": res.get("timestamp", ""),
            "confidence": res.get("confidence", 0.0)
        }
        if res["success"]:
            new_analysis["solved_coords"] = {
                "ra_deg": res["ra"], "dec_deg": res["dec"], "orientation": res.get("orientation"),
                "ra_hms": self.deg_to_hms(res["ra"]), "dec_dms": self.deg_to_dms(res["dec"])
            }
            new_analysis["process_stats"] = {
                "matched_stars": res.get("stars"),
                "solve_duration_sec": res.get("duration", 0.0)
            }
            new_analysis["quality"] = {"hfr": None, "elongation": None}
        target_dict["record"]["analysis"] = new_analysis

    def _update_csv_file(self, filepath, target_filename, res):
        try:
            rows = []; fieldnames = []; header_comment = ""
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    first_line = f.readline()
                    if first_line.startswith("#"): header_comment = first_line
                    else: f.seek(0)
                    reader = csv.DictReader(f); fieldnames = list(reader.fieldnames) if reader.fieldnames else []; rows = list(reader)
            if not fieldnames: return
            new_cols = ["Solve_Status", "Solve_Confidence", "Matched_Stars", "Solve_Time_sec", "Solve_Path", "Solve_Orientation", "Solve_RA", "Solve_DEC", "SSE_Version"]
            for col in new_cols:
                if col not in fieldnames: fieldnames.append(col)
            updated_any = False
            for row in rows:
                csv_filename = row.get("File_Name", "")
                if csv_filename and (csv_filename == target_filename or csv_filename in target_filename):
                    row["Solve_Status"] = "success" if res["success"] else "failed"
                    row["Solve_Path"] = res.get("solve_path", "N/A")
                    row["Solve_Time_sec"] = str(res.get("duration", 0.0))
                    row["Solve_Confidence"] = f"{res.get('confidence', 0.0):.2f}"
                    row["SSE_Version"] = __version__
                    if res["success"]:
                        row["Solve_RA"] = f"{res['ra']:.8f}"; row["Solve_DEC"] = f"{res['dec']:.8f}"
                        row["Matched_Stars"] = str(res.get("stars", "")); row["Solve_Orientation"] = f"{res.get('orientation', 0.0):.2f}"
                    updated_any = True
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                if header_comment: f.write(header_comment)
                writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader(); writer.writerows(rows)
        except Exception as e: print(f"  [Error] CSV Update Failed: {e}")

    def process_target(self, target_path):
        target_name = os.path.basename(target_path)
        log_path = os.path.join(os.path.dirname(target_path), "shutter_log.json")
        ra_hint, dec_hint, is_solved = None, None, False
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    for r in json.load(f):
                        if r["record"]["file"]["name"] in target_name:
                            is_solved = r["record"].get("analysis", {}).get("solve_status") == "success"
                            ra_hint = r["record"]["mount"].get("ra_deg")
                            dec_hint = r["record"]["mount"].get("dec_deg"); break
            except: pass
        if is_solved and not self.force_mode:
            print(f"SSE>> Processing [{target_name}]\n  [Skip] Already solved.")
            return
        print(f"SSE>> Processing [{target_name}]{' (RE-SOLVE)' if is_solved else ''}")
        res = self.solve(target_path, ra_hint, dec_hint)
        self.print_dashboard(res, ra_hint, dec_hint)
        self.update_logs(target_path, res)

    def process_latest(self, image_dir):
        """latest_shot.json を指紋照合しながら更新する"""
        latest_json = os.path.join(image_dir, "latest_shot.json")
        if not os.path.exists(latest_json):
            print(f"SSE>> [Error] {latest_json} not found."); return

        # 1. 開始時の指紋取得
        try:
            with open(latest_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
                target_filename = data[0]["record"]["file"]["name"]
                target_path = os.path.join(image_dir, target_filename)
                ra_hint = data[0]["record"]["mount"].get("ra_deg")
                dec_hint = data[0]["record"]["mount"].get("dec_deg")
        except Exception as e:
            print(f"SSE>> [Error] Failed to read fingerprint: {e}"); return

        # 2. 解析実行
        print(f"SSE>> Processing Latest: [{target_filename}]")
        res = self.solve(target_path, ra_hint, dec_hint)
        self.print_dashboard(res, ra_hint, dec_hint)

        # 3. 書き込み直前の照合と更新
        try:
            with open(latest_json, 'r+', encoding='utf-8') as f:
                current_data = json.load(f)
                if current_data[0]["record"]["file"]["name"] == target_filename:
                    print(f"SSE>> Fingerprint match. Updating latest_shot.json.")
                    self._apply_res_to_dict(current_data[0], res)
                    f.seek(0); json.dump(current_data, f, indent=4, ensure_ascii=False); f.truncate()
                else:
                    print(f"SSE>> [Warning] Fingerprint mismatch! Next shot already started. Skipping update.")
            
            # メインログ（shutter_log.json / csv）は不一致でも更新しておく
            self.update_logs(target_path, res)
        except Exception as e:
            print(f"SSE>> [Error] Final update failed: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['latest', 'select'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--allsky', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    sse = SkySolverEngine(all_sky_enabled=args.allsky, force_mode=args.force)

    try:
        if args.mode == 'select' and args.target:
            t = os.path.abspath(os.path.expanduser(args.target))
            if os.path.isdir(t):
                files = sorted([f for f in os.listdir(t) if f.lower().endswith(('.dng', '.raw'))])
                for f in files: sse.process_target(os.path.join(t, f))
            else: sse.process_target(t)
        elif args.mode == 'latest' and args.target:
            sse.process_latest(os.path.abspath(os.path.expanduser(args.target)))
    except KeyboardInterrupt:
        print("\nSSE>> Interrupted by user. Cleaning up..."); sys.exit(1)

if __name__ == "__main__": main()
