import asyncio
import os
import signal
import sys
import json
import io
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import rawpy

app = FastAPI(title="OrionFieldStack Web GUI")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global reference to the running process
running_process = None
process_lock = asyncio.Lock()

# SSE process
sse_process = None
sse_process_lock = asyncio.Lock()

# Starflux process
starflux_process = None
starflux_process_lock = asyncio.Lock()

# Starforge process
starforge_process = None
starforge_process_lock = asyncio.Lock()

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHUTTERPRO_PATH = os.path.join(BASE_DIR, "shutterpro03", "shutterpro03.py")
SSE_PATH = os.path.join(BASE_DIR, "SSE", "SSE.py")
STARFLUX_PATH = os.path.join(BASE_DIR, "starflux", "starflux.py")
STARFORGE_PATH = os.path.join(BASE_DIR, "starforge", "starforge.py")
GUI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ofs_gui_sp03_config.json")

def get_sse_python():
    # Use the GUI's own python environment which is verified to have all dependencies
    return sys.executable


def get_starflux_python():
    # Use the starflux virtual environment if available to run starflux
    venv_python = os.path.join(BASE_DIR, "starflux", "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def get_starforge_python():
    # Use the starforge virtual environment if available to run starforge
    venv_python = os.path.join(BASE_DIR, "starforge", "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable



@app.post("/api/shutter/start")
async def start_shutter(request: Request):
    global running_process
    async with process_lock:
        if running_process and running_process.returncode is None:
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
            
            running_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "shutterpro03"),
                env=env
            )
            return {"status": "started", "pid": running_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/shutter/logs")
async def stream_logs():
    async def log_generator():
        global running_process
        if not running_process:
            yield "data: No process running\n\n"
            return

        try:
            while True:
                line = await running_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.post("/api/shutter/stop")
async def stop_shutter():
    global running_process
    async with process_lock:
        if running_process and running_process.returncode is None:
            running_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@app.get("/api/status")
async def get_status():
    global running_process
    if running_process and running_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

# --- SSE APIs ---

@app.post("/api/sse/start")
async def start_sse(request: Request):
    global sse_process
    async with sse_process_lock:
        if sse_process and sse_process.returncode is None:
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
            
            sse_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "SSE"),
                env=env
            )
            return {"status": "started", "pid": sse_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sse/logs")
async def stream_sse_logs():
    async def log_generator():
        global sse_process
        if not sse_process:
            yield "data: No SSE process running\n\n"
            return

        try:
            while True:
                line = await sse_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.post("/api/sse/stop")
async def stop_sse():
    global sse_process
    async with sse_process_lock:
        if sse_process and sse_process.returncode is None:
            sse_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@app.get("/api/sse/status")
async def get_sse_status():
    global sse_process
    if sse_process and sse_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

# --- Starflux APIs ---

@app.post("/api/starflux/start")
async def start_starflux(request: Request):
    global starflux_process
    async with starflux_process_lock:
        if starflux_process and starflux_process.returncode is None:
            raise HTTPException(status_code=400, detail="Starflux process is already running.")

        form_data = await request.form()
        target_path = form_data.get("target_path")
        target_type = form_data.get("target_type", "folder")  # "folder", "session", "file"
        session_id = form_data.get("session_id")
        file_name = form_data.get("file_name")
        force = form_data.get("force") == "true"
        plot = form_data.get("plot") == "true"
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
        if snr:
            cmd.extend(["--snr", snr])
        if top_stars:
            cmd.extend(["--top-stars", top_stars])
        if target_type == "session" and session_id:
            cmd.extend(["--session", session_id])

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            starflux_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "starflux"),
                env=env
            )
            return {"status": "started", "pid": starflux_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/starflux/logs")
async def stream_starflux_logs():
    async def log_generator():
        global starflux_process
        if not starflux_process:
            yield "data: No Starflux process running\n\n"
            return

        try:
            while True:
                line = await starflux_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.post("/api/starflux/stop")
async def stop_starflux():
    global starflux_process
    async with starflux_process_lock:
        if starflux_process and starflux_process.returncode is None:
            starflux_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@app.get("/api/starflux/status")
async def get_starflux_status():
    global starflux_process
    if starflux_process and starflux_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

# --- Config Persistence APIs ---

@app.get("/api/config/load")
async def load_config():
    if os.path.exists(GUI_CONFIG_PATH):
        try:
            with open(GUI_CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Load error: {e}")
    return {}

@app.post("/api/config/save")
async def save_config(request: Request):
    try:
        config_data = await request.json()
        with open(GUI_CONFIG_PATH, "w") as f:
            json.dump(config_data, f, indent=4)
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save error: {e}")

# --- Utility APIs ---

@app.get("/api/utils/list_dirs")
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

# --- Log Data Browsing APIs ---

@app.get("/api/logs/browse")
async def browse_logs(path: str):
    full_path = os.path.abspath(os.path.expanduser(path))
    log_file = os.path.join(full_path, "shutter_log.json")
    
    if not os.path.exists(log_file):
        raise HTTPException(status_code=404, detail=f"shutter_log.json not found in {path}")
    
    try:
        with open(log_file, "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading log: {str(e)}")

@app.get("/api/logs/image")
async def get_image(path: str):
    full_path = os.path.abspath(os.path.expanduser(path))
    
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    ext = os.path.splitext(full_path)[1].lower()
    
    if ext == ".dng":
        try:
            with rawpy.imread(full_path) as raw:
                try:
                    thumb = raw.extract_thumb()
                except (rawpy.LibRawNoThumbnailError, AttributeError):
                    thumb = None

                if thumb:
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        return StreamingResponse(io.BytesIO(thumb.data), media_type="image/jpeg")
                    else:
                        img = Image.fromarray(thumb.data)
                else:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False)
                    img = Image.fromarray(rgb)
                
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                buf.seek(0)
                return StreamingResponse(buf, media_type="image/jpeg")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DNG conversion error: {str(e)}")

    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}")

    return FileResponse(full_path)

# --- Starforge APIs ---

@app.post("/api/starforge/start")
async def start_starforge(request: Request):
    global starforge_process
    async with starforge_process_lock:
        if starforge_process and starforge_process.returncode is None:
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
            
            starforge_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "starforge"),
                env=env
            )
            return {"status": "started", "pid": starforge_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/starforge/logs")
async def stream_starforge_logs():
    async def log_generator():
        global starforge_process
        if not starforge_process:
            yield "data: No Starforge process running\n\n"
            return

        try:
            while True:
                line = await starforge_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.post("/api/starforge/stop")
async def stop_starforge():
    global starforge_process
    async with starforge_process_lock:
        if starforge_process and starforge_process.returncode is None:
            starforge_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}

@app.get("/api/starforge/status")
async def get_starforge_status():
    global starforge_process
    if starforge_process and starforge_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}

@app.get("/api/fits/preview")
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

# Serve static files
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Use string reference to allow hot-reload during development
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
