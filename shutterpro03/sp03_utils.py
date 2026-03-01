# =================================================================
# Project:      OrionFieldStack
# Component:    ShutterPro03 Utils
# Author:       voyager3.stars
# Web:          https://voyager3.stars.ne.jp
# Version:      14.1.1 (Formatting and Sexagesimal fix)
# License:      MIT
# Description:  Core utility module providing INDI client capabilities,
#               astronomical coordinate conversion (Decimal <-> HMS/DMS),
#               LST/Hour Angle calculation, Timezone detection, 
#               colorized console logging, and configuration management.
# =================================================================

import os
import sys
import json
import time
import math
import subprocess
from datetime import datetime, timezone
from timezonefinder import TimezoneFinder
import pytz

# Instantiate as a global variable (load the database only once at startup)
# This prevents the heavy database loading on every function call.
_tf = TimezoneFinder()


class IndiClient:
    """
    IndiClient handles communication with an INDI server via shell commands (indi_getprop).
    It retrieves astronomical telemetry such as coordinates, pier side, 
    and environmental data.
    
    New in v14.0.0:
    - Calculates Local Sidereal Time (LST) based on longitude and UTC.
    - Determines Hour Angle (HA) and Meridian Side (East/West).
    """
    def __init__(self, config):
        """
        Initializes the client with a reference to the global configuration.
        
        Args:
            config (dict): The main configuration dictionary.
        """
        self.config = config

    def _get_config_val(self, key, section=None, default=None):
        """
        Helper method to safely retrieve configuration values.
        """
        # Try to access as a nested dictionary first
        if section and section in self.config and isinstance(self.config[section], dict):
            return self.config[section].get(key, default)
        
        # Fallback: Try to access as a flat dictionary
        return self.config.get(key, default)
    
    def _get_prop(self, device, property_name, element_name):
        """
        INDIプロパティを取得する基本メソッド。
        """
        full_prop = f"{device}.{property_name}.{element_name}"
        try:
            # タイムアウトを1秒に設定し、外部コマンドを実行
            result = subprocess.check_output(
                ["indi_getprop", "-t", "1", full_prop], 
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            # 取得結果が "Device.Property.Element=Value" の形式であることを確認
            if "=" in result:
                return result.split('=')[1].strip()
        except:
            return None
        return None

    def _calc_lst(self, longitude, dt_utc):
        """
        Calculates Local Sidereal Time (LST) in decimal hours.
        """
        # Julian Date calculation (valid for 1901-2099)
        timestamp = dt_utc.timestamp()
        jd = (timestamp / 86400.0) + 2440587.5
        
        # GMST calculation
        t = (jd - 2451545.0) / 36525.0
        gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t**2 - (t**3 / 38710000)
        gmst = gmst % 360.0
        
        # LST = GMST + Longitude (degrees)
        lst_deg = (gmst + longitude) % 360.0
        
        # Convert degrees to hours (15 degrees = 1 hour)
        return lst_deg / 15.0

    def _to_hms(self, val):
        """
        Converts a decimal hour value to a formatted HH:MM:SS string.
        """
        if val is None: return "00:00:00"
        try:
            val = float(val) % 24
            h = int(val)
            m = int((val - h) * 60)
            s = int((((val - h) * 60) - m) * 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        except: 
            return "00:00:00"

    def _to_dms(self, val):
        """
        Converts a decimal degree value to a formatted +DD:MM:SS string.
        """
        if val is None: return "+00:00:00"
        try:
            val = float(val)
            sign = "-" if val < 0 else "+"
            val = abs(val)
            d = int(val)
            m = int((val - d) * 60)
            s = int((((val - d) * 60) - m) * 60)
            return f"{sign}{d:02d}:{m:02d}:{s:02d}"
        except: 
            return "+00:00:00"

    def _parse_sexagesimal(self, val):
        """
        'HH:MM:SS' または 'DD:MM:SS' 形式の文字列を float に変換する
        """
        if val is None: return None
        try:
            if isinstance(val, (int, float)): return float(val)
            parts = str(val).split(':')
            if len(parts) < 2: return float(val)
            
            d = float(parts[0])
            m = float(parts[1])
            s = float(parts[2]) if len(parts) > 2 else 0.0
            
            sign = -1 if d < 0 or parts[0].startswith('-') else 1
            return d + (sign * m / 60.0) + (sign * s / 3600.0)
        except:
            return None

    def get_observation_data(self):
        """
        INDIサーバーからテレメトリを取得し、JSON Spec v1.4.0準拠のデータを生成します。
        Logger(CSV)用の整形済み文字列 (_s) も同時に生成して返します。
        """
        # --- 1. 設定の取得 ---
        mount_dev = self._get_config_val('INDI_MOUNT', 'SYSTEM', 'LX200 OnStep')
        geo_prop  = self._get_config_val('PROP_GEO', 'SYSTEM', 'GEOGRAPHIC_COORD')
        wth_dev   = self._get_config_val('INDI_WEATHER', 'SYSTEM', mount_dev)
        wth_prop  = self._get_config_val('PROP_WEATHER', 'SYSTEM', 'WEATHER_PARAMETERS')

        # --- 2. 内部ヘルパー: 数値化と整形済み文字列の生成 ---
        def _fmt(val, prec):
            v = to_float_or_none(val)
            s = f"{v:.{prec}f}" if v is not None else ""
            return v, s

        # --- 3. INDIからのデータ取得 ---
        lat_raw = self._get_prop(mount_dev, geo_prop, "LAT") or self._get_prop(mount_dev, geo_prop, "LATITUDE")
        lon_raw = self._get_prop(mount_dev, geo_prop, "LONG") or self._get_prop(mount_dev, geo_prop, "LON")
        alt_raw = self._get_prop(mount_dev, geo_prop, "ELEV") or self._get_prop(mount_dev, geo_prop, "ALT")

        coord_candidates = ["EQUATORIAL_COORD", "EQUATORIAL_EOD_COORD", self._get_config_val('PROP_COORD', 'SYSTEM', 'EQUATORIAL_EOD_COORD')]
        ra_raw, dec_raw, status = None, None, "Unknown"

        for cp in coord_candidates:
            ra_val = self._get_prop(mount_dev, cp, "RA")
            if ra_val:
                ra_raw = ra_val
                dec_raw = self._get_prop(mount_dev, cp, "DEC")
                status = self._get_prop(mount_dev, cp, "STATE") or "Idle"
                break

        # --- 4. 座標・時間・LST計算 ---
        try:
            latitude = float(lat_raw)
            longitude = float(lon_raw)
            tz_source = "gps"
        except:
            latitude = float(self._get_config_val('LAST_LATITUDE', 'SYSTEM', 34.6493))
            longitude = float(self._get_config_val('LAST_LONGITUDE', 'SYSTEM', 135.0015))
            tz_source = "last_known"

        elevation = to_float_or_none(alt_raw) or float(self._get_config_val('LAST_ELEVATION', 'SYSTEM', 0.0))

        try:
            timezone_name = _tf.timezone_at(lat=latitude, lng=longitude) or "Asia/Tokyo"
        except:
            timezone_name = "Asia/Tokyo"
            
        now_utc = datetime.now(timezone.utc)
        
        try:
            tz_obj = pytz.timezone(timezone_name)
            now_tz = now_utc.astimezone(tz_obj)
            offset_str = now_tz.strftime('%z')
            utc_offset = f"{offset_str[:3]}:{offset_str[3:]}"
        except:
            utc_offset = "+09:00"

        lst_val = self._calc_lst(longitude, now_utc)
        meridian_side = self._get_prop(mount_dev, "SIDE_OF_PIER", "PIER_SIDE") or \
                        self._get_prop(mount_dev, "TELESCOPE_PIER_SIDE", "PIER_SIDE") or "Unknown"

        # --- 5. RA/DEC 変換と時角計算 (桁合わせ含む) ---
        ra_deg, dec_deg, hour_angle = None, None, None
        if ra_raw:
            try:
                r_val = self._parse_sexagesimal(ra_raw)
                if r_val is not None:
                    ra_deg = r_val * 15.0
                    ha_val = lst_val - r_val
                    if ha_val > 12: ha_val -= 24
                    if ha_val < -12: ha_val += 24
                    hour_angle = ha_val
                    if meridian_side == "Unknown":
                        meridian_side = "East" if ha_val < 0 else "West"
            except: pass
        
        if dec_raw:
            try:
                dec_deg = self._parse_sexagesimal(dec_raw)
            except: pass

        # 整形済みデータの生成
        lat_v, lat_s = _fmt(latitude, 6)
        lon_v, lon_s = _fmt(longitude, 6)
        elv_v, elv_s = _fmt(elevation, 1)
        ra_deg_v, ra_deg_s = _fmt(ra_deg, 6)
        dec_deg_v, dec_deg_s = _fmt(dec_deg, 6)
        ha_v, ha_s = _fmt(hour_angle, 4)

        w_temp_v, w_temp_s = _fmt(self._get_prop(wth_dev, wth_prop, "WEATHER_TEMPERATURE") or self._get_prop(wth_dev, "ATMOSPHERE", "TEMPERATURE"), 1)
        w_humi_v, w_humi_s = _fmt(self._get_prop(wth_dev, wth_prop, "WEATHER_HUMIDITY") or self._get_prop(wth_dev, "ATMOSPHERE", "HUMIDITY"), 1)
        w_pres_v, w_pres_s = _fmt(self._get_prop(wth_dev, wth_prop, "WEATHER_BAROMETER") or self._get_prop(wth_dev, "ATMOSPHERE", "PRESSURE"), 1)
        w_dew_v,  w_dew_s  = _fmt(self._get_prop(wth_dev, wth_prop, "WEATHER_DEWPOINT"), 1)
        
        # INDI (OnStep等) 側の温度取得
        cpu_mount_raw = self._get_prop(mount_dev, "WEATHER_PARAMETERS", "WEATHER_CPU_TEMPERATURE")
        cpu_mount_v, cpu_mount_s = _fmt(cpu_mount_raw, 1)
        
        cpu_rpi_v,    cpu_rpi_s    = _fmt(get_cpu_temp() if 'get_cpu_temp' in globals() else None, 1)

        # --- 6. 結果辞書の構築 ---
        return {
            "latitude": lat_v, "latitude_s": lat_s,
            "longitude": lon_v, "longitude_s": lon_s,
            "elevation": elv_v, "elevation_s": elv_s,
            "timezone": timezone_name, "utc_offset": utc_offset, "tz_source": tz_source,
            "site_name": self._get_config_val('DEFAULT_SITE_NAME', 'SYSTEM', "Unknown Site"),
            
            "ra_raw_val": ra_raw,
            "dec_raw_val": dec_raw,
            "ra_deg": ra_deg_v, "ra_deg_s": ra_deg_s,
            "dec_deg": dec_deg_v, "dec_deg_s": dec_deg_s,
            "ra_hms": deg_to_hms(ra_deg) if ra_deg is not None else str(ra_raw),
            "dec_dms": deg_to_dms(dec_deg) if dec_deg is not None else str(dec_raw),
            
            "side_of_pier": meridian_side,
            "lst_hms": deg_to_hms(lst_val * 15.0),
            "hour_angle": ha_v, "hour_angle_s": ha_s,
            "status": status,
            
            "weather_temp": w_temp_v, "weather_temp_s": w_temp_s,
            "weather_humi": w_humi_v, "weather_humi_s": w_humi_s,
            "weather_pres": w_pres_v, "weather_pres_s": w_pres_s,
            "weather_dew":  w_dew_v,  "weather_dew_s":  w_dew_s,
            "cpu_temp_mount":   cpu_mount_v, "cpu_temp_mount_s": cpu_mount_s,
            
            "cpu_temp_rpi":     cpu_rpi_v,   "cpu_temp_rpi_s":   cpu_rpi_s
        }

# --- Standalone Helper Functions (Original Implementation) ---

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read()) / 1000.0
    except:
        return None

def sp_print(message, config, level="full"):
    LOG_LEVELS = {"full": 3, "simple": 2, "off": 1}
    current_mode = config.get("DISPLAY_MODE", "full")
    if LOG_LEVELS.get(current_mode, 3) >= LOG_LEVELS.get(level, 3):
        if current_mode == "off": return
        print(f"\033[38;5;208m SP03>> {message}\033[0m")

def print_help(config):
    C_RESET, C_HEAD, C_KEY, C_VAL = "\033[0m", "\033[1;36m", "\033[32m", "\033[36m"
    sw_ver = config.get('VERSION', 'unknown')
    js_ver = config.get('JSON_SPEC', 'unknown')
    print(f"{C_HEAD}ShutterPro03 (v{sw_ver} / JSON Spec v{js_ver}) - Interactive Help{C_RESET}")
    print(f"Default settings loaded from 'config.json'. Arguments override these values.\n")
    print(f"{C_HEAD}[USAGE]{C_RESET}")
    print(f"  python3 shutterpro03.py [shots] [mode] [exposure_sec] [options...]\n")
    def p_opt(key, desc, current):
        print(f"  {C_KEY}{key:<20}{C_RESET}: {desc:<35}{C_VAL}[Current: {current}]{C_RESET}")
    ctx = config.get('CONTEXT', {})
    eqp = config.get('EQUIPMENT', {})
    sys_conf = config if 'SAVE_DIR' in config else config.get('SYSTEM', {})
    print(f" {C_HEAD}[CONTEXT]{C_RESET}")
    p_opt("objective (obj)=", "Target name / Object ID", ctx.get('objective', 'N/A'))
    p_opt("session (sess)=",  "Unique Session ID", ctx.get('session', 'def'))
    p_opt("type (t)=",        "Frame type", ctx.get('frame_type', 'test'))
    print(f"\n {C_HEAD}[EQUIPMENT]{C_RESET}")
    p_opt("telescope (tel)=", "Telescope / OTA", eqp.get('telescope', 'N/A'))
    p_opt("camera (cam)=",    "Imaging Camera", eqp.get('camera', 'N/A'))
    p_opt("focal (f)=",       "Focal Length (mm)", eqp.get('focal_length_mm', 0))
    p_opt("aperture (ap)=",   "Aperture (mm)", eqp.get('aperture_mm', 0))
    print(f"\n {C_HEAD}[SYSTEM]{C_RESET}")
    p_opt("dir=",             "Save Directory", sys_conf.get('SAVE_DIR', ''))
    p_opt("display=",         "Log verbosity", sys_conf.get('DISPLAY_MODE', 'full'))
    print("")

def load_config_file(base_config):
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                ext_conf = json.load(f)
            if "SYSTEM" in ext_conf:
                for k, v in ext_conf["SYSTEM"].items():
                    if k in base_config: base_config[k] = v
                    elif 'SYSTEM' in base_config and isinstance(base_config['SYSTEM'], dict):
                        base_config['SYSTEM'][k] = v
                    if k == "SAVE_DIR":
                         if k in base_config: base_config[k] = os.path.expanduser(v)
                         if 'SYSTEM' in base_config and isinstance(base_config['SYSTEM'], dict):
                             base_config['SYSTEM'][k] = os.path.expanduser(v)
            if "CONTEXT" in ext_conf and "CONTEXT" in base_config:
                base_config["CONTEXT"].update(ext_conf["CONTEXT"])
            if "EQUIPMENT" in ext_conf and "EQUIPMENT" in base_config:
                base_config["EQUIPMENT"].update(ext_conf["EQUIPMENT"])
                # メイン表示用の同期 (v14.0.1で追加)
                for key in ["telescope", "optics", "focal_length_mm", "aperture_mm", "camera"]:
                    if key in base_config["EQUIPMENT"]:
                        base_config[key] = base_config["EQUIPMENT"][key]
        except Exception as e:
            print(f" SP03>> Error loading config.json: {e}")
    return base_config

# --- Common Utilities (Legacy Support) ---

def deg_to_hms(val):
    if val is None: return "00:00:00"
    try:
        val = (float(val) / 15.0) % 24
        h = int(val)
        m = int((val - h) * 60)
        s = int((((val - h) * 60) - m) * 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    except: return "00:00:00"

def deg_to_dms(val):
    if val is None: return "+00:00:00"
    try:
        val = float(val)
        sign = "-" if val < 0 else "+"
        val = abs(val)
        d = int(val)
        m = int((val - d) * 60)
        s = int((((val - d) * 60) - m) * 60)
        return f"{sign}{d:02d}:{m:02d}:{s:02d}"
    except: return "+00:00:00"

def calculate_exposure_diff(actual_ms, exif_exp_tag):
    try:
        actual_sec = float(actual_ms) / 1000.0
        exif_sec = float(exif_exp_tag.values[0].num) / float(exif_exp_tag.values[0].den) if exif_exp_tag else actual_sec
        return round(actual_sec - exif_sec, 6)
    except: return 0.0

def calculate_equipment_specs(eq_config):
    try:
        f_len = float(eq_config.get("focal_length_mm", 0))
        aper = float(eq_config.get("aperture_mm", 0))
        pix_size = float(eq_config.get("pixel_size_um", 0))
        f_num = round(f_len / aper, 1) if aper > 0 else None
        pix_scale = round((pix_size * 206.265) / f_len, 2) if f_len > 0 else None
        return f_num, pix_scale
    except: return None, None

def to_float_or_none(val):
    try: return float(val)
    except (TypeError, ValueError): return None
