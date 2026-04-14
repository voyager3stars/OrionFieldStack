#!/usr/bin/env python3
# =================================================================
# Project:      OrionFieldStack
# Component:    LogMigrator 1.6
# Author:       Antigravity
# Description:  
#   v1.5 の shutter_log.json を読み込み、v1.6.0 仕様のスキーマへと
#   互換性を保ったまま構造変換を行う単独スクリプト。
# =================================================================

import json
import os
import sys
import shutil

__version__ = "1.0.0"
TARGET_SPEC = "1.6.0"

def migrate_entry(entry):
    """
    1つの JSON レコード（Dict）を v1.6.0 の書式へ変換します。
    """
    if entry.get("version") == TARGET_SPEC:
        return entry  # 既にマイグレーション済みならスキップ
    
    # 1. バージョンの更新
    entry["version"] = TARGET_SPEC
    
    record = entry.get("record", {})
    
    # 2. Locationブロックのクリーンアップ（余分なタイムゾーン変数を削除）
    # 大文字・小文字両対応（過去のフォーマットゆれ吸収のため）
    loc = record.get("location") or record.get("Location") or {}
    
    if "Location" in record:
        del record["Location"]
        record["location"] = loc

    if "timezone" in loc:
        del loc["timezone"]
    if "utc_offset" in loc:
        del loc["utc_offset"]
        
    # 3. Analysisブロックの再マッピング
    old_analysis = record.get("analysis", {})
    
    # --- SSE ツリーの抽出 ---
    # 旧バージョンでは SSE のデータは analysis 直下に置かれていました。
    sse = {
        "sse_version": old_analysis.get("sse_version", "pending"),
        "solve_status": old_analysis.get("solve_status", "pending"),
        "solve_path": old_analysis.get("solve_path", "pending"),
        "confidence": old_analysis.get("confidence", "pending"),
        "timestamp": old_analysis.get("timestamp", "pending"),
        "solved_coords": old_analysis.get("solved_coords") or {
            "ra_deg": "pending", "dec_deg": "pending", "orientation": "pending",
            "ra_hms": "pending", "dec_dms": "pending"
        },
        "process_stats": old_analysis.get("process_stats") or {
            "matched_stars": "pending", "solve_duration_sec": "pending"
        }
    }
    
    # --- SF ツリーの抽出 ---
    # 旧バージョンでは SF の主要ステータスやバージョンも quality 直下にありました。
    old_q = old_analysis.get("quality", {})
    
    if isinstance(old_q, dict) and old_q.get("sf_status") == "success":
        sf = {
            "sf_version": old_q.get("sf_version", "unknown"),
            "sf_status": old_q.get("sf_status", "success"),
            "sf_timestamp": old_q.get("sf_timestamp", "unknown"),
            "quality": {
                "sf_stars": old_q.get("sf_stars", "pending"),
                "sf_fwhm_med": old_q.get("sf_fwhm_med", "pending"),
                "sf_fwhm_mean": old_q.get("sf_fwhm_mean", "pending"),
                "sf_fwhm_std": old_q.get("sf_fwhm_std", "pending"),
                "sf_ell_med": old_q.get("sf_ell_med", "pending"),
                "sf_ell_mean": old_q.get("sf_ell_mean", "pending"),
                "sf_ell_std": old_q.get("sf_ell_std", "pending")
            }
        }
    else:
        sf = {
            "sf_version": "pending",
            "sf_status": "pending",
            "sf_timestamp": "pending",
            "quality": {
                "sf_stars": "pending", 
                "sf_fwhm_med": "pending", 
                "sf_fwhm_mean": "pending",
                "sf_fwhm_std": "pending", 
                "sf_ell_med": "pending", 
                "sf_ell_mean": "pending",
                "sf_ell_std": "pending"
            }
        }
        
    # 古い解析結果を上書き（SSE と SF の完全独立ツリーにする）
    record["analysis"] = {
        "SSE": sse,
        "SF": sf
    }
    
    return entry


def main():
    if len(sys.argv) < 2:
        print("Usage: python logmigrator_1_6.py <path_to_shutter_log.json>")
        sys.exit(1)
        
    input_file = os.path.abspath(sys.argv[1])
    if not os.path.exists(input_file):
        print(f"[Error] File not found: {input_file}")
        sys.exit(1)
        
    # バックアップの作成
    backup_file = input_file + ".bak"
    try:
        shutil.copy2(input_file, backup_file)
        print(f"LogMigrator>> Backup successfully created at: {backup_file}")
    except Exception as e:
        print(f"[Error] Failed to create backup: {e}")
        sys.exit(1)
    
    # マイグレーション
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        if not isinstance(data, list):
            print("[Error] Expected a JSON array at root level.")
            sys.exit(1)
            
        migrated_data = [migrate_entry(item) for item in data]
        
        with open(input_file, 'w', encoding='utf-8') as f:
            json.dump(migrated_data, f, indent=4, ensure_ascii=False)
            
        print(f"LogMigrator>> Successfully migrated {len(migrated_data)} entries to {TARGET_SPEC}.")
        
    except Exception as e:
        print(f"LogMigrator>> [Error] Migration failed: {e}")
        print("LogMigrator>> Restoring from backup...")
        shutil.copy2(backup_file, input_file)
        sys.exit(1)

if __name__ == "__main__":
    main()
