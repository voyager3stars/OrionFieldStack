import os
import sys
import io
import asyncio
import json
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from core.config import STARFORGE_PATH, BASE_DIR, get_starforge_python
import core.state as state

router = APIRouter()

# --- Starforge APIs ---

@router.post("/api/starforge/start")
async def start_starforge(request: Request):
    async with state.starforge_process_lock:
        if state.starforge_process and state.starforge_process.returncode is None:
            raise HTTPException(status_code=400, detail="Starforge process is already running.")

        form_data = await request.form()
        inputs = form_data.get("inputs")  # Comma-separated paths
        threshold = form_data.get("threshold")
        sessions = form_data.get("session")  # Comma-separated or empty
        objectives = form_data.get("obj")  # Comma-separated or empty
        mode = form_data.get("mode", "mono")
        method = form_data.get("method", "sigma_clip")
        out = form_data.get("out", "AUTO")
        out_dir = form_data.get("out_dir", ".")
        limit = form_data.get("limit")
        use_flat = form_data.get("use_flat") == "true"
        no_flat = form_data.get("use_flat") == "false"
        flat_dir = form_data.get("flat_dir")
        flat_session = form_data.get("flat_session")
        flat_mult_mode = form_data.get("flat_mult_mode")
        flat_mult_value = form_data.get("flat_mult_value")
        use_dark = form_data.get("use_dark") == "true"
        no_dark = form_data.get("use_dark") == "false"
        dark_dir = form_data.get("dark_dir")
        dark_session = form_data.get("dark_session")

        if not inputs:
            raise HTTPException(status_code=400, detail="Inputs (files/folders) are required.")

        # Build command line
        cmd = [get_starforge_python(), "-u", STARFORGE_PATH]

        # Add positional arguments (inputs)
        for input_item in inputs.split(','):
            item_stripped = input_item.strip()
            if item_stripped:
                cmd.append(os.path.abspath(os.path.expanduser(item_stripped)))

        # Add keyword options
        if threshold:
            cmd.extend(["--threshold", threshold])
        if mode:
            cmd.extend(["--mode", mode])
        if method:
            cmd.extend(["--method", method])
        if out:
            cmd.extend(["--out", out])
        if out_dir:
            cmd.extend(["--out_dir", os.path.abspath(os.path.expanduser(out_dir))])
        if limit:
            cmd.extend(["--limit", limit])
        if flat_dir:
            cmd.extend(["--flat_dir", os.path.abspath(os.path.expanduser(flat_dir))])
        if flat_session:
            cmd.extend(["--flat_session", flat_session])
        if flat_mult_mode:
            cmd.extend(["--flat-mult-mode", flat_mult_mode])
        if flat_mult_value:
            cmd.extend(["--flat-mult-value", flat_mult_value])
        if dark_dir:
            cmd.extend(["--dark_dir", os.path.abspath(os.path.expanduser(dark_dir))])
        if dark_session:
            cmd.extend(["--dark_session", dark_session])

        # Flag properties
        if use_flat:
            cmd.append("--flat")
        elif no_flat:
            cmd.append("--no-flat")

        if use_dark:
            cmd.append("--dark")
        elif no_dark:
            cmd.append("--no-dark")

        # Multi-valued filters
        if sessions:
            cmd.append("--session")
            cmd.extend([s.strip() for s in sessions.split(',') if s.strip()])
        if objectives:
            cmd.append("--obj")
            cmd.extend([o.strip() for o in objectives.split(',') if o.strip()])

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            state.starforge_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "starforge"),
                env=env
            )
            return {"status": "started", "pid": state.starforge_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/starforge/logs")
async def stream_starforge_logs():
    async def log_generator():
        if not state.starforge_process:
            yield "data: No Starforge process running\n\n"
            return

        try:
            while True:
                line = await state.starforge_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.post("/api/starforge/stop")
async def stop_starforge():
    async with state.starforge_process_lock:
        if state.starforge_process and state.starforge_process.returncode is None:
            state.starforge_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@router.get("/api/starforge/status")
async def get_starforge_status():
    if state.starforge_process and state.starforge_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

@router.get("/api/fits/preview")
async def fits_preview(path: str):
    full_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="FITS file not found")
        
    fits_code = """
import sys
import io
import numpy as np
from astropy.io import fits
from PIL import Image

fits_path = sys.argv[1]
try:
    with fits.open(fits_path) as hdul:
        data = hdul[0].data
        if data is None and len(hdul) > 1:
            data = hdul[1].data
        if data is None:
            sys.exit(1)
        
        data = data.astype(np.float32)
        
        if data.ndim == 3:
            if data.shape[0] == 3:
                data = np.transpose(data, (1, 2, 0))
                
        vmin, vmax = np.percentile(data, [0.5, 99.5])
        if vmax > vmin:
            data = np.clip(data, vmin, vmax)
            data = (data - vmin) / (vmax - vmin)
        else:
            data = data - np.min(data)
            mx = np.max(data)
            if mx > 0:
                data = data / mx
                
        data = (data * 255).astype(np.uint8)
        img = Image.fromarray(data)
        img.save(sys.stdout.buffer, format="JPEG", quality=80)
except Exception as e:
    sys.exit(2)
"""
    try:
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", fits_code, full_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FITS conversion failed: {stderr.decode(errors='replace')}")
            
        return StreamingResponse(io.BytesIO(stdout), media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running conversion: {str(e)}")


@router.get("/api/starforge/stacked_fits")
async def get_stacked_fits(dir: str, type: str):
    abs_dir = os.path.abspath(os.path.expanduser(dir))
    if not os.path.exists(abs_dir):
        return []
        
    fits = []
    prefix = f"master_{type}_"
    try:
        for f in os.listdir(abs_dir):
            if f.startswith(prefix) and f.lower().endswith(('.fits', '.fit')):
                fits.append(f)
    except Exception:
        pass
    return list(set(fits))


