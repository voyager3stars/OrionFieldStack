import os
import time
import urllib.request
import urllib.error
from .tile_math import get_tiles_for_region

TILE_SERVER = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "OrionFieldStack-MapManager/1.0"
DOWNLOAD_DELAY = 0.2 # seconds

def cleanup_unused_tiles(regions_data, base_dir):
    """
    Deletes tiles that are no longer required by any region.
    """
    print("Calculating required tiles across all regions for cleanup...")
    required_tiles = set()
    for region in regions_data.get('regions', []):
        tiles = get_tiles_for_region(region)
        required_tiles.update(tiles)
        
    tiles_dir = os.path.join(base_dir, "data", "tiles")
    if not os.path.exists(tiles_dir):
        return 0
        
    existing_tiles = set()
    for root, dirs, files in os.walk(tiles_dir):
        for file in files:
            if file.endswith('.png'):
                parts = os.path.relpath(os.path.join(root, file), tiles_dir).split(os.sep)
                if len(parts) == 3:
                    try:
                        z, x, y = int(parts[0]), int(parts[1]), int(parts[2].replace('.png', ''))
                        existing_tiles.add((z, x, y))
                    except ValueError:
                        pass
                        
    tiles_to_delete = existing_tiles - required_tiles
    deleted_count = 0
    if tiles_to_delete:
        print("\nDeleting unused tiles...")
        for z, x, y in tiles_to_delete:
            filepath = os.path.join(tiles_dir, str(z), str(x), f"{y}.png")
            if os.path.exists(filepath):
                os.remove(filepath)
                deleted_count += 1
        print(f"Successfully deleted {deleted_count} unused tiles.")
        
        # Cleanup empty directories
        for root, dirs, files in os.walk(tiles_dir, topdown=False):
            if not os.listdir(root) and root != tiles_dir:
                os.rmdir(root)
    return deleted_count

def sync_tiles(regions_data, base_dir, cancel_event=None, progress_callback=None):
    """
    Synchronizes the local tiles with the regions specified in regions_data.
    """
    print("Calculating required tiles across all regions...")
    required_tiles = set()
    for region in regions_data.get('regions', []):
        tiles = get_tiles_for_region(region)
        required_tiles.update(tiles)
        print(f"  - {region['name']}: {len(tiles)} tiles calculated")
        
    print(f"Total unique required tiles: {len(required_tiles)}")
    
    # Check existing tiles
    tiles_dir = os.path.join(base_dir, "data", "tiles")
    if not os.path.exists(tiles_dir):
        os.makedirs(tiles_dir)
        
    existing_tiles = set()
    for root, dirs, files in os.walk(tiles_dir):
        for file in files:
            if file.endswith('.png'):
                parts = os.path.relpath(os.path.join(root, file), tiles_dir).split(os.sep)
                if len(parts) == 3:
                    try:
                        z, x, y = int(parts[0]), int(parts[1]), int(parts[2].replace('.png', ''))
                        existing_tiles.add((z, x, y))
                    except ValueError:
                        pass

    print(f"Existing local tiles: {len(existing_tiles)}")
    
    tiles_to_download = required_tiles - existing_tiles
    
    # Clean up unused tiles using the separated function
    cleanup_unused_tiles(regions_data, base_dir)
    
    # Download missing tiles
    if tiles_to_download:
        print("\nDownloading missing tiles...")
        downloaded_count = 0
        failed_count = 0
        total_to_download = len(tiles_to_download)
        
        req_headers = {'User-Agent': USER_AGENT}
        
        for idx, (z, x, y) in enumerate(tiles_to_download, 1):
            if cancel_event and cancel_event.is_set():
                print("\nSync cancelled by user.")
                break
                
            url = TILE_SERVER.format(z=z, x=x, y=y)
            filepath = os.path.join(tiles_dir, str(z), str(x), f"{y}.png")
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            req = urllib.request.Request(url, headers=req_headers)
            try:
                with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
                    out_file.write(response.read())
                downloaded_count += 1
                
                # Print progress
                if progress_callback:
                    progress_callback(idx, total_to_download)
                if idx % 10 == 0 or idx == total_to_download:
                    print(f"  Progress: {idx}/{total_to_download} ({(idx/total_to_download)*100:.1f}%)", end='\r')
                    
                time.sleep(DOWNLOAD_DELAY)
            except urllib.error.URLError as e:
                failed_count += 1
                print(f"\n  Failed to download tile {z}/{x}/{y}: {e}")
                
        print(f"\nDownload complete. Success: {downloaded_count}, Failed: {failed_count}")
    
    print("\nSync process completed.")
