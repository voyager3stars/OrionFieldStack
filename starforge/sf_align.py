import numpy as np
import astroalign as aa

def register_images(source_data, target_data):
    """
    Finds the transformation for target_data to match source_data and 
    returns the aligned version of target_data.
    Supports both 2D (monochrome) and 3D (color, HWC) arrays.
    """
    try:
        # Create grayscale versions for star matching
        src_mono = source_data
        tgt_mono = target_data
        
        if source_data.ndim == 3:
            # luminance transform (H, W, 3) -> (H, W)
            src_mono = 0.299 * source_data[:,:,0] + 0.587 * source_data[:,:,1] + 0.114 * source_data[:,:,2]
        if target_data.ndim == 3:
            tgt_mono = 0.299 * target_data[:,:,0] + 0.587 * target_data[:,:,1] + 0.114 * target_data[:,:,2]

        if target_data.ndim == 3:
            # Correct order: find mapping from target to source (tgt -> src)
            transf, _ = aa.find_transform(tgt_mono, src_mono)
            
            # Application of transform to all channels (H, W, 3)
            # Use a loop over RGB to ensure robust handling by astroalign
            aligned_color = np.zeros_like(target_data)
            for c in range(3):
                # aa.apply_transform returns (registered, footprint)
                aligned_color[:, :, c], _ = aa.apply_transform(transf, target_data[:, :, c], source_data[:, :, c])
            
            return aligned_color, None
        else:
            # Standard monochrome registration
            registered_image, footprint = aa.register(target_data, source_data)
            return registered_image, footprint
    
    except aa.MaxIterError:
        print("  [Error] Max iterations reached during image registration.")
        return None, None
    except Exception as e:
        print(f"  [Error] Alignment failed: {e}")
        return None, None

def find_transform(source_data, target_data):
    """
    Experimental: Just finds the transformation matrix without applying it.
    Can be used for batch transformation later or checking alignment quality.
    """
    try:
        transf, (s_list, t_list) = aa.find_transform(source_data, target_data)
        return transf
    except Exception as e:
        print(f"  [Error] Failed to find transform: {e}")
        return None
