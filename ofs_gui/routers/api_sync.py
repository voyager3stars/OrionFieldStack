import os
import sys
import json
import asyncio
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

# Global variables imported from app.py temporarily until Phase 3
# In FastAPI, we can access these from the main app or import them later.
# For now, we need to import them or rely on them being defined in the module.
# To make it work cleanly without circular imports, we should import the paths from app.py.

from core.config import SKYSYNC_PATH, BASE_DIR
# (We import core.state as state locally inside functions for globals to avoid circular import issues)

@router.post("/api/sync/flow/start")
async def start_sync_flow(request: Request):
    import core.state as state
    async with state.sync_process_lock:
        if state.sync_process and state.sync_process.returncode is None:
            raise HTTPException(status_code=400, detail="Sync flow is already running.")

        form_data = await request.form()
        exposure = form_data.get("exposure", "5.0")
        count = form_data.get("count", "1")
        shutter_mode = form_data.get("mode", "bulb")
        save_dir = form_data.get("save_dir", "~/Pictures/sync")
        session = form_data.get("session", "sync")
        flow_type = form_data.get("flow_type", "solve")
        
        if flow_type not in ["full", "sync", "solve", "solve_only"]:
            flow_type = "solve"

        # 指定された flow_type モードで実行
        cmd = [
            sys.executable, "-u", SKYSYNC_PATH, flow_type,
            "--exposure", exposure,
            "--count", count,
            "--shutter-mode", shutter_mode,
            "--dir", save_dir,
            "--session", session
        ]

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            state.sync_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "skysync"),
                env=env
            )
            return {"status": "started", "pid": state.sync_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/sync/flow/logs")
async def stream_sync_logs():
    async def log_generator():
        import core.state as state
        if not state.sync_process:
            yield "data: No Sync process running\n\n"
            return

        try:
            while True:
                line = await state.sync_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")


@router.post("/api/sync/flow/stop")
async def stop_sync_flow():
    import core.state as state
    async with state.sync_process_lock:
        if state.sync_process and state.sync_process.returncode is None:
            state.sync_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}


@router.get("/api/sync/flow/status")
async def get_sync_status():
    import core.state as state
    if state.sync_process and state.sync_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}


@router.get("/api/sync/flow/result")
async def get_sync_result(save_dir: str = "~/Pictures/sync"):
    abs_dir = os.path.abspath(os.path.expanduser(save_dir))
    latest_json_path = os.path.join(abs_dir, "latest_shot.json")
    
    if not os.path.exists(latest_json_path):
        raise HTTPException(status_code=404, detail=f"{latest_json_path} not found.")

    try:
        with open(latest_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            if isinstance(data, list):
                if not data:
                    raise HTTPException(status_code=404, detail="Empty data array.")
                record_root = data[0]
            elif isinstance(data, dict):
                record_root = data
            else:
                raise HTTPException(status_code=400, detail="Invalid JSON format.")
            
            analysis = record_root.get("analysis", {})
            if "SSE" in analysis:
                sse = analysis.get("SSE", {})
            else:
                if not analysis and "record" in record_root:
                    analysis = record_root.get("record", {}).get("analysis", {})
                sse = analysis
            
            if sse.get("solve_status") == "success":
                coords = sse.get("solved_coords", {})
                stats = sse.get("process_stats", {})
                conf = sse.get("confidence", 0.0)
                
                return {
                    "solve_status": "success",
                    "ra_deg": coords.get("ra_deg"),
                    "dec_deg": coords.get("dec_deg"),
                    "ra_hms": coords.get("ra_hms"),
                    "dec_dms": coords.get("dec_dms"),
                    "confidence": conf,
                    "matched_stars": stats.get("matched_stars"),
                    "process_time": sse.get("process_time_sec")
                }
            else:
                fail_reason = sse.get("fail_reason") or sse.get("solve_status") or "Unknown"
                return {
                    "solve_status": "failed",
                    "fail_reason": fail_reason
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse latest_shot.json: {str(e)}")


@router.post("/api/sync/indi")
async def sync_indi(request: Request):
    import core.state as state
    form_data = await request.form()
    ra = form_data.get("ra")
    dec = form_data.get("dec")
    if ra is None or dec is None:
        raise HTTPException(status_code=400, detail="RA and DEC are required.")
    
    cmd = [sys.executable, SKYSYNC_PATH, "manual", "--ra", str(ra), "--dec", str(dec)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.join(BASE_DIR, "skysync")
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return {"status": "success", "output": stdout.decode()}
        else:
            raise HTTPException(status_code=500, detail=stderr.decode() or "INDI setprop failed.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
