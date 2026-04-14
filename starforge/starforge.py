#!/usr/bin/env python3
import os
import sys
import json
import argparse
import glob
import numpy as np
from sf_loader import load_image
from sf_align import register_images
from sf_stack import stack_images, save_stacked_fits

__version__ = "1.1.0"

def get_best_frame(valid_files, metadata_map, criteria='sf_ell_med'):
    """
    Scans the metadata_map to find the entry with the best quality metrics
    among the provided valid_files.
    """
    best_entry = None
    min_val = float('inf')
    
    for f_path in valid_files:
        f_name = os.path.basename(f_path)
        entry = metadata_map.get(f_path)
        if not entry:
            continue
            
        try:
            q = entry.get("record", {}).get("analysis", {}).get("quality", {})
            val = q.get(criteria)
            if val is not None and val < min_val:
                min_val = val
                best_entry = f_path
        except (KeyError, TypeError):
            continue
            
    return best_entry, min_val

def collect_images_and_metadata(inputs, session_filters=None, obj_filters=None):
    """
    Collects image files and their corresponding metadata from shutter_log.json.
    Inputs can be directories, files, or wildcard patterns.
    """
    all_files = []
    for item in inputs:
        expanded = glob.glob(item, recursive=False)
        for path in expanded:
            if os.path.isdir(path):
                # Add all supported images in directory
                for f in os.listdir(path):
                    if f.lower().endswith(('.dng', '.raw', '.fits', '.fit', '.fts')):
                        all_files.append(os.path.abspath(os.path.join(path, f)))
            elif os.path.isfile(path):
                all_files.append(os.path.abspath(path))

    # Remove duplicates and sort
    all_files = sorted(list(set(all_files)))
    
    # Map directories to their logs
    dir_to_log = {}
    metadata_map = {}
    
    final_files = []
    
    for f_path in all_files:
        f_dir = os.path.dirname(f_path)
        f_name = os.path.basename(f_path)
        
        if f_dir not in dir_to_log:
            log_path = os.path.join(f_dir, "shutter_log.json")
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                        # Create mapping: filename -> full entry
                        dir_to_log[f_dir] = { e["record"]["file"]["name"]: e for e in log_data if "record" in e }
                except Exception as e:
                    print(f"  [Warning] Failed to load log in {f_dir}: {e}")
                    dir_to_log[f_dir] = {}
            else:
                dir_to_log[f_dir] = {}
        
        log_entries = dir_to_log[f_dir]
        entry = log_entries.get(f_name)
        
        if not entry:
            print(f"  [Skip] No quality metadata found for: {f_name}")
            continue
            
        # Apply Session/Objective filters
        if session_filters:
            s_id = entry.get("session_id")
            if s_id not in session_filters:
                continue
        
        if obj_filters:
            obj = entry.get("objective")
            if obj not in obj_filters:
                continue
                
        metadata_map[f_path] = entry
        final_files.append(f_path)
        
    return final_files, metadata_map

def filter_by_quality(valid_files, metadata_map, criteria='sf_ell_med', threshold=0.2):
    """
    Returns only files that meet the quality threshold.
    """
    passed = []
    for f_path in valid_files:
        entry = metadata_map.get(f_path)
        if not entry:
            continue
        try:
            q = entry.get("record", {}).get("analysis", {}).get("quality", {})
            val = q.get(criteria)
            if val is not None and val <= threshold:
                passed.append(f_path)
        except (KeyError, TypeError):
            continue
    return passed

def main():
    parser = argparse.ArgumentParser(description=f"StarForge v{__version__}: High-Precision Multi-Session Stacker")
    parser.add_argument("inputs", nargs='+', help="Paths to images, directories, or wildcards")
    parser.add_argument("--threshold", type=float, default=0.2, help="Ellipticity threshold for filtering (default: 0.2)")
    parser.add_argument("--session", nargs='+', help="Filter by Session ID(s)")
    parser.add_argument("--obj", nargs='+', help="Filter by Objective name(s)")
    parser.add_argument("--color", action="store_true", help="Enable color (RGB) processing")
    parser.add_argument("--method", choices=['median', 'mean', 'sigma_clip'], default='sigma_clip', help="Stacking method")
    parser.add_argument("--out", default="master_stacked.fits", help="Output filename")
    parser.add_argument("--limit", type=int, help="Limit number of frames to stack")
    args = parser.parse_args()

    mode_str = "COLOR" if args.color else "MONO"
    print(f"StarForge v{__version__} [{mode_str}] >> Initializing file collection...")
    
    # 1. Collect & Initial Filter (Existence, Metadata, Session/Obj)
    initial_files, metadata_map = collect_images_and_metadata(args.inputs, args.session, args.obj)
    
    if not initial_files:
        print("[Error] No valid files found matching criteria.")
        sys.exit(1)
        
    print(f"  [Collect] Found {len(initial_files)} files with metadata.")

    # 2. Select Reference (Best ellipticity among initial set)
    # Reference frame is always loaded as mono for quality check anyway, but here we just need the path
    ref_path, ref_val = get_best_frame(initial_files, metadata_map)
    if not ref_path:
        print("[Error] No valid quality analysis found. Please run StarFlux first.")
        sys.exit(1)
    
    ref_name = os.path.basename(ref_path)
    print(f"  [Auto-Ref] Selected: {ref_name} (ell: {ref_val:.3f})")
    
    # 3. Quality Filtering
    valid_files = filter_by_quality(initial_files, metadata_map, threshold=args.threshold)
    print(f"  [Filter] {len(valid_files)} frames passed quality threshold (ell <= {args.threshold}).")
    
    if args.limit:
        valid_files = valid_files[:args.limit]
        print(f"  [Limit] Capped to {len(valid_files)} frames.")
        
    if not valid_files:
        print("[Error] No frames passed the filter. Try a looser threshold.")
        sys.exit(1)
        
    # 4. Load & Pre-process images
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"  [Processing] Initializing stack with {len(valid_files)} frames...")
        
        # Reference is loaded in requested mode
        ref_data = load_image(ref_path, color=args.color)
        
        # Save reference to disk
        ref_tmp_path = os.path.join(tmp_dir, "ref_aligned.npy")
        np.save(ref_tmp_path, ref_data)
        
        aligned_images = [ref_tmp_path]
        count = 1
        
        for f_path in valid_files:
            if f_path == ref_path:
                continue
            
            f_name = os.path.basename(f_path)
            print(f"  [{count+1}/{len(valid_files)}] Registering {f_name}...")
            
            try:
                img_data = load_image(f_path, color=args.color)
                aligned, _ = register_images(ref_data, img_data)
                
                if aligned is not None:
                    # Save to disk instead of keeping in RAM
                    tmp_path = os.path.join(tmp_dir, f"aligned_{count}.npy")
                    np.save(tmp_path, aligned)
                    aligned_images.append(tmp_path)
                    count += 1
                else:
                    print(f"  [Skip] Alignment failed for: {f_name}")
            except Exception as e:
                print(f"  [Error] Failed to process {f_name}: {e}")
                
        # 5. Final Stacking
        print(f"  [Stacking] Method: {args.method} ({len(aligned_images)} frames)...")
        master_frame = stack_images(aligned_images, method=args.method)
        
        if master_frame is not None:
            save_stacked_fits(master_frame, args.out)
            print(f"Success! Saved to: {args.out}")
        else:
            print("[Error] Stacking failed.")

if __name__ == "__main__":
    main()
