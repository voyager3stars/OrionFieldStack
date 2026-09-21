import asyncio
import io
import json
import math
import os
import subprocess
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

import OSM_map_manager

app = FastAPI(title="OrionFieldStack Map GUI")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TILES_DIR = os.path.join(BASE_DIR, "data", "tiles")

# Gray tile cache
_gray_tile_bytes = None

def get_gray_tile():
    global _gray_tile_bytes
    if _gray_tile_bytes is None:
        img = Image.new('RGB', (256, 256), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        _gray_tile_bytes = buf.getvalue()
    return _gray_tile_bytes

# --- Tile Server ---
def get_fallback_tile(z, x, y):
    # Try to find a parent tile
    current_z, current_x, current_y = z, x, y
    for level_diff in range(1, z + 1):
        parent_z = z - level_diff
        parent_x = x // (2 ** level_diff)
        parent_y = y // (2 ** level_diff)
        
        parent_path = os.path.join(TILES_DIR, str(parent_z), str(parent_x), f"{parent_y}.png")
        if os.path.exists(parent_path):
            try:
                img = Image.open(parent_path).convert("RGBA")
                scale = 2 ** level_diff
                crop_x = (x % scale) * (256 // scale)
                crop_y = (y % scale) * (256 // scale)
                
                cropped = img.crop((crop_x, crop_y, crop_x + 256 // scale, crop_y + 256 // scale))
                resized = cropped.resize((256, 256), Image.NEAREST)
                
                # Dark overlay
                overlay = Image.new('RGBA', (256, 256), (0, 0, 0, 150))
                blended = Image.alpha_composite(resized, overlay)
                
                draw = ImageDraw.Draw(blended)
                text = "Map data isn't available"
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", 16)
                except:
                    font = ImageFont.load_default()
                
                try:
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                except AttributeError:
                    text_w, text_h = draw.textsize(text, font=font)
                    
                text_x = (256 - text_w) / 2
                text_y = (256 - text_h) / 2
                draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)
                
                buf = io.BytesIO()
                blended.save(buf, format='PNG')
                return buf.getvalue()
            except Exception as e:
                print("Fallback error:", e)
                break

    return get_gray_tile()

@app.get("/tiles/{z}/{x}/{y}.png")
async def serve_tile(z: int, x: int, y: int):
    tile_path = os.path.join(TILES_DIR, str(z), str(x), f"{y}.png")
    if os.path.exists(tile_path):
        return FileResponse(tile_path, media_type="image/png")
    else:
        # Return fallback image if tile is missing
        return StreamingResponse(io.BytesIO(get_fallback_tile(z, x, y)), media_type="image/png")

# --- GPS API ---
@app.get("/api/location")
def get_location():
    """
    Calls ofs_link.py to get the current location.
    ofs_link automatically handles GPSD integration and fallbacks.
    """
    try:
        # Assuming ofs_link.py is in the sibling directory
        ofs_link_dir = os.path.join(BASE_DIR, "..", "ofs_link")
        ofs_link_path = os.path.join(ofs_link_dir, "ofs_link.py")
        
        # Use sys.executable to ensure we use the same virtual environment
        import sys
        result = subprocess.run(
            [sys.executable, ofs_link_path, "--get"],
            cwd=ofs_link_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            def safe_num(v):
                try:
                    f = float(v)
                    return f if math.isfinite(f) else None
                except:
                    return None
            return JSONResponse(content={
                "lat": safe_num(data.get("latitude")),
                "lon": safe_num(data.get("longitude")),
                "elevation": safe_num(data.get("elevation"))
            })
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to run ofs_link", "details": result.stderr})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- Management API ---
class RegionModel(BaseModel):
    name: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    min_zoom: int
    max_zoom: int

@app.get("/api/regions")
async def get_regions():
    data = OSM_map_manager.load_regions()
    return JSONResponse(content=data)

@app.post("/api/regions")
async def add_region(region: RegionModel):
    data = OSM_map_manager.load_regions()
    for r in data.get('regions', []):
        if r['name'] == region.name:
            raise HTTPException(status_code=400, detail="Region already exists")
    
    data.setdefault('regions', []).append(region.dict())
    OSM_map_manager.save_regions(data)
    return JSONResponse(content={"status": "ok"})

@app.delete("/api/regions/{name}")
async def delete_region(name: str, background_tasks: BackgroundTasks):
    data = OSM_map_manager.load_regions()
    initial_len = len(data.get('regions', []))
    data['regions'] = [r for r in data.get('regions', []) if r['name'] != name]
    
    if len(data.get('regions', [])) == initial_len:
        raise HTTPException(status_code=404, detail="Region not found")
        
    OSM_map_manager.save_regions(data)
    
    # 未使用タイルのクリーンアップをバックグラウンドで実行
    if not sync_state["is_syncing"]:
        def run_cleanup():
            try:
                from core.sync_engine import cleanup_unused_tiles
                cleanup_unused_tiles(data, BASE_DIR)
            except Exception as e:
                print("Cleanup error:", e)
        background_tasks.add_task(run_cleanup)
        
    return JSONResponse(content={"status": "deleted"})

class BoundsModel(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    target_level: str

@app.post("/api/download_bounds")
async def download_bounds(bounds: BoundsModel, background_tasks: BackgroundTasks):
    data = OSM_map_manager.load_regions()
    
    min_z = 7
    if bounds.target_level == 'medium':
        max_z = 14
    elif bounds.target_level == 'detailed':
        max_z = 19
    else:
        try:
            max_z = int(bounds.target_level)
        except ValueError:
            max_z = 14
        
    import time
    region_name = f"Custom_Area_{int(time.time())}"
    
    region_data = {
        "name": region_name,
        "min_lat": bounds.min_lat,
        "max_lat": bounds.max_lat,
        "min_lon": bounds.min_lon,
        "max_lon": bounds.max_lon,
        "min_zoom": min_z,
        "max_zoom": max_z
    }
    
    data.setdefault('regions', []).append(region_data)
    OSM_map_manager.save_regions(data)
    
    if not sync_state["is_syncing"]:
        background_tasks.add_task(background_sync)
        
    return JSONResponse(content={"status": "started", "region": region_name})

# Global state for sync progress
sync_state = {"is_syncing": False, "status": "Idle"}
sync_cancel_event = threading.Event()

def background_sync():
    global sync_state
    if sync_state["is_syncing"]:
        return
    sync_state["is_syncing"] = True
    sync_state["status"] = "Calculating tiles..."
    sync_cancel_event.clear()
    
    def progress_callback(current, total):
        pct = (current / total) * 100 if total > 0 else 0
        sync_state["status"] = f"Downloading: {current}/{total} tiles ({pct:.1f}%)"
        
    try:
        data = OSM_map_manager.load_regions()
        from core.sync_engine import sync_tiles
        sync_tiles(data, BASE_DIR, cancel_event=sync_cancel_event, progress_callback=progress_callback)
        if sync_cancel_event.is_set():
            sync_state["status"] = "Cancelled"
        else:
            sync_state["status"] = "Completed"
    except Exception as e:
        sync_state["status"] = f"Error: {e}"
    finally:
        sync_state["is_syncing"] = False

@app.post("/api/sync")
async def start_sync(background_tasks: BackgroundTasks):
    global sync_state
    if sync_state["is_syncing"]:
        return JSONResponse(content={"status": "already syncing"})
    background_tasks.add_task(background_sync)
    return JSONResponse(content={"status": "sync started"})

@app.post("/api/sync/cancel")
async def cancel_sync():
    if sync_state["is_syncing"]:
        sync_cancel_event.set()
        return JSONResponse(content={"status": "cancelling"})
    return JSONResponse(content={"status": "not syncing"})

@app.post("/api/estimate_download")
async def estimate_download(bounds: BoundsModel):
    min_z = 7
    if bounds.target_level == 'medium':
        max_z = 14
    elif bounds.target_level == 'detailed':
        max_z = 19
    else:
        try:
            max_z = int(bounds.target_level)
        except ValueError:
            max_z = 14
            
    region_data = {
        "name": "Estimate",
        "min_lat": bounds.min_lat,
        "max_lat": bounds.max_lat,
        "min_lon": bounds.min_lon,
        "max_lon": bounds.max_lon,
        "min_zoom": min_z,
        "max_zoom": max_z
    }
    
    from core.tile_math import deg2num
    count = 0
    for z in range(min_z, max_z + 1):
        min_x, min_y = deg2num(bounds.max_lat, bounds.min_lon, z)
        max_x, max_y = deg2num(bounds.min_lat, bounds.max_lon, z)
        # Add 1 because the range is inclusive
        count += (max_x - min_x + 1) * (max_y - min_y + 1)
    
    # Approx 15 KB per tile, 0.2 seconds per tile
    kb = count * 15
    mb = kb / 1024
    seconds = count * 0.2
    
    return JSONResponse(content={
        "tiles": count,
        "megabytes": round(mb, 1),
        "seconds": round(seconds, 1)
    })

@app.get("/api/sync/status")
async def get_sync_status():
    global sync_state
    return JSONResponse(content=sync_state)

# --- Static Pages ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/admin")
async def admin():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
