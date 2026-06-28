import asyncio
import os
import signal
import sys
import json
import io
from datetime import datetime, timezone
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

# Sync process
sync_process = None
sync_process_lock = asyncio.Lock()

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHUTTERPRO_PATH = os.path.join(BASE_DIR, "shutterpro03", "shutterpro03.py")
SSE_PATH = os.path.join(BASE_DIR, "SSE", "SSE.py")
STARFLUX_PATH = os.path.join(BASE_DIR, "starflux", "starflux.py")
STARFORGE_PATH = os.path.join(BASE_DIR, "starforge", "starforge.py")
SKYSYNC_PATH = os.path.join(BASE_DIR, "skysync", "skysync.py")
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


def get_ofs_link_python():
    # Use the ofs_link virtual environment if available to run ofs_link
    venv_python = os.path.join(BASE_DIR, "ofs_link", "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


# Global telemetry cache
latest_telemetry = {
    "indi_server": "DISCONNECTED",
    "status": "UNKNOWN",
    "ra_deg": None,
    "dec_deg": None,
    "ra_str": None,
    "dec_str": None,
    "side_of_pier": "UNKNOWN",
    "latitude": None,
    "longitude": None,
    "elevation": None,
    "timestamp_utc": None,
    "iso_timestamp": None
}

latest_flashair = {
    "flashair": "DISCONNECTED",
    "url": "http://192.168.50.200"
}


async def update_telemetry_loop():
    global latest_telemetry
    ofs_link_py = os.path.join(BASE_DIR, "ofs_link", "ofs_link.py")
    python_exe = get_ofs_link_python()
    
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                python_exe, ofs_link_py, "--get",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                try:
                    data = json.loads(stdout.decode().strip())
                    latest_telemetry = data
                except Exception as ex:
                    latest_telemetry["status"] = "PARSE_ERROR"
            else:
                latest_telemetry["indi_server"] = "DISCONNECTED"
                latest_telemetry["status"] = "ERROR"
        except Exception as e:
            latest_telemetry["indi_server"] = "DISCONNECTED"
            latest_telemetry["status"] = f"ERROR: {str(e)}"
        
        await asyncio.sleep(1.0)


async def update_flashair_loop():
    global latest_flashair
    ofs_link_py = os.path.join(BASE_DIR, "ofs_link", "ofs_link.py")
    python_exe = get_ofs_link_python()
    
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                python_exe, ofs_link_py, "--flashair",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                try:
                    data = json.loads(stdout.decode().strip())
                    latest_flashair = data
                except Exception as ex:
                    latest_flashair = {
                        "flashair": "DISCONNECTED",
                        "url": "http://192.168.50.200"
                    }
            else:
                latest_flashair = {
                    "flashair": "DISCONNECTED",
                    "url": "http://192.168.50.200"
                }
        except Exception as e:
            latest_flashair = {
                "flashair": "DISCONNECTED",
                "url": "http://192.168.50.200"
            }
        
        await asyncio.sleep(10.0)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(update_telemetry_loop())
    asyncio.create_task(update_flashair_loop())



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


@app.get("/api/telemetry")
async def get_telemetry(mock: bool = False):
    global latest_telemetry, latest_flashair
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
    res = dict(latest_telemetry)
    res["flashair"] = latest_flashair.get("flashair", "DISCONNECTED")
    res["flashair_url"] = latest_flashair.get("url", "http://192.168.50.200")
    return res

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


# --- Sync APIs ---

@app.post("/api/sync/flow/start")
async def start_sync_flow(request: Request):
    global sync_process
    async with sync_process_lock:
        if sync_process and sync_process.returncode is None:
            raise HTTPException(status_code=400, detail="Sync flow is already running.")

        form_data = await request.form()
        exposure = form_data.get("exposure", "5.0")
        count = form_data.get("count", "1")
        shutter_mode = form_data.get("mode", "bulb")
        save_dir = form_data.get("save_dir", "~/Pictures/sync")
        session = form_data.get("session", "sync")

        # solve モードで実行（自動同期なし、撮影＋ゾルブのみ）
        cmd = [
            sys.executable, "-u", SKYSYNC_PATH, "solve",
            "--exposure", exposure,
            "--count", count,
            "--shutter-mode", shutter_mode,
            "--dir", save_dir,
            "--session", session
        ]

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            sync_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.join(BASE_DIR, "skysync"),
                env=env
            )
            return {"status": "started", "pid": sync_process.pid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sync/flow/logs")
async def stream_sync_logs():
    async def log_generator():
        global sync_process
        if not sync_process:
            yield "data: No Sync process running\n\n"
            return

        try:
            while True:
                line = await sync_process.stdout.readline()
                if not line:
                    break
                yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
        except Exception as e:
            yield f"data: Log stream error: {str(e)}\n\n"
        
        yield "data: [Process Finished]\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")


@app.post("/api/sync/flow/stop")
async def stop_sync_flow():
    global sync_process
    async with sync_process_lock:
        if sync_process and sync_process.returncode is None:
            sync_process.terminate()
            return {"status": "stopping"}
        return {"status": "not running"}


@app.get("/api/sync/flow/status")
async def get_sync_status():
    global sync_process
    if sync_process and sync_process.returncode is None:
        return {"status": "running"}
    return {"status": "idle"}


@app.get("/api/sync/flow/result")
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


@app.post("/api/sync/indi")
async def sync_indi(request: Request):
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


@app.get("/api/starforge/stacked_fits")
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


@app.get("/api/starforge/flat_view")
async def starforge_flat_view(dir: str, session: str = "", file: str = "", out_dir: str = "", cx: str = "", cy: str = ""):
    abs_dir = os.path.abspath(os.path.expanduser(dir))
    log_file = os.path.join(abs_dir, "shutter_log.json")
    
    file_options = []
    file_map = {}
    
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                logs = json.load(f)
            for record in logs:
                if not session or record.get("session_id") == session:
                    fname = record.get("record", {}).get("file", {}).get("name")
                    fpath = record.get("record", {}).get("file", {}).get("path", "")
                    if fname:
                        full_p = os.path.join(fpath if fpath else abs_dir, fname)
                        if os.path.exists(full_p) and fname not in file_map:
                            file_options.append(fname)
                            file_map[fname] = full_p
        except Exception:
            pass
            
    if not file_options and os.path.isdir(abs_dir):
        for f in os.listdir(abs_dir):
            if f.lower().endswith(('.fits', '.fit', '.dng', '.raw', '.cr2', '.nef', '.jpg', '.jpeg', '.png')):
                if f not in file_map:
                    full_p = os.path.join(abs_dir, f)
                    file_options.append(f)
                    file_map[f] = full_p
                    
    stacked_files = []
    search_dirs = []
    if out_dir:
        search_dirs.append(os.path.abspath(os.path.expanduser(out_dir)))
    search_dirs.append(abs_dir)
    
    # Remove duplicates
    search_dirs = list(dict.fromkeys(search_dirs))
    
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            prefix = "master_flat_"
            try:
                for f in os.listdir(s_dir):
                    if f.startswith(prefix) and f.lower().endswith(('.fits', '.fit')):
                        if not session or f"_{session}" in f:
                            if f not in stacked_files:
                                stacked_files.append(f)
                                if f not in file_map:
                                    file_map[f] = os.path.join(s_dir, f)
            except Exception:
                pass

    if not file_options and not stacked_files:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><h3>Error: No flat images found in the specified directory/session.</h3></body></html>", status_code=404)

    if file and file in file_map:
        selected_filename = file
    elif stacked_files:
        selected_filename = stacked_files[0]
    else:
        selected_filename = file_options[0]

    target_file = file_map[selected_filename]
    
    options_html = ""
    if stacked_files:
        options_html += '<div class="list-title" style="padding: 6px 10px;">STACKED FILE</div>\n'
        for sf in stacked_files:
            sel = " selected" if sf == selected_filename else ""
            options_html += f"""<div class="list-item{sel}" onclick="changeFile('{sf}')"><div class="file-name" style="color: var(--accent-gold); font-weight: 600;">{sf}</div></div>\n"""
        options_html += '<div class="list-title" style="margin-top: 8px; border-top: 1px solid var(--glass-border); padding: 6px 10px;">FILES</div>\n'
    else:
        options_html += '<div class="list-title" style="padding: 6px 10px;">FILES</div>\n'

    for opt in file_options:
        sel = " selected" if opt == selected_filename else ""
        options_html += f"""<div class="list-item{sel}" onclick="changeFile('{opt}')"><div class="file-name">{opt}</div></div>\n"""

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
cx = int(cx_str) if cx_str.lstrip("-").isdigit() else -1
cy = int(cy_str) if cy_str.lstrip("-").isdigit() else -1
data = None

try:
    ext = file_path.lower().split('.')[-1]
    if ext in ['fits', 'fit']:
        if has_astropy:
            with fits.open(file_path) as hdul:
                for hdu in hdul:
                    if hdu.data is not None:
                        d = hdu.data
                        if d.ndim == 3:
                            data = np.mean(d, axis=0)
                        else:
                            data = d
                        break
    elif ext in ['dng', 'cr2', 'nef', 'arw', 'raw']:
        if has_rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=16)
                data = np.mean(rgb, axis=2)
    else:
        img = Image.open(file_path).convert('L')
        data = np.array(img)

    if data is None:
        print("<html><body><h3>Error: Unsupported file format or missing libraries.</h3></body></html>")
        sys.exit(0)

    h, w = data.shape
    scale_2d = max(1, round(w / 640))
    scale_3d = max(1, round(w / 150))
    
    data_small_2d = data[::scale_2d, ::scale_2d]
    data_small_3d = data[::scale_3d, ::scale_3d]

    z_data = data_small_2d.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    z_data_3d = data_small_3d.astype(float)
    z_data_3d = np.nan_to_num(z_data_3d, nan=0.0, posinf=0.0, neginf=0.0)
    
    z_max = float(np.max(z_data))
    if z_max <= 0:
        z_max = 255.0

    # Calculate center slices for 2D plots
    ch, cw = z_data.shape
    mid_y, mid_x = ch // 2, cw // 2
    x_slice = z_data[mid_y, :].tolist()
    y_slice = z_data[:, mid_x].tolist()

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Flat Image 3D View</title>
        <link rel="stylesheet" href="/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <style>
            .flat-layout-3col {
                display: grid;
                grid-template-columns: 20% 50% 1fr;
                gap: 1rem;
                height: calc(100vh - 120px);
            }
            .col-files { background: var(--bg-sidebar); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-center { position: relative; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-right { display: flex; flex-direction: column; gap: 1rem; height: calc(100vh - 120px); }
            .side-plot { flex: 1; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; overflow: hidden; position: relative; }
            #plot { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
            /* Adjust list-item height and font based on previous request while keeping LOGDATA design */
            .list-item { padding: 8px 8px !important; }
            .file-name { font-size: 0.68rem !important; }
        </style>
        <script>
            function changeFile(filename) {
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('file', filename);
                window.location.search = urlParams.toString();
            }
        </script>
    </head>
    <body>
        <div class="container" style="max-width: 100%;">
            <header>
                <div class="header-main">
                    <h1>OrionFieldStack <span class="v-tag">Flat Viewer</span></h1>
                </div>
            </header>
            
            <main>
                <div class="flat-layout-3col">
                    <aside class="col-files">
                        <div class="list-container" style="padding: 0; display: flex; flex-direction: column;">
                            __OPTIONS__
                        </div>
                    </aside>
                    <div class="col-center">
                        <div style="position: absolute; top: 10px; right: 10px; z-index: 10; display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.6); padding: 8px 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                            <span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: bold; margin-right: 4px;">Z-AXIS</span>
                            <label style="font-size: 0.75rem; color: var(--text-dim);">Min:</label>
                            <input type="number" id="z-min" value="0" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                            <label style="font-size: 0.75rem; color: var(--text-dim); margin-left: 4px;">Max:</label>
                            <input type="number" id="z-max" value="__ZMAX__" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                        </div>
                        <div id="plot"></div>
                    </div>
                    <div class="col-right">
                        <div id="plot-xz" class="side-plot"></div>
                        <div id="plot-yz" class="side-plot"></div>
                    </div>
                </div>
            </main>
        </div>
        <script>
            var z_data = __ZDATA3D__;
            var x_slice = __XSLICE__;
            var y_slice = __YSLICE__;
 
            // 3D Plot
            var data3d = [{
                z: z_data,
                type: 'surface',
                colorscale: 'Viridis',
                cmin: 0,
                cmax: __ZMAX__,
                showscale: false
            }];
            var aspect_x = z_data[0].length / Math.max(z_data.length, z_data[0].length);
            var aspect_y = z_data.length / Math.max(z_data.length, z_data[0].length);

            var layout3d = {
                autosize: true,
                scene: {
                    xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                    yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                    zaxis: { title: 'Luminance', range: [0, __ZMAX__], autorange: false },
                    aspectmode: 'manual',
                    aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                    camera: {
                        eye: {x: -1.5, y: -1.5, z: 1.2}
                    }
                },
                margin: { l: 0, r: 0, b: 0, t: 0 },
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212'
            };
            Plotly.newPlot('plot', data3d, layout3d, {responsive: true});

            // X-Z Section
            var dataXZ = [
                { y: x_slice, type: 'scatter', mode: 'lines', name: 'Center', line: {color: '#00ff88', dash: 'dash'} },
                { y: x_slice, type: 'scatter', mode: 'lines', name: 'Selected', line: {color: '#ffffff'} }
            ];
            var layoutXZ = {
                title: 'X-Z Section (Center & Selected)',
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff'},
                margin: {t: 40, b: 40, l: 40, r: 20},
                xaxis: { title: 'X', showgrid: true, gridcolor: '#333' },
                yaxis: { title: 'Luminance', showgrid: true, gridcolor: '#333', range: [0, __ZMAX__] },
                showlegend: true,
                legend: { x: 1, xanchor: 'right', y: 1, bgcolor: 'rgba(0,0,0,0)' }
            };
            Plotly.newPlot('plot-xz', dataXZ, layoutXZ, {responsive: true});

            // Y-Z Section
            var dataYZ = [
                { y: y_slice, type: 'scatter', mode: 'lines', name: 'Center', line: {color: '#ff0088', dash: 'dash'} },
                { y: y_slice, type: 'scatter', mode: 'lines', name: 'Selected', line: {color: '#ffffff'} }
            ];
            var layoutYZ = {
                title: 'Y-Z Section (Center & Selected)',
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff'},
                margin: {t: 40, b: 40, l: 40, r: 20},
                xaxis: { title: 'Y', showgrid: true, gridcolor: '#333' },
                yaxis: { title: 'Luminance', showgrid: true, gridcolor: '#333', range: [0, __ZMAX__] },
                showlegend: true,
                legend: { x: 1, xanchor: 'right', y: 1, bgcolor: 'rgba(0,0,0,0)' }
            };
            Plotly.newPlot('plot-yz', dataYZ, layoutYZ, {responsive: true});

            // Add click event for 3D plot to update selected cross-sections
            var plotDiv = document.getElementById('plot');
            plotDiv.on('plotly_click', function(data) {
                if (data.points && data.points.length > 0) {
                    var pt = data.points[0];
                    var x_idx = Math.round(pt.x);
                    var y_idx = Math.round(pt.y);
                    
                    if (y_idx >= 0 && y_idx < __ZDATA_FULL_LENGTH__ && x_idx >= 0 && x_idx < __ZDATA_FULL_WIDTH__) {
                        // For 3D click, we'd need to map 3D indices to 2D indices, but for now we skip or approximate.
                        // Actually, we use the original z_data array in JS for full resolution slices.
                        // Since z_data is now ZDATA3D, cross-section clicks won't map exactly.
                        // We will pass the full z_data as z_data_full just for the click event.
                        var new_x_slice = z_data_full[Math.round(y_idx * (__ZDATA_FULL_LENGTH__ / z_data.length))];
                        var new_y_slice = z_data_full.map(function(row) { return row[Math.round(x_idx * (__ZDATA_FULL_WIDTH__ / z_data[0].length))]; });
                        
                        Plotly.update('plot-xz', { y: [new_x_slice] }, { title: 'X-Z Section (Selected)' }, [1]);
                        Plotly.update('plot-yz', { y: [new_y_slice] }, { title: 'Y-Z Section (Selected)' }, [1]);
                    }
                }
            });
            var z_data_full = __ZDATA__;

            function updateZRange() {
                var zmin = parseFloat(document.getElementById('z-min').value);
                var zmax = parseFloat(document.getElementById('z-max').value);
                if (isNaN(zmin)) zmin = 0;
                if (isNaN(zmax)) zmax = __ZMAX__;
                
                Plotly.relayout('plot', {
                    'scene.zaxis.range': [zmin, zmax],
                    'scene.zaxis.autorange': false
                });
                Plotly.restyle('plot', {
                    cmin: [zmin],
                    cmax: [zmax]
                });
                Plotly.relayout('plot-xz', {
                    'yaxis.range': [zmin, zmax],
                    'yaxis.autorange': false
                });
                Plotly.relayout('plot-yz', {
                    'yaxis.range': [zmin, zmax],
                    'yaxis.autorange': false
                });
            }
            // Force apply range once to ensure 3D scene correctly clips
            updateZRange();
        </script>
    </body>
    </html>
    '''
    html = html_template.replace('__FILENAME__', file_path)\
        .replace('__ZDATA3D__', json.dumps(z_data_3d.tolist()))\
        .replace('__ZDATA__', json.dumps(z_data.tolist()))\
        .replace('__XSLICE__', json.dumps(x_slice))\
        .replace('__YSLICE__', json.dumps(y_slice))\
        .replace('__ZMAX__', str(z_max))\
        .replace('__ZDATA_FULL_LENGTH__', str(len(z_data)))\
        .replace('__ZDATA_FULL_WIDTH__', str(len(z_data[0]) if len(z_data) > 0 else 0))
    print(html)
except Exception as e:
    print(f"<html><body><h3>Error processing image: {str(e)}</h3></body></html>")
"""
    try:
        from fastapi.responses import HTMLResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file,
            cx, cy,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return HTMLResponse(f"<html><body><h3>Error: Script execution failed.</h3><pre>{stderr.decode(errors='replace')}</pre></body></html>", status_code=500)
            
        final_html = stdout.decode(errors='replace').replace('__OPTIONS__', options_html)
        return HTMLResponse(final_html)
    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<html><body><h3>Error: {str(e)}</h3></body></html>", status_code=500)



def get_dark_target_file(dir: str, session: str, file: str, out_dir: str):
    abs_dir = os.path.abspath(os.path.expanduser(dir))
    log_file = os.path.join(abs_dir, "shutter_log.json")
    
    file_options = []
    file_map = {}
    
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                logs = json.load(f)
            for record in logs:
                if not session or record.get("session_id") == session:
                    fname = record.get("record", {}).get("file", {}).get("name")
                    fpath = record.get("record", {}).get("file", {}).get("path", "")
                    if fname:
                        full_p = os.path.join(fpath if fpath else abs_dir, fname)
                        if os.path.exists(full_p) and fname not in file_map:
                            file_options.append(fname)
                            file_map[fname] = full_p
        except Exception:
            pass
            
    if not file_options and os.path.isdir(abs_dir):
        for f in os.listdir(abs_dir):
            if f.lower().endswith(('.fits', '.fit', '.dng', '.raw', '.cr2', '.nef', '.jpg', '.jpeg', '.png')):
                if f not in file_map:
                    full_p = os.path.join(abs_dir, f)
                    file_options.append(f)
                    file_map[f] = full_p
                    
    stacked_files = []
    search_dirs = []
    if out_dir:
        search_dirs.append(os.path.abspath(os.path.expanduser(out_dir)))
    search_dirs.append(abs_dir)
    
    # Remove duplicates
    search_dirs = list(dict.fromkeys(search_dirs))
    
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            prefix = "master_dark_"
            try:
                for f in os.listdir(s_dir):
                    if f.startswith(prefix) and f.lower().endswith(('.fits', '.fit')):
                        if not session or f"_{session}" in f:
                            if f not in stacked_files:
                                stacked_files.append(f)
                                if f not in file_map:
                                    file_map[f] = os.path.join(s_dir, f)
            except Exception:
                pass

    if file and file in file_map:
        selected_filename = file
    elif stacked_files:
        selected_filename = stacked_files[0]
    elif file_options:
        selected_filename = file_options[0]
    else:
        return None, None, None, None, None

    target_file = file_map[selected_filename]
    return target_file, selected_filename, file_options, stacked_files, abs_dir


@app.get("/api/starforge/dark_crop_3d")
async def starforge_dark_crop_3d(dir: str, session: str = "", file: str = "", out_dir: str = "", cx: str = "", cy: str = "", grid_row: str = "", grid_col: str = "", k_val: str = "1000"):
    target_file, _, _, _, _ = get_dark_target_file(dir, session, file, out_dir)
    if not target_file:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "No dark images found"}, status_code=404)

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
grid_row_str = sys.argv[4] if len(sys.argv) > 4 else "-1"
grid_col_str = sys.argv[5] if len(sys.argv) > 5 else "-1"
k_val_str = sys.argv[6] if len(sys.argv) > 6 else "1000"

cx = int(float(cx_str)) if cx_str.strip() and cx_str.replace('.','',1).lstrip("-").isdigit() else -1
cy = int(float(cy_str)) if cy_str.strip() and cy_str.replace('.','',1).lstrip("-").isdigit() else -1
grid_row = int(grid_row_str) if grid_row_str.lstrip("-").isdigit() else -1
grid_col = int(grid_col_str) if grid_col_str.lstrip("-").isdigit() else -1
k_val = float(k_val_str) if k_val_str.replace('.', '', 1).isdigit() else 1000.0

try:
    ext = file_path.lower().split('.')[-1]
    data = None
    if ext in ['fits', 'fit']:
        if has_astropy:
            with fits.open(file_path) as hdul:
                for hdu in hdul:
                    if hdu.data is not None:
                        d = hdu.data
                        if d.ndim == 3 and d.shape[0] in [3, 4]:
                            data = np.mean(d, axis=0)
                        elif d.ndim == 3 and d.shape[2] in [3, 4]:
                            data = np.mean(d, axis=2)
                        else:
                            data = d
                        break
    elif ext in ['dng', 'raw', 'cr2', 'nef']:
        if has_rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=False, no_auto_bright=True, output_bps=16)
                data = np.mean(rgb, axis=2)
    else:
        img = Image.open(file_path).convert('L')
        data = np.array(img)

    if data is None:
        print(json.dumps({"error": "Unsupported file format"}))
        sys.exit(0)

    h, w = data.shape
    
    if grid_row >= 0 and grid_col >= 0:
        grid_h, grid_w = h / 16.0, w / 16.0
        start_y = int(grid_row * grid_h)
        end_y = int((grid_row+1)*grid_h) if grid_row < 15 else h
        start_x = int(grid_col * grid_w)
        end_x = int((grid_col+1)*grid_w) if grid_col < 15 else w
        crop_h = end_y - start_y
        crop_w = end_x - start_x
    else:
        crop_h = min(300, h)
        crop_w = min(300, w)
        if cx >= 0 and cy >= 0:
            start_x = max(0, min(cx - crop_w // 2, w - crop_w))
            start_y = max(0, min(cy - crop_h // 2, h - crop_h))
        else:
            start_x = (w - crop_w) // 2
            start_y = (h - crop_h) // 2
            
    data_crop = data[start_y:start_y+crop_h, start_x:start_x+crop_w]
    z_data = data_crop.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    crop_med = float(np.median(z_data)) if z_data.size > 0 else 0
    crop_mad = float(np.median(np.abs(z_data - crop_med))) if z_data.size > 0 else 0
    z_max = (crop_med + k_val * crop_mad) * 2.0 if z_data.size > 0 else 255.0
    
    print(json.dumps({"z_data": z_data.tolist(), "z_max": z_max}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
"""
    try:
        from fastapi.responses import JSONResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file,
            cx, cy, grid_row, grid_col, k_val,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return JSONResponse({"error": "Script execution failed", "stderr": stderr.decode(errors='replace')}, status_code=500)
            
        return JSONResponse(json.loads(stdout.decode(errors='replace')))
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=500)



@app.get("/api/starforge/dark_view")
async def starforge_dark_view(dir: str, session: str = "", file: str = "", out_dir: str = "", cx: str = "", cy: str = "", grid_row: str = "", grid_col: str = "", k_val: str = "1000", plot3d: str = "0", use_global_mad: str = "1"):
    # If no custom crop is specified and no grid is specified, default to Grid 0,0
    if not cx and not cy and not grid_row and not grid_col:
        grid_row = "0"
        grid_col = "0"
    if not grid_row:
        grid_row = "-1"
    if not grid_col:
        grid_col = "-1"

    target_file, selected_filename, file_options, stacked_files, abs_dir = get_dark_target_file(dir, session, file, out_dir)
    
    if not target_file:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><h3>Error: No dark images found in the specified directory/session.</h3></body></html>", status_code=404)

    options_html = ""
    if stacked_files:
        options_html += '<h3 style="padding: 6px 10px; margin: 0;">STACKED FILE</h3>\n'
        for sf in stacked_files:
            sel = " selected" if sf == selected_filename else ""
            options_html += f'''<div class="list-item{sel}" onclick="changeFile('{sf}')"><div class="file-name" style="color: var(--accent-gold); font-weight: 600;">{sf}</div></div>\n'''
        options_html += '<h3 style="margin-top: 8px; border-top: 1px solid var(--glass-border); padding: 12px 10px 0 10px;">FILES</h3>\n'
    else:
        options_html += '<h3 style="padding: 6px 10px; margin: 0;">FILES</h3>\n'

    for opt in file_options:
        sel = " selected" if opt == selected_filename else ""
        options_html += f'''<div class="list-item{sel}" onclick="changeFile('{opt}')"><div class="file-name">{opt}</div></div>\n'''

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

try:
    from scipy.ndimage import label
    has_scipy = True
except ImportError:
    has_scipy = False

file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
grid_row_str = sys.argv[4] if len(sys.argv) > 4 else "-1"
grid_col_str = sys.argv[5] if len(sys.argv) > 5 else "-1"
k_val_str = sys.argv[6] if len(sys.argv) > 6 else "1000"
plot3d_str = sys.argv[7] if len(sys.argv) > 7 else "0"
use_global_mad_str = sys.argv[8] if len(sys.argv) > 8 else "1"

cx = int(float(cx_str)) if cx_str.strip() and cx_str.replace('.','',1).lstrip("-").isdigit() else -1
cy = int(float(cy_str)) if cy_str.strip() and cy_str.replace('.','',1).lstrip("-").isdigit() else -1
grid_row = int(grid_row_str) if grid_row_str.lstrip("-").isdigit() else -1
grid_col = int(grid_col_str) if grid_col_str.lstrip("-").isdigit() else -1
k_val = float(k_val_str) if k_val_str.replace('.', '', 1).isdigit() else 1000.0
plot3d = int(plot3d_str) if plot3d_str.isdigit() else 0
use_global_mad = int(use_global_mad_str) if use_global_mad_str.isdigit() else 1
data = None

try:
    ext = file_path.lower().split('.')[-1]
    if ext in ['fits', 'fit']:
        if has_astropy:
            with fits.open(file_path) as hdul:
                for hdu in hdul:
                    if hdu.data is not None:
                        d = hdu.data
                        if d.ndim == 3:
                            data = np.mean(d, axis=0)
                        else:
                            data = d
                        break
    elif ext in ['dng', 'cr2', 'nef', 'arw', 'raw']:
        if has_rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=False, no_auto_bright=True, output_bps=16)
                data = np.mean(rgb, axis=2)
    else:
        img = Image.open(file_path).convert('L')
        data = np.array(img)

    if data is None:
        print("<html><body><h3>Error: Unsupported file format or missing libraries.</h3></body></html>")
        sys.exit(0)

    h, w = data.shape
    
    # Extract grid partition if grid coordinates provided
    if grid_row >= 0 and grid_col >= 0:
        grid_h, grid_w = h / 16.0, w / 16.0
        start_y = int(grid_row * grid_h)
        end_y = int((grid_row+1)*grid_h) if grid_row < 15 else h
        start_x = int(grid_col * grid_w)
        end_x = int((grid_col+1)*grid_w) if grid_col < 15 else w
        crop_h = end_y - start_y
        crop_w = end_x - start_x
        actual_cx = start_x + crop_w // 2
        actual_cy = start_y + crop_h // 2
    else:
        crop_h = min(300, h)
        crop_w = min(300, w)
        if cx >= 0 and cy >= 0:
            start_x = max(0, min(cx - crop_w // 2, w - crop_w))
            start_y = max(0, min(cy - crop_h // 2, h - crop_h))
            actual_cx = cx
            actual_cy = cy
        else:
            start_x = (w - crop_w) // 2
            start_y = (h - crop_h) // 2
            actual_cx = start_x + crop_w // 2
            actual_cy = start_y + crop_h // 2
    
    data_crop = data[start_y:start_y+crop_h, start_x:start_x+crop_w]
    
    z_data = data_crop.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    if plot3d:
        z_data_3d = z_data.copy()
    else:
        z_data_3d = np.array([])
    

    
    if z_data.size > 0:
        crop_med = float(np.median(z_data))
        crop_mad = float(np.median(np.abs(z_data - crop_med)))
        z_max = (crop_med + k_val * crop_mad) * 2.0
    else:
        z_max = 255.0
    if z_max <= 0:
        z_max = 255.0

    # Calculate 1D medians for full image banding analysis
    col_medians = np.median(data, axis=0)
    row_medians = np.median(data, axis=1)
    col_medians_list = [float(x) for x in col_medians]
    row_medians_list = [float(x) for x in row_medians]
    col_x_list = list(range(len(col_medians_list)))
    row_x_list = list(range(len(row_medians_list)))

    # Calculate 16x16 medians and MADs
    grid_h, grid_w = h / 16.0, w / 16.0
    medians_16x16 = np.zeros((16, 16))
    mads_16x16 = np.zeros((16, 16))
    for i in range(16):
        for j in range(16):
            r_start = int(i * grid_h)
            r_end = int((i+1)*grid_h) if i < 15 else h
            c_start = int(j * grid_w)
            c_end = int((j+1)*grid_w) if j < 15 else w
            region = data[r_start:r_end, c_start:c_end]
            if region.size > 0:
                med = float(np.median(region))
                medians_16x16[i, j] = med
                mads_16x16[i, j] = float(np.median(np.abs(region - med)))

    overall_med = float(np.median(data))
    overall_mad = float(np.median(np.abs(data - overall_med)))
    global_threshold_severe = overall_med + k_val * overall_mad
    global_threshold_mild = overall_med + (k_val / 10.0) * overall_mad

    all_hotspots = []
    # Hotspot count grid (16x16)
    hotspot_counts_16x16 = np.zeros((16, 16), dtype=int)
    total_hotspots = 0
    for i in range(16):
        for j in range(16):
            r_start = int(i * grid_h)
            r_end = int((i+1)*grid_h) if i < 15 else h
            c_start = int(j * grid_w)
            c_end = int((j+1)*grid_w) if j < 15 else w
            region = data[r_start:r_end, c_start:c_end]
            if region.size > 0:
                if use_global_mad:
                    ref_med = overall_med
                    ref_mad = overall_mad
                else:
                    ref_med = medians_16x16[i, j]
                    ref_mad = mads_16x16[i, j]
                
                threshold_severe = ref_med + k_val * ref_mad
                threshold_mild = ref_med + (k_val / 10.0) * ref_mad
                mask = region > threshold_mild

                if has_scipy:
                    labeled_array, num_features = label(mask)
                    if num_features > 0:
                        import scipy.ndimage as ndi
                        peaks = ndi.maximum_position(region, labels=labeled_array, index=np.arange(1, num_features + 1))
                        for y_local, x_local in peaks:
                            val = float(region[int(y_local), int(x_local)])
                            is_severe = bool(val > threshold_severe)
                            all_hotspots.append({"x": int(x_local + c_start), "y": int(y_local + r_start), "val": val, "grid_r": i, "grid_c": j, "is_severe": is_severe})
                            if is_severe:
                                total_hotspots += 1
                                hotspot_counts_16x16[i, j] += 1
                else:
                    ys, xs = np.where(mask)
                    if len(ys) > 0:
                        vals = region[ys, xs]
                        if len(ys) > 100:
                            idx = np.argpartition(vals, -100)[-100:]
                            ys = ys[idx]
                            xs = xs[idx]
                            vals = vals[idx]
                        for y_local, x_local, val in zip(ys, xs, vals):
                            val = float(val)
                            is_severe = bool(val > threshold_severe)
                            all_hotspots.append({"x": int(x_local + c_start), "y": int(y_local + r_start), "val": val, "grid_r": i, "grid_c": j, "is_severe": is_severe})
                            if is_severe:
                                total_hotspots += 1
                                hotspot_counts_16x16[i, j] += 1

                hotspot_counts_16x16[i, j] = min(hotspot_counts_16x16[i, j], 200)

    # Sort hotspots by value descending
    all_hotspots.sort(key=lambda item: item["val"], reverse=True)
    hotspots = [hs for hs in all_hotspots if hs["is_severe"]][:50]
    
    if len(all_hotspots) > 5000:
        all_hotspots = all_hotspots[:5000]

    if len(all_hotspots) > 5000:
        all_hotspots = all_hotspots[:5000]

    
    all_hotspot_vals_severe = [float(hs["val"]) for hs in all_hotspots if hs["is_severe"]]
    all_hotspot_vals_mild = [float(hs["val"]) for hs in all_hotspots if not hs["is_severe"]]
    
    medians_1d = [float(x) for x in medians_16x16.flatten()]

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Dark Image 3D View</title>
        <link rel="stylesheet" href="/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <style>
            .dark-layout-4col {
                display: grid;
                grid-template-columns: 13% 30% 30% 27%;
                gap: 1rem;
                height: calc(100vh - 120px);
            }
            .col-files { background: var(--bg-sidebar); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-center { position: relative; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-right { display: flex; flex-direction: column; gap: 1rem; height: calc(100vh - 120px); }
            .side-plot { flex: 1; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; overflow: hidden; position: relative; }
            #plot { flex: 1; min-height: 55%; position: relative; }
            .line-plots-container { display: flex; flex-direction: column; height: 45%; border-top: 1px solid var(--glass-border); }
            .line-plot-box { flex: 1; padding: 5px 10px; position: relative; display: flex; flex-direction: column; }
            /* Adjust list-item height and font based on previous request while keeping LOGDATA design */
            .list-item { padding: 8px 8px !important; }
            .file-name { font-size: 0.68rem !important; }
            .highlighted-grid-item {
                border: 2px solid red !important;
                box-sizing: border-box !important;
                z-index: 10;
                position: relative;
            }
        </style>
        <script>
            function changeFile(filename) {
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('file', filename);
                window.location.search = urlParams.toString();
            }
            async function updateCropData(r, c, cx, cy) {
                // Instantly update highlights
                highlightGrid(r, c);

                // Update URL quietly so sharing works
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('grid_row', r);
                urlParams.set('grid_col', c);
                urlParams.set('cx', cx);
                urlParams.set('cy', cy);
                window.history.replaceState({}, '', '?' + urlParams.toString());
                
                // Sync the inputs
                document.getElementById('crop-x').value = cx;
                document.getElementById('crop-y').value = cy;

                // Stop if plot3d is OFF
                if (!document.getElementById('plot3d-toggle').checked) {
                    return;
                }

                // Fetch new 3D data and render
                document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:var(--text-dim); font-size:0.8rem;">Loading 3D Data...</div>';
                var fetchUrl = `/api/starforge/dark_crop_3d?dir=${encodeURIComponent('__DIR__')}&session=${encodeURIComponent('__SESSION__')}&file=${encodeURIComponent('__FILE__')}&out_dir=${encodeURIComponent('__OUT_DIR__')}&grid_row=${r}&grid_col=${c}&cx=${cx}&cy=${cy}&k_val=${document.getElementById('k-val').value}`;
                
                try {
                    const response = await fetch(fetchUrl);
                    const result = await response.json();
                    
                    if (result.error) throw new Error(result.error);
                    
                    var new_z = result.z_data;
                    if (new_z && new_z.length > 0 && new_z[0].length > 0) {
                        var aspect_x = new_z[0].length / Math.max(new_z.length, new_z[0].length);
                        var aspect_y = new_z.length / Math.max(new_z.length, new_z[0].length);
                        var data3d = [{
                            z: new_z,
                            type: 'surface',
                            colorscale: 'Viridis',
                            cmin: 0,
                            cmax: result.z_max,
                            showscale: false
                        }];
                        var zmin = parseFloat(document.getElementById('z-min').value);
                        var zmax = parseFloat(document.getElementById('z-max').value);
                        if (isNaN(zmin)) zmin = 0;
                        if (isNaN(zmax)) zmax = result.z_max;

                        var layout3d = {
                            autosize: true,
                            scene: {
                                xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                                yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                                zaxis: { title: 'Luminance', range: [zmin, zmax], autorange: false },
                                aspectmode: 'manual',
                                aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                                camera: { eye: {x: -1.5, y: -1.5, z: 1.2} }
                            },
                            margin: { l: 0, r: 0, b: 0, t: 0 },
                            paper_bgcolor: '#121212',
                            plot_bgcolor: '#121212'
                        };
                        document.getElementById('plot').innerHTML = ''; // clear loading text
                        Plotly.newPlot('plot', data3d, layout3d, {responsive: true});
                    }
                } catch (e) {
                    document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:#ff3366; font-size:0.8rem;">Error loading 3D Data</div>';
                }
            }

            function updateK() {
                var new_k = document.getElementById('k-val').value;
                var use_global = document.getElementById('global-mad-toggle').checked ? '1' : '0';
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('k_val', new_k);
                urlParams.set('use_global_mad', use_global);
                window.location.search = urlParams.toString();
            }
            function updateCrop() {
                var cx = parseInt(document.getElementById('crop-x').value) || 0;
                var cy = parseInt(document.getElementById('crop-y').value) || 0;
                updateCropData(-1, -1, cx, cy);
            }
            function toggle3DPlot() {
                var isChecked = document.getElementById('plot3d-toggle').checked;
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('plot3d', isChecked ? '1' : '0');
                window.history.replaceState({}, '', '?' + urlParams.toString());
                
                if (isChecked) {
                    var cx = parseInt(document.getElementById('crop-x').value) || -1;
                    var cy = parseInt(document.getElementById('crop-y').value) || -1;
                    var r = parseInt(urlParams.get('grid_row'));
                    var c = parseInt(urlParams.get('grid_col'));
                    if (isNaN(r)) r = -1;
                    if (isNaN(c)) c = -1;
                    if (r === -1 && cx === -1 && cy === -1) {
                        r = 0; c = 0; // default
                    }
                    updateCropData(r, c, cx, cy);
                } else {
                    document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:var(--text-dim); font-size:0.8rem;">3D PLOT IS OFF (Enable in Analysis Setting)</div>';
                }
            }
            function highlightGrid(r, c) {
                // Clear existing highlights
                document.querySelectorAll('.highlighted-grid-item').forEach(el => {
                    el.classList.remove('highlighted-grid-item');
                });
                
                // Add highlight to all matching elements
                document.querySelectorAll(`[data-grid-r="${r}"][data-grid-c="${c}"]`).forEach(el => {
                    el.classList.add('highlighted-grid-item');
                });
            }
        </script>
    </head>
    <body>
        <div class="container" style="max-width: 100%; padding: 0 50px; box-sizing: border-box;">
            <header>
                <div class="header-main">
                    <h1>OrionFieldStack <span class="v-tag">Dark Viewer</span></h1>
                </div>
            </header>
            
            <main>
                <div class="dark-layout-4col">
                    <aside class="col-files">
                        <div style="padding: 15px; border-bottom: 1px solid var(--glass-border); background: var(--bg-card);">
                            <h3 style="margin: 0 0 8px 0;">ANALYSIS SETTING</h3>
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <span style="font-size: 0.75rem; color: #ccc; font-weight: bold;">HOTSPOT Thres. factor K:</span>
                                <input type="number" id="k-val" value="__K_VAL__" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateK()">
                            </div>
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
                                <span style="font-size: 0.75rem; color: #ccc; font-weight: bold;">USE GLOBAL MAD:</span>
                                <label style="display: flex; align-items: center; cursor: pointer;">
                                    <input type="checkbox" id="global-mad-toggle" __GLOBAL_MAD_CHECKED__ onchange="updateK()" style="margin: 0; width: auto; background: none; border: none; accent-color: var(--accent-gold);">
                                </label>
                            </div>
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
                                <span style="font-size: 0.75rem; color: #ccc; font-weight: bold;">3D PLOT:</span>
                                <label style="display: flex; align-items: center; cursor: pointer;">
                                    <input type="checkbox" id="plot3d-toggle" __PLOT3D_CHECKED__ onchange="toggle3DPlot()" style="margin: 0; width: auto; background: none; border: none; accent-color: var(--accent-gold);">
                                </label>
                            </div>
                        </div>
                        <div class="list-container" style="flex: 1; padding: 0; display: flex; flex-direction: column; overflow-y: auto;">
                            __OPTIONS__
                        </div>

                    </aside>
                    <div class="col-right">
                        <div style="display: flex; flex-direction: row; gap: 10px; flex: 1.2; overflow: hidden;">
                            <div class="side-plot" style="flex: 1.4; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                                <h3 style="margin: 0 0 8px 0;">ANALYSIS REPORT</h3>
                                <div style="flex: 1; display: flex; flex-direction: column; gap: 8px; overflow-y: auto;">
                                    <div style="background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                            <span style="font-size: 0.65rem; color: var(--text-dim);">Total Hotspots</span>
                                            <span style="font-size: 0.7rem; color: #fff; font-family: 'JetBrains Mono', monospace;">__TOTAL_HOTSPOTS__</span>
                                        </div>
                                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                            <span style="font-size: 0.65rem; color: var(--text-dim);">Global Median</span>
                                            <span style="font-size: 0.7rem; color: #fff; font-family: 'JetBrains Mono', monospace;">__OVERALL_MEDIAN__</span>
                                        </div>
                                        <div style="display: flex; justify-content: space-between;">
                                            <span style="font-size: 0.65rem; color: var(--text-dim);">Global MAD</span>
                                            <span style="font-size: 0.7rem; color: #fff; font-family: 'JetBrains Mono', monospace;">__OVERALL_MAD__</span>
                                        </div>
                                    </div>
                                    <div style="flex: 1; min-height: 90px; display: flex; flex-direction: column;">
                                        <div style="font-size: 0.65rem; color: var(--accent-gold); margin-bottom: 2px;">Hotspot Histogram</div>
                                        <div style="font-size: 0.55rem; color: var(--text-dim); margin-bottom: 2px;">Threshold: Median + K/10&times;MAD</div>
                                        <div id="plot-hs-hist" style="flex: 1; width: 100%; min-height: 70px;"></div>
                                    </div>
                                    <div style="flex: 1; min-height: 90px; display: flex; flex-direction: column;">
                                        <div style="font-size: 0.65rem; color: var(--accent-gold); margin-bottom: 2px;">Block Median Histogram</div>
                                        <div id="plot-med-hist" style="flex: 1; width: 100%; min-height: 70px;"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="side-plot" style="flex: 0.6; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                                <h3 style="margin: 0 0 8px 0;">HOTSPOTS (TOP 50)</h3>
                                <div id="hotspots-list" style="overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 0px;"></div>
                            </div>
                        </div>
                        <div class="side-plot" style="flex: 1; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                            <h3 style="margin: 0 0 2px 0;">16x16 HOTSPOT HEATMAP</h3>
                            <div style="font-size: 0.65rem; color: var(--text-dim); margin-bottom: 6px;">Threshold: Median + K&times;MAD &nbsp;|&nbsp; Total: <span style="color:#fff;">__TOTAL_HOTSPOTS__</span></div>
                            <div id="hotspot-count-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                        </div>
                    </div>
                    <div class="col-right">
                        <div class="side-plot" style="flex: 1; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                            <h3 style="margin: 0 0 8px 0;">16x16 MEDIAN HEATMAP</h3>
                            <div id="median-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                        </div>
                        <div class="side-plot" style="flex: 1; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                            <h3 style="margin: 0 0 8px 0;">16x16 MAD HEATMAP (Median Absolute Deviation)</h3>
                            <div id="mad-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                        </div>
                    </div>
                    <div class="col-center">
                        <h3 style="margin: 10px 10px 0 10px;">Local Pixel Surface(3D PLOT)</h3>
                        <div style="position: absolute; top: 35px; left: 10px; z-index: 10; display: flex; flex-direction: column; gap: 8px;">
                            <div style="display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.6); padding: 8px 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                                <span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: bold; margin-right: 4px;">CROP CENTER</span>
                                <label style="font-size: 0.75rem; color: var(--text-dim);">X:</label>
                                <input type="number" id="crop-x" value="__CROP_X__" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;">
                                <label style="font-size: 0.75rem; color: var(--text-dim); margin-left: 4px;">Y:</label>
                                <input type="number" id="crop-y" value="__CROP_Y__" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;">
                                <button onclick="updateCrop()" style="padding: 4px 8px; font-size: 0.7rem; border-radius: 4px; background: #333; color: #fff; border: 1px solid #555; cursor: pointer;">Apply</button>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.6); padding: 8px 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                                <span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: bold; margin-right: 4px;">Z-AXIS</span>
                                <label style="font-size: 0.75rem; color: var(--text-dim);">Min:</label>
                                <input type="number" id="z-min" value="0" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                                <label style="font-size: 0.75rem; color: var(--text-dim); margin-left: 4px;">Max:</label>
                                <input type="number" id="z-max" value="__ZMAX__" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                            </div>
                        </div>
                        <div id="plot"></div>
                        <div class="line-plots-container">
                            <div class="line-plot-box">
                                <h3 style="margin: 0 0 2px 0;">Row Median Profile</h3>
                                <div style="font-size: 0.65rem; color: var(--text-dim); margin-bottom: 2px;">Shows Vertical sensor non-uniformity.</div>
                                <div id="plot-row-median" style="flex: 1; width: 100%;"></div>
                            </div>
                            <div class="line-plot-box" style="border-top: 1px solid var(--glass-border);">
                                <h3 style="margin: 4px 0 2px 0;">Column Median Profile</h3>
                                <div style="font-size: 0.65rem; color: var(--text-dim); margin-bottom: 2px;">Shows horizontal sensor non-uniformity.</div>
                                <div id="plot-col-median" style="flex: 1; width: 100%;"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
        <script>
            var z_data = __ZDATA3D__;

 
            // 3D Plot
            if (z_data.length > 0 && z_data[0].length > 0) {
                var data3d = [{
                    z: z_data,
                    type: 'surface',
                    colorscale: 'Viridis',
                    cmin: 0,
                    cmax: __ZMAX__,
                    showscale: false
                }];
                var aspect_x = z_data[0].length / Math.max(z_data.length, z_data[0].length);
                var aspect_y = z_data.length / Math.max(z_data.length, z_data[0].length);

                var layout3d = {
                    autosize: true,
                    scene: {
                        xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                        yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                        zaxis: { title: 'Luminance', range: [0, __ZMAX__], autorange: false },
                        aspectmode: 'manual',
                        aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                        camera: {
                            eye: {x: -1.5, y: -1.5, z: 1.2}
                        }
                    },
                    margin: { l: 0, r: 0, b: 0, t: 0 },
                    paper_bgcolor: '#121212',
                    plot_bgcolor: '#121212'
                };
                Plotly.newPlot('plot', data3d, layout3d, {responsive: true});
            } else {
                document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:var(--text-dim); font-size:0.8rem;">3D PLOT IS OFF (Enable in Analysis Setting)</div>';
            }

            // Shared cell dimensions for click navigation
            var cell_w = __FULL_WIDTH__ / 16.0;
            var cell_h = __FULL_HEIGHT__ / 16.0;
            var sel_row = __GRID_ROW__;
            var sel_col = __GRID_COL__;

            function getClickAttr(i, j) {
                var click_cx = Math.round((j + 0.5) * cell_w);
                var click_cy = Math.round((i + 0.5) * cell_h);
                // Highlight handles the border dynamically now, but we keep onclick
                return `data-grid-r="${i}" data-grid-c="${j}" style="cursor: pointer;" onmouseover="this.style.opacity=0.7;" onmouseout="this.style.opacity=1;" onclick="updateCropData(${i}, ${j}, ${click_cx}, ${click_cy})"`;
            }

            // Populate 16x16 Grid
            var medians = __MEDIANS_16X16__;
            var max_med = -Infinity;
            var min_med = Infinity;
            for(var i=0; i<16; i++) {
                for(var j=0; j<16; j++) {
                    if (medians[i][j] > max_med) max_med = medians[i][j];
                    if (medians[i][j] < min_med) min_med = medians[i][j];
                }
            }
            var gridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = medians[i][j];
                    var norm = max_med > min_med ? (val - min_med) / (max_med - min_med) : 0;
                    var r = Math.round(30 + norm * 225);
                    var g = Math.round(30 + norm * 21);
                    var b = Math.round(30 + norm * 72);
                    gridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" ${getClickAttr(i, j)} title="Row ${i+1}, Col ${j+1}: ${val}">${Number(val.toPrecision(3))}</div>`;
                }
            }
            document.getElementById('median-grid').innerHTML = gridHtml;

            // Populate 16x16 MAD Grid
            var mads = __MADS_16X16__;
            var max_mad = -Infinity;
            var min_mad = Infinity;
            for(var i=0; i<16; i++) {
                for(var j=0; j<16; j++) {
                    if (mads[i][j] > max_mad) max_mad = mads[i][j];
                    if (mads[i][j] < min_mad) min_mad = mads[i][j];
                }
            }
            var madGridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = mads[i][j];
                    var norm = max_mad > min_mad ? (val - min_mad) / (max_mad - min_mad) : 0;
                    var r = Math.round(30 + norm * 123);
                    var g = Math.round(30 + norm * 21);
                    var b = Math.round(30 + norm * 225);
                    madGridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" ${getClickAttr(i, j)} title="Row ${i+1}, Col ${j+1}: ${val}">${Number(val.toPrecision(3))}</div>`;
                }
            }
            document.getElementById('mad-grid').innerHTML = madGridHtml;

            // Populate 16x16 Hotspot Count Grid
            var hs_counts = __HOTSPOT_COUNTS_16X16__;
            var hsGridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = hs_counts[i][j];
                    var r, g, b;
                    if (val === 0) {
                        r = 25; g = 25; b = 25;
                    } else {
                        var norm = Math.min(val / 200.0, 1.0);
                        r = Math.round(120 + norm * 135);
                        g = Math.round(40 + norm * 160);
                        b = Math.round(40 - norm * 40);
                    }
                    var displayVal = val >= 200 ? '200+' : val;
                    hsGridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" ${getClickAttr(i, j)} title="Row ${i+1}, Col ${j+1}: ${displayVal} hotspots">${displayVal}</div>`;
                }
            }
            document.getElementById('hotspot-count-grid').innerHTML = hsGridHtml;

            // Populate Hotspots
            var hotspots = __HOTSPOTS__;
            var hsHtml = '';
            hotspots.forEach((hs, idx) => {
                var hs_grid_col = hs.grid_c;
                var hs_grid_row = hs.grid_r;
                var click_cx = Math.round((hs_grid_col + 0.5) * cell_w);
                var click_cy = Math.round((hs_grid_row + 0.5) * cell_h);
                hsHtml += `<div data-grid-r="${hs_grid_row}" data-grid-c="${hs_grid_col}" style="padding: 2px 4px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.05);" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'" onclick="updateCropData(${hs_grid_row}, ${hs_grid_col}, ${click_cx}, ${click_cy})">
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; color: var(--text-bright);">#${idx+1} <span style="color:var(--accent-gold);">[${hs.x}, ${hs.y}]</span></span>
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; font-weight: bold; color: #ff3366;">${(hs.val/1000).toPrecision(3)}k</span>
                </div>`;
            });
            document.getElementById('hotspots-list').innerHTML = hsHtml;

            function updateZRange() {
                var zmin = parseFloat(document.getElementById('z-min').value);
                var zmax = parseFloat(document.getElementById('z-max').value);
                if (isNaN(zmin)) zmin = 0;
                if (isNaN(zmax)) zmax = __ZMAX__;
                
                Plotly.relayout('plot', {
                    'scene.zaxis.range': [zmin, zmax],
                    'scene.zaxis.autorange': false
                });
                Plotly.restyle('plot', {
                    cmin: [zmin],
                    cmax: [zmax]
                });

            }
            // Force apply range once to ensure 3D scene correctly clips
            if (document.getElementById('z-min') && z_data.length > 0) {
                updateZRange();
            }

            // Apply grid highlight on load for the selected grid
            if (sel_row >= 0 && sel_col >= 0) {
                highlightGrid(sel_row, sel_col);
            }

            // Render 1D Line plots
            var rowMedians = __ROW_MEDIANS__;
            var rowX = __ROW_X__;
            var colMedians = __COL_MEDIANS__;
            var colX = __COL_X__;

            var commonLayout = {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                margin: { l: 40, r: 10, t: 10, b: 20 },
                font: { color: '#ccc', size: 10 },
                xaxis: { showgrid: true, gridcolor: 'rgba(255,255,255,0.1)' },
                yaxis: { showgrid: true, gridcolor: 'rgba(255,255,255,0.1)' }
            };

            Plotly.newPlot('plot-row-median', [{
                x: rowX,
                y: rowMedians,
                type: 'scatter',
                mode: 'lines',
                line: { color: '#ff3366', width: 1 }
            }], commonLayout, { responsive: true, scrollZoom: true });

            Plotly.newPlot('plot-col-median', [{
                x: colX,
                y: colMedians,
                type: 'scatter',
                mode: 'lines',
                line: { color: '#33ccff', width: 1 }
            }], commonLayout, { responsive: true, scrollZoom: true });

            // Render Histograms in Analysis Report
            var hsValsSevere = __ALL_HOTSPOT_VALS_SEVERE__;
            var hsValsMild = __ALL_HOTSPOT_VALS_MILD__;
            var medians1D = __MEDIANS_1D__;

            var histLayout = {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                margin: { l: 25, r: 10, t: 10, b: 20 },
                font: { color: '#ccc', size: 9 },
                xaxis: { showgrid: false, zeroline: false },
                yaxis: { showgrid: true, gridcolor: 'rgba(255,255,255,0.1)', zeroline: false },
                showlegend: false,
                bargap: 0.05
            };
            var histLayoutStacked = JSON.parse(JSON.stringify(histLayout));
            histLayoutStacked.barmode = 'stack';
            histLayoutStacked.yaxis.type = 'log';

            var maxHs = Math.max(...hsValsSevere, ...hsValsMild, 1e-9);
            var hsXbins = { start: 0, end: maxHs, size: maxHs / 20 };
            
            var useGlobalMad = parseInt('__USE_GLOBAL_MAD__');
            if (useGlobalMad === 1) {
                var thrSevere = parseFloat('__GLOBAL_THRESHOLD_SEVERE__');
                var thrMild = parseFloat('__GLOBAL_THRESHOLD_MILD__');
                
                histLayoutStacked.shapes = [
                    { type: 'line', x0: thrMild, x1: thrMild, y0: 0, y1: 1, yref: 'paper', line: { color: '#ffcc00', width: 1, dash: 'dash' } },
                    { type: 'line', x0: thrSevere, x1: thrSevere, y0: 0, y1: 1, yref: 'paper', line: { color: '#ff3366', width: 1, dash: 'dash' } }
                ];
                var textMild = 'TH: ' + (thrMild / 1000).toPrecision(3) + 'k';
                var textSevere = 'TH: ' + (thrSevere / 1000).toPrecision(3) + 'k';
                histLayoutStacked.annotations = [
                    { x: thrMild, y: 1.0, yref: 'paper', text: textMild, showarrow: false, font: { color: '#ffcc00', size: 9 }, xanchor: 'left', yanchor: 'bottom' },
                    { x: thrSevere, y: 1.0, yref: 'paper', text: textSevere, showarrow: false, font: { color: '#ff3366', size: 9 }, xanchor: 'left', yanchor: 'bottom' }
                ];
                histLayoutStacked.margin.t = 15;
            }

            Plotly.newPlot('plot-hs-hist', [
                {
                    x: hsValsMild,
                    type: 'histogram',
                    marker: { color: '#ffcc00', opacity: 0.8 },
                    name: 'Mild',
                    xbins: hsXbins
                },
                {
                    x: hsValsSevere,
                    type: 'histogram',
                    marker: { color: '#ff3366', opacity: 0.8 },
                    name: 'Severe',
                    xbins: hsXbins
                }
            ], histLayoutStacked, { responsive: true, displayModeBar: false });

            var maxMed = Math.max(...medians1D, 1e-9);
            var medXbins = { start: 0, end: maxMed, size: maxMed / 20 };

            Plotly.newPlot('plot-med-hist', [{
                x: medians1D,
                type: 'histogram',
                marker: { color: '#33ccff', opacity: 0.8 },
                xbins: medXbins
            }], histLayout, { responsive: true, displayModeBar: false });
        </script>
    </body>
    </html>
    '''
    html = html_template.replace('__FILENAME__', file_path)\
        .replace('__ZDATA3D__', json.dumps(z_data_3d.tolist()))\
        .replace('__MEDIANS_16X16__', json.dumps(medians_16x16.tolist()))\
        .replace('__MADS_16X16__', json.dumps(mads_16x16.tolist()))\
        .replace('__ROW_MEDIANS__', json.dumps(row_medians_list))\
        .replace('__ROW_X__', json.dumps(row_x_list))\
        .replace('__COL_MEDIANS__', json.dumps(col_medians_list))\
        .replace('__COL_X__', json.dumps(col_x_list))\
        .replace('__HOTSPOT_COUNTS_16X16__', json.dumps(hotspot_counts_16x16.tolist()))\
        .replace('__TOTAL_HOTSPOTS__', str(total_hotspots))\
        .replace('__OVERALL_MEDIAN__', f"{overall_med:.2f}")\
        .replace('__OVERALL_MAD__', f"{overall_mad:.2f}")\
        .replace('__USE_GLOBAL_MAD__', str(use_global_mad))\
        .replace('__GLOBAL_THRESHOLD_SEVERE__', f"{global_threshold_severe:.2f}")\
        .replace('__GLOBAL_THRESHOLD_MILD__', f"{global_threshold_mild:.2f}")\
        .replace('__ALL_HOTSPOT_VALS_SEVERE__', json.dumps(all_hotspot_vals_severe))\
        .replace('__ALL_HOTSPOT_VALS_MILD__', json.dumps(all_hotspot_vals_mild))\
        .replace('__MEDIANS_1D__', json.dumps(medians_1d))\
        .replace('__HOTSPOTS__', json.dumps(hotspots))\
        .replace('__ZMAX__', str(z_max))\
        .replace('__ZDATA_FULL_LENGTH__', str(len(z_data)))\
        .replace('__ZDATA_FULL_WIDTH__', str(len(z_data[0]) if len(z_data) > 0 else 0))\
        .replace('__FULL_WIDTH__', str(w))\
        .replace('__FULL_HEIGHT__', str(h))\
        .replace('__CROP_X__', str(actual_cx))\
        .replace('__CROP_Y__', str(actual_cy))\
        .replace('__GRID_ROW__', str(grid_row))\
        .replace('__GRID_COL__', str(grid_col))\
        .replace('__PLOT3D_CHECKED__', "checked" if plot3d == 1 else "")\
        .replace('__GLOBAL_MAD_CHECKED__', "checked" if use_global_mad == 1 else "")
    print(html)
except Exception as e:
    print(f"<html><body><h3>Error processing image: {str(e)}</h3></body></html>")
"""
    try:
        from fastapi.responses import HTMLResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file, cx, cy, grid_row, grid_col, k_val, plot3d, use_global_mad,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return HTMLResponse(f"<html><body><h3>Error: Script execution failed.</h3><pre>{stderr.decode(errors='replace')}</pre></body></html>", status_code=500)
            
        final_html = stdout.decode(errors='replace') \
            .replace('__OPTIONS__', options_html) \
            .replace('__K_VAL__', k_val) \
            .replace('__DIR__', dir) \
            .replace('__SESSION__', session) \
            .replace('__FILE__', file) \
            .replace('__OUT_DIR__', out_dir)
        return HTMLResponse(final_html)
    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<html><body><h3>Error: {str(e)}</h3></body></html>", status_code=500)


# Serve static files
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Use string reference to allow hot-reload during development
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
