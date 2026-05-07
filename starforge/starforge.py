#!/usr/bin/env python3
import os
import sys
import json
import argparse
import glob
import tempfile
import numpy as np
from sf_loader import load_image
from sf_align import register_images
from sf_stack import stack_images, save_stacked_fits

__version__ = "1.3.3"

# ANSI Colors
C_YELLOW_GREEN = "\033[38;5;154m"
C_RESET = "\033[0m"

class CustomHelpFormatter(argparse.HelpFormatter):
    """
    Custom formatter that displays current values aligned on the right.
    """
    def _format_action(self, action):
        # Format the basic help output
        original = super()._format_action(action)
        
        # Skip for positional arguments or help
        if not action.option_strings or action.dest == 'help':
            return original

        # Get current value
        val = action.default
        if val is None:
            val_str = "None"
        elif isinstance(val, bool):
            val_str = "color" if val else "mono" # Legacy compatibility during transition
        else:
            val_str = str(val)

        # Split description to find where to append
        lines = original.splitlines()
        if not lines:
            return original

        # Find the first line with the description
        # Usually it's the first line, but we need to find where the option strings end
        # A simpler way: just append to the first line with padding
        first_line = lines[0]
        
        # Alignment position
        align_pos = 50
        
        if len(first_line) < align_pos:
            padding = align_pos - len(first_line)
            lines[0] = f"{first_line}{' ' * padding}{C_YELLOW_GREEN}[{val_str}]{C_RESET}"
        else:
            lines[0] = f"{first_line}  {C_YELLOW_GREEN}[{val_str}]{C_RESET}"
            
        return "\n".join(lines) + "\n"

def load_config():
    """Loads settings from config.json if it exists."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    defaults = {
        "threshold": 0.2,
        "method": "sigma_clip",
        "mode": "mono",
        "out": "AUTO",
        "limit": None,
        "flat_dir": None,
        "flat_session": None,
        "use_flat": True,
        "session": None,
        "obj": None
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cf = json.load(f)
                # Expand tildes in paths
                if cf.get("flat_dir"):
                    cf["flat_dir"] = os.path.expanduser(cf["flat_dir"])
                # Handle legacy 'color' key if present
                if "color" in cf:
                    cf["mode"] = "color" if cf.pop("color") else "mono"
                defaults.update(cf)
        except Exception as e:
            print(f"  [Warning] Failed to load config.json: {e}")
    return defaults


def get_nested_val(data, keys, default=None):
    """Safe retrieval from nested dictionaries."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return default
    return data if data is not None else default


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
    among the provided valid_files. Fully v1.6.2 compliant.
    """
    best_entry = None
    min_val = float('inf')
    
    for f_path in valid_files:
        entry = metadata_map.get(f_path)
        if not entry:
            continue
            
        # Try finding quality based on v1.6.2 -> v1.6.1 -> legacy
        # v1.6.2+: top-level 'analysis' -> 'SF' -> 'quality'
        q = get_nested_val(entry, ["analysis", "SF", "quality"])
        if q is None:
            # v1.6.1: top-level 'analysis' -> 'quality'
            q = get_nested_val(entry, ["analysis", "quality"])
        if q is None:
            # v1.6.0: 'record' -> 'analysis' -> 'quality'
            q = get_nested_val(entry, ["record", "analysis", "quality"])
            
        if q:
            val = q.get(criteria)
            if val is not None and val < min_val:
                min_val = val
                best_entry = f_path
            
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
    Returns only files that meet the quality threshold. Fully v1.6.2 compliant.
    """
    passed = []
    for f_path in valid_files:
        entry = metadata_map.get(f_path)
        if not entry:
            continue
            
        q = get_nested_val(entry, ["analysis", "SF", "quality"])
        if q is None:
            q = get_nested_val(entry, ["analysis", "quality"])
        if q is None:
            q = get_nested_val(entry, ["record", "analysis", "quality"])
                
        if q:
            val = q.get(criteria)
            if val is not None and val <= threshold:
                passed.append(f_path)
                
    return passed

def main():
    import datetime
    conf = load_config()
    
    parser = argparse.ArgumentParser(
        description=f"StarForge v{__version__}: High-Precision Multi-Session Stacker",
        formatter_class=CustomHelpFormatter
    )
    parser.add_argument("inputs", nargs='+', help="Paths to images, directories, or wildcards")
    parser.add_argument("--threshold", type=float, default=conf["threshold"], help="Ellipticity threshold for filtering")
    parser.add_argument("--session", nargs='+', default=conf["session"], help="Filter by Session ID(s)")
    parser.add_argument("--obj", nargs='+', default=conf["obj"], help="Filter by Objective name(s)")
    parser.add_argument("--mode", choices=['color', 'mono'], default=conf["mode"], help="Processing mode")
    parser.add_argument("--method", choices=['median', 'mean', 'sigma_clip'], default=conf["method"], help="Stacking method")
    parser.add_argument("--out", default=conf["out"], help="Output filename (AUTO for dynamic name)")
    parser.add_argument("--limit", type=int, default=conf["limit"], help="Limit number of frames to stack")
    parser.add_argument("--flat_dir", default=conf["flat_dir"], help="Directory containing flat images")
    parser.add_argument("--flat_session", default=conf["flat_session"], help="Force a specific session ID for flats")
    
    # Flat on/off toggle
    flat_group = parser.add_mutually_exclusive_group()
    flat_group.add_argument("--flat", action="store_true", dest="use_flat", default=conf["use_flat"], help="Enable flat correction")
    flat_group.add_argument("--no-flat", action="store_false", dest="use_flat", help="Disable flat correction")
    
    args = parser.parse_args()
    
    # Internal flag for compatibility with functions
    args.color = (args.mode == 'color')
    
    # Post-process inputs to expand tildes
    args.inputs = [os.path.expanduser(i) for i in args.inputs]
    if args.flat_dir:
        args.flat_dir = os.path.expanduser(args.flat_dir)

    mode_str = args.mode.upper()
    print(f"StarForge v{__version__} [{mode_str}] >> Initializing file collection...")
    
    # 1. Collect & Initial Filter (Existence, Metadata, Session/Obj)
    initial_files, metadata_map = collect_images_and_metadata(args.inputs, args.session, args.obj)
    
    if not initial_files:
        print("[Error] No valid files found matching criteria.")
        sys.exit(1)
        
    print(f"  [Collect] Found {len(initial_files)} files with metadata.")

    # Dynamic output name generation if needed
    if args.out == "AUTO":
        # Extract sessions and objectives from the metadata of participating files
        sessions = sorted(list(set([m.get("session_id") for m in metadata_map.values() if m.get("session_id")])))
        objs = sorted(list(set([m.get("objective") for m in metadata_map.values() if m.get("objective")])))
        
        s_part = sessions[0] if len(sessions) == 1 else ("MultiSession" if sessions else "NoSession")
        o_part = objs[0] if len(objs) == 1 else ("MultiObject" if objs else "NoObject")
        now_str = datetime.datetime.now().strftime("%y%m%d%H%M")
        args.out = f"{s_part}_{o_part}_{args.mode}_{now_str}.fits"
        print(f"  [Auto-Out] Generated filename: {args.out}")

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
    # We collect all flats per session to support master flat generation
    flat_inventory = {}
    if args.flat_dir:
        flat_log_path = os.path.join(args.flat_dir, "shutter_log.json")
        if os.path.exists(flat_log_path):
            print(f"  [Flats] Inventorying flat files from {flat_log_path}...")
            try:
                with open(flat_log_path, 'r', encoding='utf-8') as f:
                    f_log = json.load(f)
                    for entry in f_log:
                        if "record" in entry and "file" in entry["record"]:
                            s_id = entry.get("session_id")
                            if not s_id: continue
                            f_name = entry["record"]["file"]["name"]
                            f_path = os.path.abspath(os.path.join(args.flat_dir, f_name))
                            if os.path.exists(f_path):
                                if s_id not in flat_inventory:
                                    flat_inventory[s_id] = []
                                flat_inventory[s_id].append(f_path)
                print(f"  [Flats] Found flat frames for {len(flat_inventory)} sessions.")
            except Exception as e:
                print(f"  [Warning] Failed to read flat log: {e}")
        else:
            print(f"  [Warning] No shutter_log.json found in {args.flat_dir}")

    flat_cache = {}

    def get_and_apply_flat(img, path):
        if not args.flat_dir or not args.use_flat:
            return img
            
        # Determine target session ID for flat
        if args.flat_session:
            target_s_id = args.flat_session
        else:
            entry = metadata_map.get(path)
            target_s_id = entry.get("session_id") if entry else None
            
        if not target_s_id:
            return img

        if target_s_id in flat_cache:
            f_data = flat_cache[target_s_id]
            return apply_flat(img, f_data, args.color) if f_data is not None else img

        # Try to find or generate master flat
        master_name = f"master_flat_{target_s_id}_{args.mode}.fits"
        master_path = os.path.join(args.flat_dir, master_name)
        
        if os.path.exists(master_path):
            print(f"  [Flats] Found existing master flat: {master_name}")
            try:
                f_data = load_image(master_path, color=args.color)
                flat_cache[target_s_id] = f_data
                return apply_flat(img, f_data, args.color)
            except Exception as e:
                print(f"  [Error] Failed to load master flat {master_name}: {e}")
                flat_cache[target_s_id] = None
                return img

        # Generate new master flat if multiple frames are available
        flats_to_process = flat_inventory.get(target_s_id, [])
        if not flats_to_process:
            if target_s_id not in flat_cache:
                print(f"  [Warning] No flat frames found for session: {target_s_id}")
                flat_cache[target_s_id] = None
            return img

        print(f"  [Flats] Generating master flat for session {target_s_id} ({len(flats_to_process)} frames)...")
        try:
            with tempfile.TemporaryDirectory() as flat_tmp_dir:
                npy_paths = []
                for i, f_p in enumerate(flats_to_process):
                    f_img = load_image(f_p, color=args.color)
                    tmp_npy = os.path.join(flat_tmp_dir, f"flat_{i}.npy")
                    np.save(tmp_npy, f_img)
                    npy_paths.append(tmp_npy)
                
                # Stack without registration for flats
                master_f_data = stack_images(npy_paths, method='median')
                if master_f_data is not None:
                    save_stacked_fits(master_f_data, master_path)
                    print(f"  [Flats] Saved new master flat: {master_name}")
                    flat_cache[target_s_id] = master_f_data
                    return apply_flat(img, master_f_data, args.color)
                else:
                    flat_cache[target_s_id] = None
                    return img
        except Exception as e:
            print(f"  [Error] Failed to generate master flat for session {target_s_id}: {e}")
            flat_cache[target_s_id] = None
            return img

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
