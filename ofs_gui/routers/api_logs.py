import os
import json
import io
import rawpy
import re
from PIL import Image
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()

@router.get("/api/logs/browse")
async def browse_logs(path: str):
    full_path = os.path.abspath(os.path.expanduser(path))
    log_file = os.path.join(full_path, "shutter_log.json")
    
    if not os.path.exists(log_file):
        raise HTTPException(status_code=404, detail=f"shutter_log.json not found in {path}")
    
    try:
        with open(log_file, "r") as f:
            data = json.load(f, parse_constant=lambda x: None)
            
        for record in data:
            if "record" in record and "file" in record["record"]:
                file_path = record["record"]["file"].get("path", "")
                if file_path:
                    m = re.match(r"^/(?:home|Users)/[^/]+/(.*)$", file_path)
                    if m:
                        record["record"]["file"]["path"] = "~/" + m.group(1)
                        
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading log: {str(e)}")

@router.get("/api/logs/image")
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
                except (rawpy.LibRawError, AttributeError):
                    thumb = None

                if thumb:
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        thumb_data = thumb.data.tobytes() if hasattr(thumb.data, 'tobytes') else bytes(thumb.data)
                        return StreamingResponse(io.BytesIO(thumb_data), media_type="image/jpeg")
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
