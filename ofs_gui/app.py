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

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHUTTERPRO_PATH = os.path.join(BASE_DIR, "shutterpro03", "shutterpro03.py")
SSE_PATH = os.path.join(BASE_DIR, "SSE", "SSE.py")
GUI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ofs_gui_sp03_config.json")

def get_sse_python():
    # Use the GUI's own python environment which is verified to have all dependencies
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

# Serve static files
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Use string reference to allow hot-reload during development
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
