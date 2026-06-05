import rawpy
from PIL import Image
import os
import io
import sys

path = "/home/mtorig/Pictures/260510_IMGP2181.DNG"
def log(msg):
    print(msg)
    sys.stdout.flush()

log(f"Testing path: {path}")

try:
    if not os.path.exists(path):
        log("File not found")
        exit(1)
        
    log("Opening DNG with rawpy...")
    with rawpy.imread(path) as raw:
        log("Read DNG successfully")
        try:
            log("Extracting thumbnail...")
            thumb = raw.extract_thumbnail()
            log(f"Thumbnail extracted: {thumb.format}")
        except Exception as e:
            log(f"No thumbnail or error: {e}")
            thumb = None
            
        if thumb:
            if thumb.format == rawpy.ThumbFormat.JPEG:
                log("Thumbnail is JPEG")
            else:
                img = Image.fromarray(thumb.data)
                log("Converted bitmap thumbnail to PIL")
        else:
            log("Developing RAW (this might take time)...")
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False)
            img = Image.fromarray(rgb)
            log("Developed RAW to PIL")
            
    log("Success")
except Exception as e:
    log(f"Error: {e}")
    import traceback
    traceback.print_exc()
