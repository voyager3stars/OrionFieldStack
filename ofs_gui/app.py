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


@app.get("/api/starforge/flat_view")
async def starforge_flat_view(dir: str, session: str = "", file: str = ""):
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
                    
    if not file_options:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><h3>Error: No flat images found in the specified directory/session.</h3></body></html>", status_code=404)

    selected_filename = file if file and file in file_map else file_options[0]
    target_file = file_map[selected_filename]
    
    options_html = ""
    for opt in file_options:
        sel = " selected" if opt == selected_filename else ""
        options_html += f'<div class="list-item{sel}" onclick="changeFile(\'{opt}\')"><div class="file-name">{opt}</div></div>'

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
                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=8)
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
                        <div class="list-title" title="__FILENAME__">Files</div>
                        <div class="list-container">
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


# Serve static files
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Use string reference to allow hot-reload during development
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
