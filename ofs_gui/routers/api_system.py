import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from core.config import GUI_CONFIG_PATH, SHUTTERPRO_CONFIG_PATH
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
    if os.path.exists(config_path):
        try:
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

            return flat
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Load error: {e}")
    return flat

@router.post("/api/config/save")
async def save_config(request: Request):
    try:
        flat_data = await request.json()
        raw_config = {}
        config_path = SHUTTERPRO_CONFIG_PATH
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config = json.load(f)

        if "SYSTEM" not in raw_config: raw_config["SYSTEM"] = {}
        if "CONTEXT" not in raw_config: raw_config["CONTEXT"] = {}
        if "EQUIPMENT" not in raw_config: raw_config["EQUIPMENT"] = {}

        # Update SYSTEM
        if "save_dir" in flat_data and flat_data["save_dir"] != "":
            raw_config["SYSTEM"]["SAVE_DIR"] = flat_data["save_dir"]
        if "mount" in flat_data: raw_config["SYSTEM"]["INDI_MOUNT"] = flat_data["mount"]
        if "weather" in flat_data: raw_config["SYSTEM"]["INDI_WEATHER"] = flat_data["weather"]
        if "display" in flat_data: raw_config["SYSTEM"]["DISPLAY_MODE"] = flat_data["display"]
        if "log_dest" in flat_data: raw_config["SYSTEM"]["LOG_DEST"] = flat_data["log_dest"]
        if "exposure" in flat_data:
            try: raw_config["SYSTEM"]["DEFAULT_BULB_SEC"] = float(flat_data["exposure"])
            except (ValueError, TypeError): pass
        if "shots" in flat_data:
            try: raw_config["SYSTEM"]["DEFAULT_SHOTS"] = int(flat_data["shots"])
            except (ValueError, TypeError): pass
        if "mode" in flat_data: raw_config["SYSTEM"]["DEFAULT_MODE"] = flat_data["mode"]

        # Update CONTEXT
        if "objective" in flat_data and flat_data["objective"] != "":
            raw_config["CONTEXT"]["objective"] = flat_data["objective"]
        if "session" in flat_data: raw_config["CONTEXT"]["session"] = flat_data["session"]
        if "frame_type" in flat_data: raw_config["CONTEXT"]["frame_type"] = flat_data["frame_type"]

        # Update EQUIPMENT
        if "telescope" in flat_data: raw_config["EQUIPMENT"]["telescope"] = flat_data["telescope"]
        if "camera" in flat_data: raw_config["EQUIPMENT"]["camera"] = flat_data["camera"]
        if "optics" in flat_data: raw_config["EQUIPMENT"]["optics"] = flat_data["optics"]
        if "filter" in flat_data: raw_config["EQUIPMENT"]["filter"] = flat_data["filter"]
        if "focal" in flat_data:
            try:
                if flat_data["focal"] != "":
                    raw_config["EQUIPMENT"]["focal_length_mm"] = int(flat_data["focal"])
            except (ValueError, TypeError): pass

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(raw_config, f, indent=4, ensure_ascii=False)
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
