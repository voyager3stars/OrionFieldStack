# OrionFieldStack JSON Log Specification v1.4.2

## 1. Overview
This document defines the integrated log schema for the **OrionFieldStack** project. While JSON serves as the primary master log for full session data, this specification also defines the mapping to the flat CSV log for quick analysis. **No legacy fields from v1.3.2 have been removed.**

## 2. Data Structure

### 2.1 Root
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `version` | String | JSON Spec version (e.g., "1.4.0"). | - | - |
| `session_id` | String | Unique session identifier. | Yes | **Session_ID** |
| `objective` | String | Target object name (e.g., "M42"). | Yes | **Objective** |
| `equipment` | Object | Equipment details used for the session. | - | - |
| `record` | Object | The main data container for the shot. | - | - |

### 2.2 Equipment
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `telescope` | String | Model of the telescope / OTA. | Yes | **Telescope** |
| `optics` | String | Corrective optics (Reducer, etc.). | - | - |
| `filter` | String | Filter used (e.g., "L-Pro"). | Yes | **Filter** |
| `camera` | String | Camera model name. | - | - |
| `aperture_mm`| Int | Objective aperture in mm. | - | - |
| `focal_length_mm`| Int | Combined effective focal length. | - | - |
| `f_number` | Float | Calculated: FocalLength / Aperture | - | - |
| `pixel_size_um`| Float | Camera pixel size | - | - |
| `pixel_scale` | Float | Calculated: (PixSize * 206.265) / FocalLength | - | - |

### 2.3 Record (Shot Data)

#### 2.3.1 Meta
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `iso_timestamp` | String | Local time (ISO 8601). | Yes | **LocalTime** |
| `timestamp_utc` | String | UTC time (ISO 8601: Z). | - | - |
| `utc_offset` | String | Current offset (e.g. +09:00) | Yes | **UTC_Offset** |
| `lst_hms` | String | Local Sidereal Time (HH:MM:SS) | Yes | **LST** |
| `unixtime` | Float | Epoch seconds. | - | - |
| `exposure_actual_sec`| Float | Duration (Software measured). | - | - |
| `exposure_diff_sec` | Float | Difference: (Software - Exif). | - | - |
| `shot_mode` | String | "bulb" or "camera". | - | - |
| `frame_type` | String | "Light", "Dark", "Flat", "Bias", "test". | Yes | **Frame_Type** |

#### 2.3.2 File
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `name` | String | Output filename. | Yes | **Filename** |
| `path` | String | Directory path to the file. | Yes | **SavedDir** |
| `format` | String | File extension (e.g., "DNG"). | Yes | **Format** |
| `size_mb` | Float | File size in Megabytes. | - | - |
| `width` | Int | Image width in pixels. | - | - |
| `height` | Int | Image height in pixels. | - | - |

#### 2.3.3 Exif
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `iso` | Int | ISO Speed Ratings. | Yes | **ISO_Exif** |
| `shutter_sec` | Float | Exposure time (Exif source). | Yes | **Exposure_Exif** |
| `datetime_original`| String | Internal camera clock (Exif). | Yes | **DateTime_Exif** |
| `model` | String | Camera model name from Exif. | - | - |
| `lat` | Float | GPS Latitude from Exif. | - | - |
| `lon` | Float | GPS Longitude from Exif. | - | - |
| `alt` | Float | GPS Altitude from Exif. | - | - |

#### 2.3.4 Mount (Telemetry)
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `ra_deg` | Float | Right Ascension in degrees. | - | - |
| `dec_deg` | Float | Declination in degrees. | - | - |
| `ra_hms` | String | Right Ascension (HH:MM:SS). | Yes | **RA_HMS** |
| `dec_dms` | String | Declination (+DD:MM:SS). | Yes | **DEC_DMS** |
| `status` | String | Mount tracking status. | - | - |
| `side_of_pier` | String | Pier side ("East" or "West"). | Yes | **Side** |
| `hour_angle` | Float | LST - RA_deg (Current position) | - | - |

#### 2.3.5 Location
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `site_name` | String | Label for the observation site. | Yes | **Site_Name** |
| `latitude` | Float | Latitude (GPS/INDI). | Yes | **Lat_INDI** |
| `longitude` | Float | Longitude (GPS/INDI). | Yes | **Lon_INDI** |
| `elevation` | Float | Elevation in meters (INDI). | Yes | **Alt_INDI** |
| `tz_source` | String | Source ("gps", "system", etc.). | Yes | **TZ_Source** |

#### 2.3.6 Environment
| Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `temp_c` | Float | Ambient temperature (C). | Yes | **Temp_Ext_C** |
| `humidity_pct` | Float | Humidity (%). | Yes | **Humidity_pct** |
| `pressure_hPa` | Float | Atmospheric pressure (hPa). | Yes | **Pressure_hPa** |
| `dew_point_c` | Float | Dew point temperature (C). | Yes | **DewPoint_C** |
| `cpu_temp_mount_c` | Float | INDI mount Controller CPU temperature (C). | Yes | **Mnt_CPU_Temp_C** |
| `cpu_temp_rpi_c` | Float | RPi CPU temperature (C). | Yes | **RPi_CPU_Temp_C** |

#### 2.3.7 Analysis (v2.0.0 Hierarchical Structure)

| Hierarchy / Key | Type | Description | In CSV | CSV Header |
| :--- | :--- | :--- | :---: | :--- |
| `solve_status` | String | "success" or "failed". | Yes | **Solve_Status** |
| `solve_path` | String | Strategy used (e.g., "Pass 1"). | Yes | **Solve_Path** |
| `sse_version` | String | SSE Engine version. | Yes | **SSE_Version** |
| `confidence` | Float | Solve reliability (log-odds ratio). | Yes | **Solve_Confidence** |
| **`solved_coords`** | **Object** | **Container for results** | - | - |
| └ `.ra_deg` | Float | RA in decimal degrees. | Yes | **Solve_RA** |
| └ `.dec_deg` | Float | Dec in decimal degrees. | Yes | **Solve_DEC** |
| └ `.orientation`| Float | Field rotation angle. | Yes | **Solve_Orientation** |
| └ `.ra_hms` | String | RA in HH:MM:SS.ss | No | - |
| └ `.dec_dms` | String | Dec in +DD:MM:SS.ss | No | - |
| **`process_stats`** | **Object** | **Container for process metrics** | - | - |
| └ `.matched_stars`| Int | Stars used for solving. | Yes | **Matched_Stars** |
| └ `.solve_duration_sec`| Float | Pure solve time (seconds). | Yes | **Solve_Time_sec** |
| **`quality`** | **Object** | **Container for image quality** | - | - |
| └ `.hfr` | Float | Star sharpness (Half Flux Radius). | No | - |
| └ `.elongation`| Float | Star shape distortion. | No | - |
EOF