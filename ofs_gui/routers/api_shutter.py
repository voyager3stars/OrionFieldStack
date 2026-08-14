import os
import sys
import asyncio
from fastapi import APIRouter, Form, HTTPException, Request
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
