import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from core.config import GUI_CONFIG_PATH, SHUTTERPRO_CONFIG_PATH, OFS_GUI_CONFIG_PATH
import core.state as state

router = APIRouter()

@router.get("/api/status")
async def get_status():
    if state.running_process and state.running_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

import math

def _sanitize_dict(d):
    clean = {}
    for k, v in d.items():
        if isinstance(v, float) and not math.isfinite(v):
            clean[k] = None
        elif isinstance(v, dict):
            clean[k] = _sanitize_dict(v)
        else:
            clean[k] = v
    return clean

@router.get("/api/telemetry")
async def get_telemetry(mock: bool = False):
    if mock:
        return {
            "indi_server": "CONNECTED",
            "status": "IDLE",
            "ra_deg": 261.6375,
            "dec_deg": 90.0,
            "ra_str": "17h26m33s",
            "dec_str": "+90°00'00\"",
            "side_of_pier": "EAST",
            "latitude": 34.6493,
            "longitude": 135.0015,
            "elevation": 54.0,
            "timestamp_utc": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + "Z",
            "iso_timestamp": datetime.now().astimezone().isoformat(),
            "flashair": "CONNECTED",
            "flashair_url": "http://192.168.50.200"
        }
    res = dict(state.latest_telemetry)
    res["flashair"] = state.latest_flashair.get("flashair", "DISCONNECTED")
    res["flashair_url"] = state.latest_flashair.get("url", "http://192.168.50.200")
    return _sanitize_dict(res)

@router.get("/api/config/load")
async def load_config():
    flat = {}
    config_path = SHUTTERPRO_CONFIG_PATH
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config = json.load(f)

            system = raw_config.get("SYSTEM", {})
            context = raw_config.get("CONTEXT", {})
            equipment = raw_config.get("EQUIPMENT", {})

            # Common settings
            flat["shots"] = system.get("DEFAULT_SHOTS", 10)
            flat["mode"] = system.get("DEFAULT_MODE", "camera")
            flat["exposure"] = system.get("DEFAULT_BULB_SEC", 30.0)
            flat["objective"] = context.get("objective", "Test Target")
            flat["frame_type"] = context.get("frame_type", "test")
            flat["save_dir"] = system.get("SAVE_DIR", "~/Pictures")

            # Equipment Details
            flat["telescope"] = equipment.get("telescope", "")
            flat["camera"] = equipment.get("camera", "")
            flat["optics"] = equipment.get("optics", "")
            flat["filter"] = equipment.get("filter", "")
            flat["focal"] = equipment.get("focal_length_mm", "")

            # Hardware & Network
            flat["session"] = context.get("session", "def")
            flat["mount"] = system.get("INDI_MOUNT", "")
            flat["weather"] = system.get("INDI_WEATHER", "")
            flat["display"] = system.get("DISPLAY_MODE", "full")
            flat["log_dest"] = system.get("LOG_DEST", "s2save")
        
        # GUI specific defaults
        if "save_dir" not in flat: flat["save_dir"] = "~/Pictures"
        if "log-path" not in flat: flat["log-path"] = "../shutterpro03"
        if "sfg-out-dir" not in flat: flat["sfg-out-dir"] = "./output"
        if "sfg-log-path" not in flat: flat["sfg-log-path"] = "../shutterpro03"
        if "sfg-flat-dir" not in flat: flat["sfg-flat-dir"] = ""
        if "sfg-dark-dir" not in flat: flat["sfg-dark-dir"] = ""
        if "sf-outpath" not in flat: flat["sf-outpath"] = ""
        if "sync-save-dir" not in flat: flat["sync-save-dir"] = "~/Pictures/sync"

        # Override with gui config if exists
        if os.path.exists(OFS_GUI_CONFIG_PATH):
            with open(OFS_GUI_CONFIG_PATH, "r", encoding="utf-8") as f:
                gui_flat = json.load(f)
                flat.update(gui_flat)

        return flat
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Load error: {e}")

@router.post("/api/config/save")
async def save_config(request: Request):
    try:
        flat_data = await request.json()
        
        # Save flat_data directly to ofs_gui_config.json
        with open(OFS_GUI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(flat_data, f, indent=4, ensure_ascii=False)
            
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save error: {e}")

@router.get("/api/utils/list_dirs")
async def list_dirs(path: str = "."):
    try:
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(abs_path):
            abs_path = os.path.expanduser("~")
        
        parent = os.path.dirname(abs_path)
        items = os.listdir(abs_path)
        dirs = [d for d in items if os.path.isdir(os.path.join(abs_path, d)) and not d.startswith('.')]
        dirs.sort()
        
        return {
            "current": abs_path,
            "parent": parent,
            "dirs": dirs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
