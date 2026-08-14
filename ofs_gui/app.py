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
from routers import api_sync
app.include_router(api_sync.router)
from routers import api_shutter
app.include_router(api_shutter.router)
from routers import api_sse
app.include_router(api_sse.router)
from routers import api_starflux
app.include_router(api_starflux.router)
from routers import api_system
app.include_router(api_system.router)
from routers import api_logs
app.include_router(api_logs.router)
from routers import api_starforge, api_starforge_views
app.include_router(api_starforge.router)
app.include_router(api_starforge_views.router)

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import core.state as state

from core.config import *

# Global telemetry cache
state.latest_telemetry = {
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

state.latest_flashair = {
    "flashair": "DISCONNECTED",
    "url": "http://192.168.50.200"
}


async def update_telemetry_loop():
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
                    state.latest_telemetry = data
                except Exception as ex:
                    state.latest_telemetry["status"] = "PARSE_ERROR"
            else:
                state.latest_telemetry["indi_server"] = "DISCONNECTED"
                state.latest_telemetry["status"] = "ERROR"
        except Exception as e:
            state.latest_telemetry["indi_server"] = "DISCONNECTED"
            state.latest_telemetry["status"] = f"ERROR: {str(e)}"
        
        await asyncio.sleep(1.0)


async def update_flashair_loop():
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
                    state.latest_flashair = data
                except Exception as ex:
                    state.latest_flashair = {
                        "flashair": "DISCONNECTED",
                        "url": "http://192.168.50.200"
                    }
            else:
                state.latest_flashair = {
                    "flashair": "DISCONNECTED",
                    "url": "http://192.168.50.200"
                }
        except Exception as e:
            state.latest_flashair = {
                "flashair": "DISCONNECTED",
                "url": "http://192.168.50.200"
            }
        
        await asyncio.sleep(10.0)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(update_telemetry_loop())
    asyncio.create_task(update_flashair_loop())




# Serve static files
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Use string reference to allow hot-reload during development
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
