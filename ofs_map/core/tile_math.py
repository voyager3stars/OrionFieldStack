import math

def deg2num(lat_deg, lon_deg, zoom):
    """
    Converts latitude and longitude to tile (x, y) coordinates at a given zoom level.
    """
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    
    # Bound to valid range
    xtile = max(0, min(xtile, int(n) - 1))
    ytile = max(0, min(ytile, int(n) - 1))
    
    return (xtile, ytile)

def get_tiles_for_bbox(min_lat, max_lat, min_lon, max_lon, zoom):
    """
    Calculates all tile coordinates required for a bounding box at a given zoom level.
    Returns a set of tuples: {(z, x, y), (z, x, y), ...}
    """
    tiles = set()
    # OSM top-left is (0,0) and bottom-right is (max, max)
    # Latitude goes from top to bottom (90 to -90), so max_lat corresponds to min_y
    min_x, min_y = deg2num(max_lat, min_lon, zoom)
    max_x, max_y = deg2num(min_lat, max_lon, zoom)

    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            tiles.add((zoom, x, y))
            
    return tiles

def get_tiles_for_region(region):
    """
    Calculates all required tiles for a region dictionary.
    Region dict expected format:
    {
      "min_lat": float,
      "max_lat": float,
      "min_lon": float,
      "max_lon": float,
      "min_zoom": int,
      "max_zoom": int
    }
    """
    all_tiles = set()
    min_z = region.get('min_zoom', 0)
    max_z = region.get('max_zoom', 5)
    min_lat = region.get('min_lat', -85.0511)
    max_lat = region.get('max_lat', 85.0511)
    min_lon = region.get('min_lon', -180.0)
    max_lon = region.get('max_lon', 180.0)
    
    for z in range(min_z, max_z + 1):
        z_tiles = get_tiles_for_bbox(min_lat, max_lat, min_lon, max_lon, z)
        all_tiles.update(z_tiles)
        
    return all_tiles
