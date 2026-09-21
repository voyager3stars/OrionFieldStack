import os
import asyncio
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from core.config import STARFLUX_PATH, BASE_DIR, get_starflux_python
import core.state as state

router = APIRouter()

@router.post("/api/starflux/start")
async def start_starflux(request: Request):
    async with state.starflux_process_lock:
        if state.starflux_process and state.starflux_process.returncode is None:
            raise HTTPException(status_code=400, detail="Starflux process is already running.")

        form_data = await request.form()
        target_path = form_data.get("target_path")
        target_type = form_data.get("target_type", "folder")  # "folder", "session", "file"
        session_id = form_data.get("session_id")
        file_name = form_data.get("file_name")
        force = form_data.get("force") == "true"
        plot = form_data.get("plot") == "true"
        save_bg = form_data.get("save_bg") == "true"
        bg_format = form_data.get("bg_format")
        outpath = form_data.get("outpath")
        snr = form_data.get("snr")
        top_stars = form_data.get("top_stars")

        if not target_path:
            raise HTTPException(status_code=400, detail="Target path is required.")

        abs_target_path = os.path.abspath(os.path.expanduser(target_path))

        # Build Starflux command line
        cmd = [get_starflux_python(), "-u", STARFLUX_PATH]

        if target_type == "file" and file_name:
            cmd.append(os.path.join(abs_target_path, file_name))
        else:
            cmd.append(abs_target_path)

        if force:
            cmd.append("--force")
        if plot:
            cmd.append("--plot")
        if save_bg:
            cmd.append("--save-bg-image")
        if bg_format:
            cmd.extend(["--bg-format", bg_format])
        if outpath:
            cmd.extend(["--outpath", outpath])
        if snr:
            cmd.extend(["--snr", snr])
        if top_stars:
            cmd.extend(["--top-stars", top_stars])
        if target_type == "session" and session_id:
            cmd.extend(["--session", session_id])

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            state.starflux_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "starflux"),
                env=env
            )
            return {"status": "started", "pid": state.starflux_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/starflux/logs")
async def stream_starflux_logs():
    async def log_generator():
        if not state.starflux_process:
            yield "data: No Starflux process running\n\n"
            return

        try:
            while True:
                line = await state.starflux_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.post("/api/starflux/stop")
async def stop_starflux():
    async with state.starflux_process_lock:
        if state.starflux_process and state.starflux_process.returncode is None:
            state.starflux_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@router.get("/api/starflux/status")
async def get_starflux_status():
    if state.starflux_process and state.starflux_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}
