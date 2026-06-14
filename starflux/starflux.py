#!/usr/bin/env python3
# =================================================================
# Project:      OrionFieldStack
# Component:    StarFlux
# Version:      1.3.1
# Author:       Antigravity (Coding Assistant)
# Description:  
#   天体画像の品質評価プログラム。
#   v1.1.0: フォルダ一括処理、shutter_log.json 自動統合を実装。
# =================================================================

import os
import sys
import json
import time
import argparse
import csv
import numpy as np
import rawpy
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from photutils.detection import DAOStarFinder

__version__ = "1.3.2"

def load_image(file_path):
    """
    DNG (rawpy) または FITS (astropy) ファイルを読み込み、グレースケール配列を返す
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.dng', '.raw']:
        with rawpy.imread(file_path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=False, no_auto_bright=True, output_bps=16)
            gray = 0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]
            return gray.astype(np.float32)
    elif ext in ['.fits', '.fit', '.fts']:
        with fits.open(file_path) as hdul:
            data = hdul[0].data
            if data is None: # Compressed FITS support
                data = hdul[1].data
            return data.astype(np.float32)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

def calculate_moments(data):
    """
    画像のモーメントから FWHM と Ellipticity を算出する
    """
    y, x = np.mgrid[:data.shape[0], :data.shape[1]]
    total_flux = np.sum(data)
    if total_flux <= 0:
        return None, None
    
    xc = np.sum(x * data) / total_flux
    yc = np.sum(y * data) / total_flux
    
    mxx = np.sum((x - xc)**2 * data) / total_flux
    myy = np.sum((y - yc)**2 * data) / total_flux
    mxy = np.sum((x - xc) * (y - yc) * data) / total_flux
    
    common = np.sqrt((mxx - myy)**2 + 4 * mxy**2)
    eig1 = (mxx + myy + common) / 2.0
    eig2 = (mxx + myy - common) / 2.0
    
    a = np.sqrt(max(0, eig1))
    b = np.sqrt(max(0, eig2))
    
    fwhm = 2.355 * np.sqrt((a**2 + b**2) / 2.0)
    ellipticity = 1.0 - (b / a) if a > 0 else 0.0
    
    return fwhm, ellipticity

def analyze_star_quality(data, stars, box_size=15):
    """
    検出された各星について統計情報を計算
    """
    results = []
    half_box = box_size // 2
    h, w = data.shape
    
    for star in stars:
        # photutilsのバージョンによって 'x_centroid' または 'xcentroid' が使用される
        x_val = star.get('x_centroid', star.get('xcentroid'))
        y_val = star.get('y_centroid', star.get('ycentroid'))
        
        if x_val is None or y_val is None:
            continue

        x, y = int(round(x_val)), int(round(y_val))
        if x - half_box < 0 or x + half_box >= w or y - half_box < 0 or y + half_box >= h:
            continue
        cutout = data[y-half_box:y+half_box+1, x-half_box:x+half_box+1].copy()
        bg = np.median(cutout)
        cutout -= bg
        cutout[cutout < 0] = 0
        fwhm, ell = calculate_moments(cutout)
        if fwhm is not None:
            results.append({'fwhm': fwhm, 'ellipticity': ell})
    return results

def draw_histogram(data, title, min_val, max_val, bins_count=20):
    """
    テキストベースのヒストグラムを表示する（オーバーフロー対応）
    """
    data_arr = np.array(data)
    counts, bin_edges = np.histogram(data_arr, bins=bins_count, range=(min_val, max_val))
    overflow_count = np.sum(data_arr > max_val)
    all_counts = list(counts) + [overflow_count]
    max_count = max(all_counts) if any(all_counts) else 1
    width = 30
    scale = width / max_count if max_count > width else 1.0
    
    print(f" [{title}]")
    for i in range(len(counts)):
        bar = "#" * int(round(counts[i] * scale))
        label = f"{bin_edges[i]:4.2f}"
        print(f"   {label} | {bar} ({counts[i]})")
    
    bar_ov = "#" * int(round(overflow_count * scale))
    print(f"   >{max_val:3.2f} | {bar_ov} ({overflow_count})")
    print("")

import tempfile

def update_shutter_log(img_path, report):
    """
    shutter_log.json を探し、解析結果を書き込む (Atomic 処理版)
    """
    img_dir = os.path.dirname(os.path.abspath(img_path))
    img_name = os.path.basename(img_path)
    log_path = os.path.join(img_dir, "shutter_log.json")
    
    if not os.path.exists(log_path):
        return False

    temp_fd, temp_path = tempfile.mkstemp(dir=img_dir, prefix="sf_tmp_", suffix=".json")
    try:
        updated = False
        with open(log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for entry in data:
                # ファイル名の照合
                name = entry.get("record", {}).get("file", {}).get("name", "")
                if name and (name == img_name or name in img_name):
                    analysis = entry.setdefault("analysis", {})
                    if report.get("success"):
                        sf_data = {
                            "sf_version": __version__,
                            "sf_status": "success",
                            "sf_timestamp": report["timestamp"],
                            "quality": {
                                "sf_stars": report["stars_analyzed"],
                                "sf_fwhm_mean": round(report["fwhm"]["mean"], 3),
                                "sf_fwhm_med": round(report["fwhm"]["median"], 3),
                                "sf_fwhm_std": round(report["fwhm"]["sigma"], 3),
                                "sf_ell_mean": round(report["ellipticity"]["mean"], 3),
                                "sf_ell_med": round(report["ellipticity"]["median"], 3),
                                "sf_ell_std": round(report["ellipticity"]["sigma"], 3)
                            }
                        }
                    else:
                        sf_data = {
                            "sf_version": __version__,
                            "sf_status": "error",
                            "sf_timestamp": report["timestamp"],
                            "sf_error": report.get("error", "Unknown error")
                        }
                    analysis["SF"] = sf_data
                    updated = True
        
        if updated:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as tmp:
                json.dump(data, tmp, indent=4, ensure_ascii=False)
            os.replace(temp_path, log_path)
            return True
        else:
            os.close(temp_fd)
            if os.path.exists(temp_path): os.remove(temp_path)
    except Exception as e:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try: os.close(temp_fd)
            except: pass
            os.remove(temp_path)
        print(f"  [Warning] Failed to update JSON {log_path}: {e}")
    return False

def update_csv_log(img_path, report):
    """
    shutter_log.csv を探し、解析結果を書き込む (Atomic & Streaming 処理版)
    v1.6.2仕様に強制フォーマット
    """
    img_dir = os.path.dirname(os.path.abspath(img_path))
    img_name = os.path.basename(img_path)
    log_path = os.path.join(img_dir, "shutter_log.csv")
    
    if not os.path.exists(log_path):
        return False

    temp_fd, temp_path = tempfile.mkstemp(dir=img_dir, prefix="sf_tmp_", suffix=".csv")
    try:
        updated = False
        seen_comments = set()
        master_header = [
            "JSON_ver", "Session_ID", "Objective", "Telescope", "Opt", "Filter", 
            "Camera", "Aperture", "Focal_L", "F_num", "Pixel_Size", "Pixel_Scale",
            "LocalTime", "UTC_Time", "UTC_Offset", "LST", "UnixTime", "Sf_Exp_t", 
            "Diff Sf-Exif", "Mode", "Type", "Filename", "SavedDir", "Format", 
            "FileSize", "Width", "Height", "ISO_Exif", "Exposure_Exif", 
            "DateTime_Exif", "Model", "Lat_Exif", "Lon_Exif", "Alt_Exif",
            "RA", "DEC", "RA_HMS", "DEC_DMS", "MT_Status", "Side", "HourAngle",
            "Site_Name", "Lat_INDI", "Lon_INDI", "Alt_INDI", "TZ_Source",
            "Temp_Ext_C", "Humidity_pct", "Pressure_hPa", "DewPoint_C", 
            "Mnt_CPU_Temp_C", "RPi_CPU_Temp_C", "SSE_Version", "Solve_Status", 
            "Solve_Path", "Solve_Confidence", "Solve_Timestamp", "Solve_RA", 
            "Solve_DEC", "Solve_Orientation", "Solve_RA_hms", "Solve_DEC_dms", 
            "Matched_Stars", "Solve_Time_sec", "SF_version", "SF_status", 
            "SF_timestamp", "SF_stars", "SF_fwhm_med", "SF_fwhm_mean", 
            "SF_fwhm_std", "SF_ell_med", "SF_ell_mean", "SF_ell_std"
        ]
        
        legacy_map = {
            "ISO_Timestamp": "LocalTime",
            "Timestamp_UTC": "UTC_Time",
            "Actual_Exp_sec": "Sf_Exp_t",
            "Exp_Diff_sec": "Diff Sf-Exif",
            "Shot_Mode": "Mode",
            "Frame_Type": "Type",
            "File_Name": "Filename",
            "ISO": "ISO_Exif",
            "Shutter_sec": "Exposure_Exif",
            "RA_deg": "RA",
            "Dec_deg": "DEC",
            "Mount_Status": "MT_Status",
            "Side_Of_Pier": "Side",
            "LST_HMS": "LST"
        }

        with open(log_path, 'r', encoding='utf-8-sig', newline='') as f_in, \
             os.fdopen(temp_fd, 'w', encoding='utf-8-sig', newline='') as f_out:
            
            header_line = None
            while True:
                line = f_in.readline()
                if not line:
                    break
                if line.strip().startswith("#"):
                    clean_line = line.strip()
                    if clean_line not in seen_comments:
                        f_out.write(line)
                        seen_comments.add(clean_line)
                else:
                    header_line = line
                    break
            
            if not header_line:
                f_out.flush()
                os.replace(temp_path, log_path)
                return False

            reader = csv.DictReader([header_line])
            actual_reader = csv.DictReader(f_in, fieldnames=reader.fieldnames)
            
            writer = csv.DictWriter(f_out, fieldnames=master_header, extrasaction='ignore')
            writer.writeheader()
            
            for row in actual_reader:
                new_row = {col: row.get(col, "") for col in master_header}
                
                for old_k, new_k in legacy_map.items():
                    if old_k in row and not new_row.get(new_k):
                        new_row[new_k] = row[old_k]
                        
                csv_filename = new_row.get("Filename", "")
                
                if csv_filename and (csv_filename == img_name or csv_filename in img_name):
                    if report.get("success"):
                        new_row["SF_stars"]     = str(report["stars_analyzed"])
                        new_row["SF_fwhm_med"]  = f"{report['fwhm']['median']:.3f}"
                        new_row["SF_fwhm_mean"] = f"{report['fwhm']['mean']:.3f}"
                        new_row["SF_fwhm_std"]  = f"{report['fwhm']['sigma']:.3f}"
                        new_row["SF_ell_med"]   = f"{report['ellipticity']['median']:.3f}"
                        new_row["SF_ell_mean"]  = f"{report['ellipticity']['mean']:.3f}"
                        new_row["SF_ell_std"]   = f"{report['ellipticity']['sigma']:.3f}"
                        new_row["SF_status"]    = "success"
                    else:
                        new_row["SF_stars"]     = ""
                        new_row["SF_fwhm_med"]  = ""
                        new_row["SF_fwhm_mean"] = ""
                        new_row["SF_fwhm_std"]  = ""
                        new_row["SF_ell_med"]   = ""
                        new_row["SF_ell_mean"]  = ""
                        new_row["SF_ell_std"]   = ""
                        new_row["SF_status"]    = "error"
                    new_row["SF_timestamp"] = report["timestamp"]
                    new_row["SF_version"]   = __version__
                    updated = True
                writer.writerow(new_row)
        
        os.replace(temp_path, log_path)
        return updated

    except Exception as e:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try: os.close(temp_fd)
            except: pass
            os.remove(temp_path)
        print(f"  [Warning] Failed to update CSV {log_path}: {e}")
    return False

def check_if_already_processed(img_path, force_mode):
    """
    既に解析済み（かつ同一バージョン）かチェックする
    """
    if force_mode:
        return False
        
    img_dir = os.path.dirname(os.path.abspath(img_path))
    img_name = os.path.basename(img_path)
    log_path = os.path.join(img_dir, "shutter_log.json")
    
    if not os.path.exists(log_path):
        return False

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for entry in data:
                if entry["record"]["file"]["name"] == img_name:
                    sf = entry.get("analysis", {}).get("SF", {})
                    if sf and sf.get("sf_version") == __version__ and sf.get("sf_status") in ["success", "error"]:
                        return True
                    # Fallback for old logs
                    q = entry["record"].get("analysis", {}).get("quality", {})
                    if q and q.get("sf_version") == __version__ and q.get("sf_status") in ["success", "error"]:
                        return True
    except:
        pass
    return False

def process_file(img_path, args):
    """
    1つのファイルを処理する
    """
    start_time = time.time()
    img_name = os.path.basename(img_path)
    
    if check_if_already_processed(img_path, args.force):
        print(f"  [Skip] {img_name} already processed by v{__version__}")
        return None

    print(f"  [Processing] {img_name}...")
    try:
        data = load_image(img_path)
        mean_val, median_val, std_val = sigma_clipped_stats(data, sigma=3.0)
        daofind = DAOStarFinder(fwhm=3.0, threshold=args.snr * std_val)
        stars_found = daofind(data - median_val)
        
        if stars_found is None or len(stars_found) == 0:
            report = {"success": False, "error": "No stars detected", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if not args.no_log:
                if update_shutter_log(img_path, report): report["json_updated"] = True
                if update_csv_log(img_path, report): report["csv_updated"] = True
            return report
            
        stars_found.sort('peak', reverse=True)
        top_stars = stars_found[:args.top_stars]
        quality_list = analyze_star_quality(data - median_val, top_stars, box_size=args.box_size)
        
        if not quality_list:
            report = {"success": False, "error": "Quality analysis failed", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if not args.no_log:
                if update_shutter_log(img_path, report): report["json_updated"] = True
                if update_csv_log(img_path, report): report["csv_updated"] = True
            return report
            
        fwhms = [q['fwhm'] for q in quality_list]
        ells = [q['ellipticity'] for q in quality_list]
        
        report = {
            "success": True,
            "input_file": img_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stars_analyzed": len(quality_list),
            "fwhm": {
                "mean": float(np.mean(fwhms)), "median": float(np.median(fwhms)), "sigma": float(np.std(fwhms))
            },
            "ellipticity": {
                "mean": float(np.mean(ells)), "median": float(np.median(ells)), "sigma": float(np.std(ells))
            },
            "processing_time_sec": round(time.time() - start_time, 2)
        }
        
        # ログの更新
        if not args.no_log:
            if update_shutter_log(img_path, report):
                report["json_updated"] = True
            if update_csv_log(img_path, report):
                report["csv_updated"] = True
        
        # 表示（--plot フラグがある場合）
        if args.plot:
            print("\n" + "-"*17 + f"[ {img_name} ]" + "-"*17)
            print(f" FWHM: {report['fwhm']['mean']:.2f} / σ: {report['fwhm']['sigma']:.2f}")
            draw_histogram(fwhms, "FWHM Distribution", 0, 10, 20)
            print(f" ELL:  {report['ellipticity']['mean']:.2f} / σ: {report['ellipticity']['sigma']:.2f}")
            draw_histogram(ells, "Ellipticity Distribution", 0, 0.5, 20)
            print("-" * 61)
            
        return report

    except Exception as e:
        print(f"  [Error] Failed to process {img_name}: {e}")
        report = {"success": False, "error": str(e), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if not args.no_log:
            if update_shutter_log(img_path, report): report["json_updated"] = True
            if update_csv_log(img_path, report): report["csv_updated"] = True
        return report

def main():
    parser = argparse.ArgumentParser(description=f"StarFlux v{__version__}: Batch Image Quality Analyzer")
    parser.add_argument("path", help="Path to input file OR directory")
    parser.add_argument("--force", action="store_true", help="Re-analyze even if already processed")
    parser.add_argument("--plot", action="store_true", help="Show histograms and dashboard")
    parser.add_argument("--no-log", action="store_true", help="Do not update shutter_log.json")
    parser.add_argument("--top-stars", type=int, default=300, help="Number of top stars to analyze")
    parser.add_argument("--box-size", type=int, default=15, help="Cutout size")
    parser.add_argument("--snr", type=float, default=5.0, help="SNR threshold")
    parser.add_argument("--session", help="Filter by Session ID")
    args = parser.parse_args()

    overall_start = time.time()
    targets = []
    
    if os.path.isdir(args.path):
        print(f"StarFlux v{__version__}>> Scanning directory: {args.path}")
        allowed_files = None
        if args.session:
            allowed_files = set()
            log_path = os.path.join(args.path, "shutter_log.json")
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        for r in json.load(f):
                            if r.get("session_id") == args.session:
                                name = r.get("record", {}).get("file", {}).get("name")
                                if name:
                                    allowed_files.add(name)
                except Exception as e:
                    print(f"StarFlux>> [Warning] Failed to read shutter_log.json for session filter: {e}")

        for f in sorted(os.listdir(args.path)):
            if f.lower().endswith(('.dng', '.raw', '.fits', '.fit', '.fts')):
                if allowed_files is not None and f not in allowed_files:
                    continue
                targets.append(os.path.join(args.path, f))
    else:
        targets = [args.path]

    if not targets:
        print("Done. No targets to process.")
        return

    print(f"StarFlux v{__version__}>> Found {len(targets)} image(s) to analyze.")
    
    success_count = 0
    for t in targets:
        rep = process_file(t, args)
        if rep and rep.get("success"):
            success_count += 1
            
    elapsed = round(time.time() - overall_start, 2)
    print(f"StarFlux v{__version__}>> Finished. {success_count}/{len(targets)} files processed in {elapsed}s.")

if __name__ == "__main__":
    main()
