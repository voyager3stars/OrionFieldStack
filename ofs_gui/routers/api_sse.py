import os
import asyncio
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from core.config import SSE_PATH, BASE_DIR, get_sse_python
import core.state as state

router = APIRouter()

@router.post("/api/sse/start")
async def start_sse(request: Request):
    async with state.sse_process_lock:
        if state.sse_process and state.sse_process.returncode is None:
            raise HTTPException(status_code=400, detail="SSE process is already running.")

        form_data = await request.form()
        target_path = form_data.get("target_path")
        target_type = form_data.get("target_type", "folder")  # "folder", "session", "file"
        session_id = form_data.get("session_id")
        file_name = form_data.get("file_name")
        allsky = form_data.get("allsky") == "true"
        force = form_data.get("force") == "true"

        if not target_path:
            raise HTTPException(status_code=400, detail="Target path is required.")

        abs_target_path = os.path.abspath(os.path.expanduser(target_path))

        # Build SSE command line
        cmd = [get_sse_python(), "-u", SSE_PATH, "select"]

        if target_type == "file" and file_name:
            cmd.append(os.path.join(abs_target_path, file_name))
        else:
            cmd.append(abs_target_path)

        if allsky:
            cmd.append("--allsky")
        if force:
            cmd.append("--force")
        if target_type == "session" and session_id:
            cmd.extend(["--session", session_id])

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            state.sse_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "SSE"),
                env=env
            )
            return {"status": "started", "pid": state.sse_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/sse/logs")
async def stream_sse_logs():
    async def log_generator():
        if not state.sse_process:
            yield "data: No SSE process running\n\n"
            return

        try:
            while True:
                line = await state.sse_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.post("/api/sse/stop")
async def stop_sse():
    async with state.sse_process_lock:
        if state.sse_process and state.sse_process.returncode is None:
            state.sse_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@router.get("/api/sse/status")
async def get_sse_status():
    if state.sse_process and state.sse_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}
