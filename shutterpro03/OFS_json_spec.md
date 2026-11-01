# OrionFieldStack JSON Log Specification v1.6.3

## 1. Overview
This document defines the integrated log schema for the **OrionFieldStack** project.

## 2. Data Structure

### 2.1 Root
| Key | Type | Description | CSV Header |
| :--- | :--- | :--- | :--- |
| `version` | String | JSON Spec version (e.g., "1.6.1"). | **JSON_ver** |
| `session_id` | String | Unique session identifier. | **Session_ID** |
| `objective` | String | Target object name (e.g., "M42"). | **Objective** |
| `equipment` | **Object** | See 2.2 | - |
| `record` | **Object** | See 2.3 | - |
| `analysis` | **Object** | See 2.4 | - |

### 2.2 Equipment
| Key | Type | Description |  CSV Header |
| :--- | :--- | :--- | :--- |
| `equipment` | **Object** | **Equipment details used for the session.** | - |
| └`telescope` | String | Model of the telescope / OTA. | **Telescope** |
| └`optics` | String | Corrective optics (Reducer, etc.). | **Opt** |
| └`filter` | String | Filter used (e.g., "L-Pro"). | **Filter** |
| └`camera` | String | Camera model name. | **Camera** |
| └`aperture_mm`| Int | Objective aperture in mm. | **Aperture** |
| └`focal_length_mm`| Int | Combined effective focal length. | **Focal_L** |
| └`f_number` | Float | Calculated: FocalLength / Aperture | **F_num** |
| └`pixel_size_um`| Float | Camera pixel size | **Pixel_Size** |
| └`pixel_scale` | Float | Calculated: (PixSize * 206.265) / FocalLength | **Pixel_Scale** |

### 2.3 Record
| Key | Type | Description | CSV Header |
| :--- | :--- | :--- | :--- |
| **`record`** | **Object** | **The main data container for the shot.** | - |
| └`meta` | **Object** | - | - |
| &emsp;└`iso_timestamp` | String | Local time (ISO 8601). | **LocalTime** |
| &emsp;└`timestamp_utc` | String | UTC time (ISO 8601: Z). | **UTC_Time** |
| &emsp;└`utc_offset` | String | Current offset (e.g. +09:00) | **UTC_Offset** |
| &emsp;└`lst_hms` | String | Local Sidereal Time (HHhMMmSSs) | **LST** |
| &emsp;└`unixtime` | Float | Epoch seconds. | **UnixTime** |
| &emsp;└`exposure_actual_sec`| Float | Duration (Software measured). | **Sf_Exp_t** |
| &emsp;└`exposure_diff_sec` | Float | Difference: (Software - Exif). | **Diff Sf-Exif** |
| &emsp;└`shot_mode` | String | "bulb" or "camera". | **Mode** |
| &emsp;└`frame_type` | String | "Light", "Dark", "Flat", "Bias", "test". |**Type**| 
| └`file` | **Object** | - | - |
| &emsp;└`name` | String | Output filename. | **Filename** |
| &emsp;└`path` | String | Directory path to the file. | **SavedDir** |
| &emsp;└`format` | String | File extension (e.g., "DNG"). | **Format** |
| &emsp;└`size_mb` | Float | File size in Megabytes. | **FileSize** |
| &emsp;└`width` | Int | Image width in pixels. | **Width** |
| &emsp;└`height` | Int | Image height in pixels. | **Height** |
| └`exif` | **Object** | - | - |
| &emsp;└`iso` | Int | ISO Speed Ratings. | **ISO_Exif** |
| &emsp;└`shutter_sec` | Float | Exposure time (Exif source). | **Exposure_Exif** |
| &emsp;└`datetime_original`| String | Internal camera clock (Exif). | **DateTime_Exif** |
| &emsp;└`model` | String | Camera model name from Exif. | **Model** |
| &emsp;└`lat` | Float | GPS Latitude from Exif. | **Lat_Exif** |
| &emsp;└`lon` | Float | GPS Longitude from Exif. | **Lon_Exif** |
| &emsp;└`alt` | Float | GPS Altitude from Exif. | **Alt_Exif** |
| └`mount` | **Object** | - | - |
| &emsp;└`ra_deg` | Float | Right Ascension in degrees. | **RA** |
| &emsp;└`dec_deg` | Float | Declination in degrees. | **DEC** |
| &emsp;└`ra_hms` | String | Right Ascension (HHhMMmSSs). | **RA_HMS** |
| &emsp;└`dec_dms` | String | Declination (+DD°MM'SS"). | **DEC_DMS** |
| &emsp;└`status` | String | Mount tracking status. | **MT_Status** |
| &emsp;└`side_of_pier` | String | Pier side ("East" or "West"). | **Side** |
| &emsp;└`hour_angle` | Float | LST - RA_deg (Current position) | **HourAngle** |
| └`location` | **Object** | - | - |
| &emsp;└`site_name` | String | Label for the observation site. | **Site_Name** |
| &emsp;└`latitude` | Float | Latitude (GPS/INDI). | **Lat_INDI** |
| &emsp;└`longitude` | Float | Longitude (GPS/INDI). | **Lon_INDI** |
| &emsp;└`elevation` | Float | Elevation in meters (INDI). | **Alt_INDI** |
| &emsp;└`tz_source` | String | Source ("gps", "system", etc.). |  **TZ_Source** |
| `environment` | **Object** | - | - | - |
| &emsp;└`temp_c` | Float | Ambient temperature (C). | **Temp_Ext_C** |
| &emsp;└`humidity_pct` | Float | Humidity (%). | **Humidity_pct** |
| &emsp;└`pressure_hPa` | Float | Atmospheric pressure (hPa). | **Pressure_hPa** |
| &emsp;└`dew_point_c` | Float | Dew point temperature (C). | **DewPoint_C** |
| &emsp;└`cpu_temp_mount_c` | Float | INDI mount Controller CPU temperature (C). | **Mnt_CPU_Temp_C** |
| &emsp;└`cpu_temp_rpi_c` | Float | RPi CPU temperature (C). | **RPi_CPU_Temp_C** |

### 2.4 Analysis

| Hierarchy / Key | Type | Description | CSV Header |
| :--- | :--- | :--- | :--- |
| **`analysis`** | **Object** | - | - |
| └`SSE` | **Object** | **Container for Plate Solving (StarSloveEngine integration)** | - | - |
| &emsp;└`sse_version` | String | SSE Engine version. | **SSE_Version** |
| &emsp;└`solve_status` | String | "success" or "failed". | **Solve_Status** |
| &emsp;└`solve_path` | String | Strategy used (e.g., "Pass 1"). | **Solve_Path** |
| &emsp;└`confidence` | Float | Solve reliability (log-odds ratio). | **Solve_Confidence** |
| &emsp;└`timestamp` | String | Solve execution timestamp. | **Solve_Timestamp** |
| &emsp;└`solved_coords` | **Object** | **Container for results** | - |
| &emsp;&emsp;└`ra_deg` | Float | RA in decimal degrees. | **Solve_RA** |
| &emsp;&emsp;└`dec_deg` | Float | Dec in decimal degrees. | **Solve_DEC** |
| &emsp;&emsp;└`orientation`| Float | Field rotation angle. | **Solve_Orientation** |
| &emsp;&emsp;└`ra_hms` | String | RA in HHhMMmSSs | **Solve_RA_hms** |
| &emsp;&emsp;└`dec_dms` | String | Dec in +DD°MM'SS" | **Solve_DEC_dms** |
| &emsp;└`process_stats` | **Object** | **Container for process metrics** | - |
| &emsp;&emsp;└`matched_stars`| Int | Stars used for solving. |  **Matched_Stars** |
| &emsp;&emsp;└`solve_duration_sec`| Float | Pure solve time (seconds). | **Solve_Time_sec** |
| └`SF` | **Object** | **Container for image quality (StarFlux integration)** | - |
| &emsp;└`sf_version` | String | StarFlux version. | **SF_version** |
| &emsp;└`sf_status` | String | "success" or "failed". | **SF_status** |
| &emsp;└`sf_timestamp` | String | Quality analysis execution timestamp. | **SF_timestamp** |
| &emsp;└`bg_image` | **Object** | **Container for saved background image** | - |
| &emsp;&emsp;└`path` | String | Directory path to the saved background image. | **bg_image_path** |
| &emsp;&emsp;└`name` | String | Filename of the saved background image. | **bg_image_name** |
| &emsp;└`quality` | **Object** | **Container for quality** | - |
| &emsp;&emsp;└`sf_stars` | Int | Number of stars used for quality analysis. | **SF_stars** |
| &emsp;&emsp;└`sf_fwhm_med` | Float | Median FWHM (Full Width at Half Maximum). | **SF_fwhm_med** |
| &emsp;&emsp;└`sf_fwhm_mean` | Float | Mean FWHM value. | **SF_fwhm_mean** |
| &emsp;&emsp;└`sf_fwhm_std` | Float | Standard deviation of FWHM. | **SF_fwhm_std** |
| &emsp;&emsp;└`sf_ell_med` | Float | Median Ellipticity (1 - b/a). | **SF_ell_med** |
| &emsp;&emsp;└`sf_ell_mean` | Float | Mean Ellipticity value. | **SF_ell_mean** |
| &emsp;&emsp;└`sf_ell_std` | Float | Standard deviation of Ellipticity. | **SF_ell_std** |
| &emsp;&emsp;└`sf_bg_median` | Float | Median of the background ADU. | **SF_bg_median** |
| &emsp;&emsp;└`sf_bg_mad` | Float | Median Absolute Deviation of the background noise. | **SF_bg_mad** |


EOF