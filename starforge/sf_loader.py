import os
import numpy as np
import rawpy
from astropy.io import fits

def load_image(file_path, color=False):
    """
    Load an image file (DNG, RAW, FITS) and return image data.
    If color=True, returns RGB (H, W, 3). If color=False, returns monochrome (H, W).
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in ['.dng', '.raw']:
        return load_raw(file_path, color=color)
    elif ext in ['.fits', '.fit', '.fts']:
        return load_fits(file_path, color=color)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

def load_raw(file_path, color=False):
    """
    Load a RAW/DNG file using rawpy.
    """
    with rawpy.imread(file_path) as raw:
        rgb = raw.postprocess(use_camera_wb=True, 
                               half_size=False, 
                               no_auto_bright=True, 
                               output_bps=16)
        if color:
            return rgb.astype(np.float32)
        else:
            # Convert to grayscale
            gray = 0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]
            return gray.astype(np.float32)

def load_fits(file_path, color=False):
    """
    Load a FITS file using astropy.
    """
    with fits.open(file_path) as hdul:
        data = hdul[0].data
        if data is None and len(hdul) > 1:
            data = hdul[1].data
        
        if data is None:
            raise ValueError(f"No image data found in FITS: {file_path}")
            
        data = data.astype(np.float32)
        
        # Handle dimensionality
        if data.ndim == 3:
            # FITS often stores as (C, H, W). We standardize to (H, W, C)
            if data.shape[0] == 3:
                data = np.transpose(data, (1, 2, 0))
            
            if not color:
                # Convert RGB to mono
                data = 0.299 * data[:,:,0] + 0.587 * data[:,:,1] + 0.114 * data[:,:,2]
        elif data.ndim == 2:
            if color:
                # Expand mono to RGB if requested (though not typical)
                data = np.stack([data, data, data], axis=-1)
                
        return data
