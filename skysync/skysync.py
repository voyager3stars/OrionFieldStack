#!/usr/bin/env python3
# =================================================================
# Project:      OrionFieldStack
# Tool:         SkySync v2.0.2 (Core Orchestrator)
# Description:  
#   v2.0.2: SSE v2.0.x のネストされたJSON構造に対応。
#           INDI同期時のRA単位変換 (Degree to Hours) を実装。
# =================================================================

__version__ = "2.0.2"
__json_spec__ = "1.4.2"

import subprocess
import argparse
import os
import json
import time

CONFIG_FILE = "config.json"

class SkySync:
    def __init__(self):
        self.config = self.load_config()
        self.device = self.config["indi"]["device"]
        self.shutter_dir = os.path.abspath(os.path.expanduser(self.config["paths"]["shutter_pro_dir"]))
        self.sse_dir = os.path.abspath(os.path.expanduser(self.config["paths"]["sse_dir"]))
        self.image_dir = os.path.abspath(os.path.expanduser(self.config["paths"]["default_image_dir"]))
        
        # SSE v2.0.x が出力する最新解析結果 JSON
        self.latest_json_path = os.path.join(self.image_dir, "latest_shot.json")
        self.shutter_defaults = self.config["shutter_defaults"]

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            print(f"[Error] {CONFIG_FILE} not found.")
            exit(1)
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def run_tool(self, tool_dir, script_name, args):
        """仮想環境のPythonを使って指定したスクリプトを実行する"""
        venv_python = os.path.join(tool_dir, "venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = "python3" # venvがない場合のフォールバック

        cmd = [venv_python, os.path.join(tool_dir, script_name)] + args
        print(f"[SkySync] Executing: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"[Error] {script_name} failed: {e}")
            return False

    def load_latest_coords(self):
        """SSE v2.0.x 構造の JSON から座標と解析統計を読み取る"""
        if not os.path.exists(self.latest_json_path):
            print(f"[Error] {self.latest_json_path} not found.")
            return None, None

        try:
            with open(self.latest_json_path, 'r') as f:
                data = json.load(f)
                
                # latest_shot.json はリスト形式を想定。安全に取得する。
                if not data or not isinstance(data, list):
                    return None, None
                    
                record = data[0].get("record", {})
                ana = record.get("analysis", {})
                
                if ana.get("solve_status") == "success":
                    coords = ana.get("solved_coords", {})
                    stats = ana.get("process_stats", {})
                    conf = ana.get("confidence", 0.0)
                    
                    print(f"\n--- [SkySync Result Summary] ---")
                    print(f" Status: SUCCESS (SSE v{ana.get('sse_version')})")
                    print(f" Confidence: {conf:.2f}")
                    print(f" Stars: {stats.get('matched_stars')} matched")
                    print(f" Position: RA {coords.get('ra_hms')} / Dec {coords.get('dec_dms')}")
                    print(f"--------------------------------\n")
                    
                    return coords.get("ra_deg"), coords.get("dec_deg")
                else:
                    fail_reason = ana.get("fail_reason", "Unknown")
                    print(f"[SkySync] Solve failed or pending. Reason: {fail_reason}")
                    return None, None
        except Exception as e:
            print(f"[Error] Failed to parse JSON: {e}")
            return None, None

    def sync_to_indi(self, ra_deg, dec_deg):
        """解析された座標（度）を INDI マウントに同期する"""
        if ra_deg is None or dec_deg is None: return
        
        # 【重要】RA を「度(0-360)」から「時(0-24)」に変換
        ra_hours = round(float(ra_deg) / 15.0, 8)
        dec_val = round(float(dec_deg), 8)
        
        print(f"[SkySync] Syncing to INDI [{self.device}]...")
        print(f" -> Converting RA: {ra_deg}° to {ra_hours}h")
        try:
            # EQUATORIAL_EOD_COORD に RA(時)/DEC(度) をセット
            cmd = ["indi_setprop", f"{self.device}.EQUATORIAL_EOD_COORD.RA={ra_hours};DEC={dec_val}"]
            subprocess.run(cmd, check=True)
            print(f"[SkySync] INDI Sync Complete: RA={ra_hours}h, Dec={dec_val}°")
        except Exception as e:
            print(f"[Error] INDI Sync failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="SkySync v2.0.2")
    parser.add_argument('mode', choices=['full', 'sync', 'manual'])
    parser.add_argument('--ra', type=float, help='Manual RA (deg)')
    parser.add_argument('--dec', type=float, help='Manual Dec (deg)')
    args, extra_args = parser.parse_known_args()

    ss = SkySync()

    if args.mode in ["full", "sync"]:
        if args.mode == "full":
            # 1. 撮影実行 (shutterpro03.py)
            sh_args = [
                ss.shutter_defaults["count"], ss.shutter_defaults["mode"], ss.shutter_defaults["exposure"],
                f"sess={ss.shutter_defaults['session']}", f"t={ss.shutter_defaults['type']}",
                f"dir={ss.image_dir}"
            ]
            if extra_args: sh_args.extend(extra_args)
            if not ss.run_tool(ss.shutter_dir, "shutterpro03.py", sh_args): return

        # 2. 解析実行 (SSE.py)
        if ss.run_tool(ss.sse_dir, "SSE.py", ["latest", ss.image_dir]):
            # 3. 解析済み JSON を読み込んで INDI 同期
            ra, dec = ss.load_latest_coords()
            ss.sync_to_indi(ra, dec)

    elif args.mode == "manual":
        # マニュアル同期（JSON構造に依存しない）
        if args.ra is not None and args.dec is not None:
            ss.sync_to_indi(args.ra, args.dec)
        else:
            print("[Error] --ra and --dec are required for manual mode.")

if __name__ == "__main__":
    main()
