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

__version__ = "1.2.0"

def apply_flat(img_data, flat_data, color):
    """
    Applies flat field correction to an image.
    img_data and flat_data should be numpy arrays of the same shape.
    """
    # Resize or crop flat_data if shapes don't exactly match (simple check)
    if img_data.shape != flat_data.shape:
        print("  [Warning] Flat image shape does not match Light image. Shape mismatch could cause errors.")

    if color and img_data.ndim == 3:
        # Normalize per channel
        flat_normalized = np.zeros_like(flat_data)
        for c in range(img_data.shape[-1]):
            median_val = np.median(flat_data[..., c])
            if median_val > 0:
                flat_normalized[..., c] = flat_data[..., c] / median_val
            else:
                flat_normalized[..., c] = 1.0
    else:
        # Monochrome or global normalization
        median_val = np.median(flat_data)
        if median_val > 0:
            flat_normalized = flat_data / median_val
        else:
            flat_normalized = np.ones_like(flat_data)
            
    # Apply correction: Light / Normalized_Flat
    # Avoid zero division
    flat_safe = np.maximum(flat_normalized, 1e-5)
    corrected = img_data / flat_safe
    return corrected.astype(np.float32)

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
            # Check v1.6.0 top-level analysis first, fallback to older structure
            analysis = entry.get("analysis")
            if not analysis:
                analysis = entry.get("record", {}).get("analysis", {})
            
            # Support v1.6.0+ structure (analysis -> SF -> quality)
            q = analysis.get("SF", {}).get("quality")
            if q is None:
                # Support older structure (analysis -> quality)
                q = analysis.get("quality", {})
            
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
            # Check v1.6.0 top-level analysis first, fallback to older structure
            analysis = entry.get("analysis")
            if not analysis:
                analysis = entry.get("record", {}).get("analysis", {})
            
            # Support v1.6.0+ structure (analysis -> SF -> quality)
            q = analysis.get("SF", {}).get("quality")
            if q is None:
                # Support older structure (analysis -> quality)
                q = analysis.get("quality", {})
                
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
    parser.add_argument("--flat_dir", default=None, help="Directory containing flat images and their shutter_log.json")
    parser.add_argument("--flat_session", default=None, help="Force a specific session ID for flats (overrides automatic matching)")
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
        
    # 4. Load & Pre-process flats if requested
    flat_map = {}
    if args.flat_dir:
        flat_log_path = os.path.join(args.flat_dir, "shutter_log.json")
        if os.path.exists(flat_log_path):
            print(f"  [Flats] Loading flat metadata from {flat_log_path}...")
            try:
                with open(flat_log_path, 'r', encoding='utf-8') as f:
                    f_log = json.load(f)
                    for entry in f_log:
                        if "record" in entry and "file" in entry["record"]:
                            s_id = entry.get("session_id")
                            f_name = entry["record"]["file"]["name"]
                            f_path = os.path.abspath(os.path.join(args.flat_dir, f_name))
                            if s_id and s_id not in flat_map and os.path.exists(f_path):
                                flat_map[s_id] = f_path
                print(f"  [Flats] Found flats for {len(flat_map)} sessions.")
            except Exception as e:
                print(f"  [Warning] Failed to read flat log: {e}")
        else:
            print(f"  [Warning] No shutter_log.json found in {args.flat_dir}")

    flat_cache = {}
    
    def get_and_apply_flat(img, path):
        if not args.flat_dir:
            return img
            
        # Determine target session ID for flat
        if args.flat_session:
            target_s_id = args.flat_session
        else:
            entry = metadata_map.get(path)
            target_s_id = entry.get("session_id") if entry else None
            
        if target_s_id and target_s_id in flat_map:
            if target_s_id not in flat_cache:
                flat_path = flat_map[target_s_id]
                try:
                    f_data = load_image(flat_path, color=args.color)
                    flat_cache[target_s_id] = f_data
                except Exception as e:
                    print(f"  [Warning] Failed to load flat for session {target_s_id}: {e}")
                    flat_cache[target_s_id] = None
            
            f_data = flat_cache.get(target_s_id)
            if f_data is not None:
                return apply_flat(img, f_data, args.color)
        else:
            if target_s_id and target_s_id not in flat_cache:
                print(f"  [Warning] No flat found for session ID '{target_s_id}' in {args.flat_dir}. Proceeding without flat.")
                flat_cache[target_s_id] = None # Prevent spamming
        return img

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"  [Processing] Initializing stack with {len(valid_files)} frames...")
        
        # Reference is loaded in requested mode
        ref_data = load_image(ref_path, color=args.color)
        ref_data = get_and_apply_flat(ref_data, ref_path)
        
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
                img_data = get_and_apply_flat(img_data, f_path)
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
