import os
import sys
import json
import asyncio
from typing import Optional
from urllib.parse import quote
from datetime import datetime
from fastapi import APIRouter, Form, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from core.config import SHUTTERPRO_PATH, BASE_DIR
import core.state as state

router = APIRouter()

@router.post("/api/shutter/start")
async def start_shutter(request: Request):
    async with state.process_lock:
        if state.running_process and state.running_process.returncode is None:
            raise HTTPException(status_code=400, detail="A process is already running.")

        form_data = await request.form()
        
        # Positional arguments: [shots] [mode] [exposure]
        shots = form_data.get("shots", "1")
        mode = form_data.get("mode", "camera")
        exposure = form_data.get("exposure", "10.0")

        # Use -u for unbuffered output to get real-time logs
        cmd = [sys.executable, "-u", SHUTTERPRO_PATH, shots, mode, exposure]

        # Key-Value arguments
        kv_mapping = {
            "objective": "obj",
            "session": "sess",
            "frame_type": "type",
            "telescope": "tel",
            "optics": "opt",
            "camera": "cam",
            "filter": "fil",
            "focal": "f",
            "save_dir": "dir",
            "display": "display",
            "log_dest": "log_dest",
            "mount": "mnt",
            "weather": "wth"
        }

        for form_key, cli_key in kv_mapping.items():
            val = form_data.get(form_key)
            if val is not None and val != "":
                cmd.append(f"{cli_key}={val}")
        
        try:
            # Set environment variable to ensure python output is unbuffered
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            state.running_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "shutterpro03"),
                env=env
            )
            return {"status": "started", "pid": state.running_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/shutter/logs")
async def stream_logs():
    async def log_generator():
        if not state.running_process:
            yield "data: No process running\n\n"
            return

        try:
            while True:
                line = await state.running_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.post("/api/shutter/stop")
async def stop_shutter():
    async with state.process_lock:
        if state.running_process and state.running_process.returncode is None:
            state.running_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@router.get("/api/shutter/preview/latest")
async def get_shutter_latest_preview(dir: Optional[str] = Query(None)):
    """撮影保存先から最新の撮影画像およびメタデータを取得する"""
    save_dir = dir if dir else "~/Pictures"
    abs_dir = os.path.abspath(os.path.expanduser(save_dir))
    
    if not os.path.exists(abs_dir):
        return {"status": "success", "has_image": False, "message": "Directory does not exist"}

    latest_json_path = os.path.join(abs_dir, "latest_shot.json")
    
    # 1. latest_shot.json からの読み出しを優先試行
    if os.path.exists(latest_json_path):
        try:
            with open(latest_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            if isinstance(data, list) and data:
                record_root = data[-1]
            elif isinstance(data, dict):
                record_root = data
            else:
                record_root = None
                
            if record_root:
                record = record_root.get("record", {})
                file_info = record.get("file", {})
                filename = file_info.get("name")
                file_stored_dir = file_info.get("path") or abs_dir
                file_abs_dir = os.path.abspath(os.path.expanduser(file_stored_dir))
                
                if filename:
                    img_path = os.path.join(file_abs_dir, filename)
                    if not os.path.exists(img_path):
                        img_path = os.path.join(abs_dir, filename)
                    
                    if os.path.exists(img_path) and os.path.isfile(img_path):
                        meta = record.get("meta", {})
                        exif = record.get("exif", {})
                        
                        mtime = os.path.getmtime(img_path)
                        ts = meta.get("iso_timestamp") or datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                        
                        exp = meta.get("exposure_actual_sec") or exif.get("shutter_sec")
                        iso = exif.get("iso")
                        frame_type = meta.get("frame_type") or record_root.get("context", {}).get("frame_type") or "test"
                        target = record_root.get("objective") or "Target"
                        w = file_info.get("width")
                        h = file_info.get("height")
                        size_mb = file_info.get("size_mb") or round(os.path.getsize(img_path) / (1024 * 1024), 2)
                        
                        return {
                            "status": "success",
                            "has_image": True,
                            "filename": filename,
                            "path": img_path,
                            "url": f"/api/logs/image?path={quote(img_path)}",
                            "thumb_url": f"/api/logs/image?path={quote(img_path)}&thumb=1&max_size=600",
                            "timestamp": ts,
                            "exposure": exp,
                            "iso": iso,
                            "target": target,
                            "frame_type": frame_type,
                            "width": w,
                            "height": h,
                            "size_mb": size_mb,
                            "mtime": mtime
                        }
        except Exception:
            pass

    # 2. フォールバック: ディレクトリ内の最新画像ファイルを走査
    SUPPORTED_EXTS = {".jpg", ".jpeg", ".dng", ".png", ".fits", ".fit"}
    latest_file = None
    latest_mtime = -1
    
    try:
        for entry in os.scandir(abs_dir):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in SUPPORTED_EXTS:
                    mtime = entry.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        latest_file = entry
    except Exception as e:
        return {"status": "error", "has_image": False, "message": str(e)}

    if latest_file:
        img_path = latest_file.path
        size_mb = round(latest_file.stat().st_size / (1024 * 1024), 2)
        ts = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "status": "success",
            "has_image": True,
            "filename": latest_file.name,
            "path": img_path,
            "url": f"/api/logs/image?path={quote(img_path)}",
            "thumb_url": f"/api/logs/image?path={quote(img_path)}&thumb=1&max_size=600",
            "timestamp": ts,
            "exposure": None,
            "iso": None,
            "target": None,
            "frame_type": "image",
            "width": None,
            "height": None,
            "size_mb": size_mb,
            "mtime": latest_mtime
        }

    return {"status": "success", "has_image": False, "message": "No images found"}

