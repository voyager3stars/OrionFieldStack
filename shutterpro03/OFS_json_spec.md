# OrionFieldStack JSON Log Specification v1.3.2

## 1. Overview
This document defines the integrated log schema for the **OrionFieldStack** project v1.3.2. This version emphasizes the independence of EXIF-derived data, INDI telemetry, and detailed analysis metrics for post-processing engines.

## 2. Data Structure

### 2.1 Root
| Key | Type | Description |
| :--- | :--- | :--- |
| `version` | String | JSON Spec version (e.g., "1.3.2"). |
| `session_id` | String | Unique session identifier (YYYYMMDD_Target_ID). |
| `objective` | String | Target object name (e.g., "M42 Orion Nebula"). |
| `equipment` | Object | Equipment details used for the session. |
| `record` | Object | The main data container for the shot. |

### 2.2 Equipment
Static equipment configuration derived from `config.json`.
| Key | Type | Description |
| :--- | :--- | :--- |
| `telescope` | String | Model of the telescope / OTA. |
| `optics` | String | Corrective optics (Reducer, Flattener, etc.). |
| `filter` | String | Filter used (e.g., "L-Pro", "None"). |
| `camera` | String | Camera model name. |
| `focal_length_mm`| Int | Combined effective focal length in mm. |

### 2.3 Record (Shot Data)

#### 2.3.1 Meta
Operational metadata regarding the capture timing and mode.
| Key | Type | Description |
| :--- | :--- | :--- |
| `timestamp_jst` | String | Local time (ISO8601: +09:00). |
| `timestamp_utc` | String | UTC time (ISO8601: Z). |
| `unixtime` | Float | Epoch seconds with millisecond precision. |
| `exposure_actual_sec`| Float | Exposure duration measured by software control. |
| `shot_mode` | String | Control mode ("bulb" or "camera"). |
| `frame_type` | String | Frame category ("Light", "Dark", "Flat", "Bias", "test"). |

#### 2.3.2 File
Information about the saved image file.
| Key | Type | Description |
| :--- | :--- | :--- |
| `name` | String | Output filename. |
| `path` | String | Absolute directory path to the file. |
| `format` | String | File extension (e.g., "DNG", "JPG"). |
| `size_mb` | Float | File size in Megabytes. |
| `width` | Int | Image width in pixels. |
| `height` | Int | Image height in pixels. |

#### 2.3.3 Exif
Metadata extracted directly from the image file (Camera source).
| Key | Type | Description |
| :--- | :--- | :--- |
| `iso` | Int | ISO Speed Ratings. |
| `shutter_sec` | Float | Exposure time recorded by the camera. |
| `model` | String | Camera model name from Exif tags. |
| `lat` | Float / Null | GPS Latitude from Exif (decimal degrees). |
| `lon` | Float / Null | GPS Longitude from Exif (decimal degrees). |
| `alt` | Float / Null | GPS Altitude from Exif (meters). |

#### 2.3.4 Mount
Telemetry data retrieved from the INDI Mount device.
| Key | Type | Description |
| :--- | :--- | :--- |
| `ra_deg` | Float / Null | Right Ascension in degrees. |
| `dec_deg` | Float / Null | Declination in degrees. |
| `ra_hms` | String | Right Ascension (HH:MM:SS). |
| `dec_dms` | String | Declination (+DD:MM:SS). |
| `status` | String / Null | Mount tracking status (e.g., "TRACKING"). |
| `side_of_pier` | String / Null | Pier side ("East" or "West"). |

#### 2.3.5 Location
Geographic coordinates retrieved from INDI/System settings.
| Key | Type | Description |
| :--- | :--- | :--- |
| `lat` | Float / Null | Latitude (decimal degrees). |
| `lon` | Float / Null | Longitude (decimal degrees). |
| `alt` | Float / Null | Elevation (meters). |

#### 2.3.6 Environment
Environmental data retrieved from INDI Weather devices.
| Key | Type | Description |
| :--- | :--- | :--- |
| `temp_c` | Float / Null | Ambient temperature (Celsius). |
| `humidity_pct` | Float / Null | Humidity (%). |
| `pressure_hPa` | Float / Null | Atmospheric pressure (hPa). |
| `cpu_temp_c` | Float / Null | Controller CPU temperature (Celsius). |

#### 2.3.7 Analysis
Placeholders for future post-processing and plate-solving results.
| Key | Type | Description |
| :--- | :--- | :--- |
| `solve_status` | String | Plate solving status ("pending", "solved", "failed"). |
| `solved_coords` | Object / Null | Actual RA/DEC determined by plate solver. |
| `quality` | Object | Image quality metrics container. |
| `quality.hfr` | Float / Null | Half Flux Radius (Star sharpness). |
| `quality.stars` | Int / Null | Number of stars detected. |
| `quality.elongation`| Float / Null | Star elongation (Tracking error indicator). |
| `quality.satellite_detected`| Bool | True if satellite trails are detected. |
| `quality.sky_brightness`| Float / Null | Sky background brightness level. |