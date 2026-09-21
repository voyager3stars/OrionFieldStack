#!/usr/bin/env python3
import argparse
import json
import os
import sys

from core.sync_engine import sync_tiles
from core.tile_math import get_tiles_for_region

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGIONS_FILE = os.path.join(BASE_DIR, "data", "regions.json")

def load_regions():
    if not os.path.exists(REGIONS_FILE):
        return {"regions": []}
    with open(REGIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_regions(data):
    os.makedirs(os.path.dirname(REGIONS_FILE), exist_ok=True)
    with open(REGIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def cmd_add(args):
    data = load_regions()
    
    # Check if region already exists
    for region in data['regions']:
        if region['name'] == args.name:
            print(f"Error: Region '{args.name}' already exists.")
            sys.exit(1)
            
    new_region = {
        "name": args.name,
        "min_lat": args.min_lat,
        "max_lat": args.max_lat,
        "min_lon": args.min_lon,
        "max_lon": args.max_lon,
        "min_zoom": args.min_zoom,
        "max_zoom": args.max_zoom if args.max_zoom is not None else 6
    }
    
    data['regions'].append(new_region)
    save_regions(data)
    print(f"Successfully added region '{args.name}'. Run 'sync' to download tiles.")

def cmd_remove(args):
    data = load_regions()
    initial_count = len(data['regions'])
    
    data['regions'] = [r for r in data['regions'] if r['name'] != args.name]
    
    if len(data['regions']) < initial_count:
        save_regions(data)
        print(f"Successfully removed region '{args.name}'. Run 'sync' to delete unused tiles.")
    else:
        print(f"Error: Region '{args.name}' not found.")
        sys.exit(1)

def cmd_list(args):
    data = load_regions()
    regions = data.get('regions', [])
    
    if not regions:
        print("No regions configured.")
        return
        
    print(f"{'Name':<20} | {'Zoom Range':<12} | {'BBox (Lat, Lon)':<40} | {'Calculated Tiles'}")
    print("-" * 95)
    
    total_tiles = 0
    all_tiles_set = set()
    
    for r in regions:
        tiles = get_tiles_for_region(r)
        tile_count = len(tiles)
        all_tiles_set.update(tiles)
        
        bbox_str = f"[{r['min_lat']}, {r['max_lat']}] x [{r['min_lon']}, {r['max_lon']}]"
        zoom_str = f"{r['min_zoom']} - {r['max_zoom']}"
        print(f"{r['name']:<20} | {zoom_str:<12} | {bbox_str:<40} | {tile_count}")
        
    print("-" * 95)
    print(f"Total unique tiles required across all regions: {len(all_tiles_set)}")

def cmd_sync(args):
    data = load_regions()
    sync_tiles(data, BASE_DIR)

def main():
    parser = argparse.ArgumentParser(description="OSM Map Manager for offline tile synchronization.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # ADD command
    parser_add = subparsers.add_parser("add", help="Add a new region configuration")
    parser_add.add_argument("--name", required=True, help="Unique name for the region")
    parser_add.add_argument("--min-lat", type=float, required=True, help="Minimum Latitude")
    parser_add.add_argument("--max-lat", type=float, required=True, help="Maximum Latitude")
    parser_add.add_argument("--min-lon", type=float, required=True, help="Minimum Longitude")
    parser_add.add_argument("--max-lon", type=float, required=True, help="Maximum Longitude")
    parser_add.add_argument("--min-zoom", type=int, required=True, help="Minimum Zoom Level")
    parser_add.add_argument("--max-zoom", type=int, required=True, help="Maximum Zoom Level")
    parser_add.set_defaults(func=cmd_add)
    
    # REMOVE command
    parser_remove = subparsers.add_parser("remove", help="Remove a region configuration")
    parser_remove.add_argument("--name", required=True, help="Name of the region to remove")
    parser_remove.set_defaults(func=cmd_remove)
    
    # LIST command
    parser_list = subparsers.add_parser("list", help="List all configured regions")
    parser_list.set_defaults(func=cmd_list)
    
    # SYNC command
    parser_sync = subparsers.add_parser("sync", help="Synchronize local tiles with configured regions")
    parser_sync.set_defaults(func=cmd_sync)
    
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
