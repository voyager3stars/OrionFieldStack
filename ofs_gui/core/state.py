import asyncio

# Global reference to the running process (ShutterPro)
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
