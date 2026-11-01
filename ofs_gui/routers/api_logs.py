import os
import json
import io
import rawpy
import re
import hashlib
from PIL import Image, ImageOps
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter()

CACHE_DIR = os.path.expanduser("~/.cache/ofs/thumbnails")
os.makedirs(CACHE_DIR, exist_ok=True)

def generate_thumbnail(full_path: str, ext: str, max_size: int = 600) -> str:
    """画像の軽量サムネイルを生成し、キャッシュファイルパスを返す"""
    mtime = int(os.path.getmtime(full_path))
    cache_key = hashlib.md5(f"{full_path}_{mtime}_{max_size}".encode()).hexdigest()
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.jpg")
    
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
        return cache_file
    
    img = None
    if ext == ".dng":
        try:
            with rawpy.imread(full_path) as raw:
                try:
                    thumb = raw.extract_thumb()
                except Exception:
                    thumb = None
                
                if thumb:
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        thumb_data = thumb.data.tobytes() if hasattr(thumb.data, 'tobytes') else bytes(thumb.data)
                        img = Image.open(io.BytesIO(thumb_data))
                    else:
                        img = Image.fromarray(thumb.data)
                else:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False)
                    img = Image.fromarray(rgb)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DNG thumb error: {str(e)}")
    else:
        # JPEG, PNG 等
        try:
            im = Image.open(full_path)
            # JPEG の場合は draft を使ってデコードレベルで高速にダウンサンプリング
            if ext in [".jpg", ".jpeg"]:
                im.draft("RGB", (max_size, max_size))
            img = im.convert("RGB")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Image open error: {str(e)}")
            
    if img:
        resample_filter = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "Resampling") else getattr(Image, "ANTIALIAS", Image.BICUBIC)
        img.thumbnail((max_size, max_size), resample_filter)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        img.save(cache_file, format="JPEG", quality=75, optimize=True)
        return cache_file

    raise HTTPException(status_code=500, detail="Failed to create thumbnail")

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
async def get_image(
    path: str,
    thumb: bool = Query(False),
    max_size: int = Query(600)
):
    full_path = os.path.abspath(os.path.expanduser(path))
    
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    ext = os.path.splitext(full_path)[1].lower()
    
    # サムネイル要求時（プレビュー用高速パス）
    if thumb:
        if ext not in [".dng", ".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}")
        
        cache_path = await run_in_threadpool(generate_thumbnail, full_path, ext, max_size)
        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"}
        )

    # フルサイズ要求時（従来通り）
    if ext == ".dng":
        try:
            with rawpy.imread(full_path) as raw:
                try:
                    thumb_data = raw.extract_thumb()
                except (rawpy.LibRawError, AttributeError):
                    thumb_data = None

                if thumb_data:
                    if thumb_data.format == rawpy.ThumbFormat.JPEG:
                        data = thumb_data.data.tobytes() if hasattr(thumb_data.data, 'tobytes') else bytes(thumb_data.data)
                        return StreamingResponse(io.BytesIO(data), media_type="image/jpeg")
                    else:
                        img = Image.fromarray(thumb_data.data)
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

