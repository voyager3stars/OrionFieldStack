import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from core.config import GUI_CONFIG_PATH
import core.state as state

router = APIRouter()

@router.get("/api/status")
async def get_status():
    if state.running_process and state.running_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

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
    return res

@router.get("/api/config/load")
async def load_config():
    if os.path.exists(GUI_CONFIG_PATH):
        try:
            with open(GUI_CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Load error: {e}")
    return {}

@router.post("/api/config/save")
async def save_config(request: Request):
    try:
        config_data = await request.json()
        with open(GUI_CONFIG_PATH, "w") as f:
            json.dump(config_data, f, indent=4)
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
