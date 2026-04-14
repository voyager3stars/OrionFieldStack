import numpy as np
from astropy.stats import sigma_clip

def stack_images(image_paths, method='median', sigma=3.0, iters=5, chunk_size=128):
    """
    Stacks a list of images stored on disk using a memory-efficient chunked approach.
    Supports both 2D (monochrome) and 3D (color) arrays.
    """
    if not image_paths:
        return None
        
    # Open all mmap handles once
    handles = [np.load(p, mmap_mode='r') for p in image_paths]
    shape = handles[0].shape
    n_frames = len(image_paths)
    
    # Initialize result array based on dimensions
    result = np.zeros(shape, dtype=np.float32)
    h = shape[0]
    w = shape[1]
    is_color = (len(shape) == 3)
    
    print(f"    [Stacking] Method: {method} ({n_frames} frames, {shape})")
    print(f"    [Stack-Logic] Initializing with chunk_size={chunk_size}...")
    
    # Process the image in horizontal chunks
    for y_start in range(0, h, chunk_size):
        y_end = min(y_start + chunk_size, h)
        progress = (y_start / h) * 100
        print(f"    [Stack-Logic] Processing: {progress:3.0f}% (Rows {y_start}-{y_end}/{h})...", flush=True)
        
        # Build chunk: (n_frames, chunk_h, w) or (n_frames, chunk_h, w, 3)
        chunk = np.array([m[y_start:y_end, ...] for m in handles], dtype=np.float32)
        
        if method == 'median':
            result[y_start:y_end, ...] = np.median(chunk, axis=0)
            
        elif method == 'mean':
            result[y_start:y_end, ...] = np.mean(chunk, axis=0)
            
        elif method == 'sigma_clip':
            # Sigma clipping on a 4D array (frames, h, w, 3) works across axis 0
            clipped = sigma_clip(chunk, sigma=sigma, maxiters=iters, axis=0)
            chunk_mean = np.ma.mean(clipped, axis=0)
            # Fill masked values with median
            result[y_start:y_end, ...] = chunk_mean.filled(np.median(chunk, axis=0))
            
        else:
            raise ValueError(f"Unsupported stacking method: {method}")
            
    print(f"    [Stack-Logic] 100% complete.")
    del handles
    return result

def save_stacked_fits(data, output_path, header=None):
    """
    Save the final stacked image to a FITS file.
    Ensures compatibility with astronomical tools like Siril by saving 
    color images in (C, H, W) format.
    """
    from astropy.io import fits
    
    save_data = data
    if data.ndim == 3:
        # Standard: (H, W, C) -> (C, H, W)
        save_data = np.transpose(data, (2, 0, 1))
        
    hdu = fits.PrimaryHDU(save_data, header=header)
    # Add history or processing tags
    hdu.header['HISTORY'] = 'Stacked using StarForge Star Registration and Stacking engine.'
    hdu.writeto(output_path, overwrite=True)
    print(f"  [Success] Master frame saved to: {output_path}")
