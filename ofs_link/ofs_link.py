#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import argparse
import time
import select
import urllib.request
import urllib.error
from datetime import datetime, timezone
from timezonefinder import TimezoneFinder
import pytz

# TimezoneFinderをグローバルに初期化
tf = TimezoneFinder()

def parse_sexagesimal(val):
    """
    'HH:MM:SS' または 'DD:MM:SS' 形式の文字列を float に変換する
    """
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        parts = str(val).split(':')
        if len(parts) < 2:
            return float(val)
        
        d = float(parts[0])
        m = float(parts[1])
        s = float(parts[2]) if len(parts) > 2 else 0.0
        
        sign = -1 if d < 0 or parts[0].startswith('-') else 1
        return d + (sign * m / 60.0) + (sign * s / 3600.0)
    except:
        return None

def calc_lst(longitude, dt_utc):
    """
    経度とUTC時間から地方恒星時(LST)を計算する (decimal hours)
    """
    try:
        timestamp = dt_utc.timestamp()
        jd = (timestamp / 86400.0) + 2440587.5
        t = (jd - 2451545.0) / 36525.0
        gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t**2 - (t**3 / 38710000)
        gmst = gmst % 360.0
        lst_deg = (gmst + longitude) % 360.0
        return lst_deg / 15.0
    except:
        return None

def format_ra(ra_deg):
    """
    RA (度数, 0 ~ 360) を 'XXhXXmXXs' 形式の文字列に変換する。
    """
    if ra_deg is None:
        return None
    ra_deg = ra_deg % 360.0
    ra_hours = ra_deg / 15.0
    
    total_seconds = round(ra_hours * 3600.0)
    total_seconds = total_seconds % 86400
    
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    
    return f"{h:02d}h{m:02d}m{s:02d}s"

def format_dec(dec_deg):
    """
    DEC (度数, -90 ~ 90) を 'XX°XX'XX"' 形式の文字列に変換する。
    符号は、正の場合は '+'、負の場合は '-' を明示する。
    """
    if dec_deg is None:
        return None
    dec_deg = max(-90.0, min(90.0, dec_deg))
    
    sign = "-" if dec_deg < 0 else "+"
    abs_dec = abs(dec_deg)
    
    total_seconds = round(abs_dec * 3600.0)
    total_seconds = min(total_seconds, 324000)
    
    d = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    
    return f"{sign}{d:02d}°{m:02d}'{s:02d}\""

def check_flashair(base_url, timeout=3.0):
    """
    FlashAirカードへの接続を確認する。
    /command.cgi?op=100&DIR=/DCIM へのリクエストが成功するかどうかで判定する。
    """
    url = f"{base_url}/command.cgi?op=100&DIR=/DCIM"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                return True
    except urllib.error.URLError:
        pass
    except Exception:
        pass
    return False

def load_config(config_path_arg=None):
    """
    config.jsonの読み込み。優先順位：
    1. --config で指定されたファイルパス
    2. 自身のスクリプトと同じディレクトリの config.json
    3. 親ディレクトリの ../shutterpro03/config.json
    """
    config = {
        "INDI_MOUNT": "LX200 OnStep",
        "PROP_COORD": "EQUATORIAL_EOD_COORD",
        "PROP_GEO": "GEOGRAPHIC_COORD",
        "LAST_LATITUDE": 34.6493,
        "LAST_LONGITUDE": 135.0015,
        "LAST_ELEVATION": 54.0,
        "FLASHAIR_URL": "http://192.168.50.200"
    }
    
    paths_to_try = []
    if config_path_arg:
        paths_to_try.append(os.path.abspath(config_path_arg))
        
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths_to_try.append(os.path.join(current_dir, "config.json"))
    paths_to_try.append(os.path.abspath(os.path.join(current_dir, "../shutterpro03/config.json")))
    
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    
                    # shutterpro03 の config.json 構造（SYSTEMキーがある場合）に対応
                    target_dict = loaded.get("SYSTEM", loaded) if isinstance(loaded, dict) else {}
                    
                    for k in config.keys():
                        if k in target_dict:
                            # 数値型に変換できるものは変換する
                            if k in ["LAST_LATITUDE", "LAST_LONGITUDE", "LAST_ELEVATION"]:
                                try:
                                    config[k] = float(target_dict[k])
                                except:
                                    config[k] = target_dict[k]
                            else:
                                config[k] = target_dict[k]
                break
            except:
                pass
    return config

def get_prop(device, property_name, element_name):
    """
    indi_getprop コマンドを呼び出して値を取得する
    """
    full_prop = f"{device}.{property_name}.{element_name}"
    try:
        result = subprocess.check_output(
            ["indi_getprop", "-t", "1", full_prop],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        if "=" in result:
            return result.split("=", 1)[1].strip()
    except:
        return None
    return None

def get_gps_data(timeout=1.5):
    """
    gpspipe -w コマンドを呼び出して GPSD から TPV データを取得する
    """
    try:
        proc = subprocess.Popen(
            ["gpspipe", "-w"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        
        start_time = time.monotonic()
        tpv_data = None
        
        while time.monotonic() - start_time < timeout:
            r, _, _ = select.select([proc.stdout], [], [], 0.1)
            if proc.stdout in r:
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.strip())
                    if data.get("class") == "TPV":
                        tpv_data = data
                        break
                except ValueError:
                    pass
        
        proc.terminate()
        proc.wait(timeout=0.2)
        return tpv_data
    except Exception:
        return None

def get_local_timestamp(dt_utc, lat, lon):
    """
    経緯度から現地タイムゾーンを特定し、タイムゾーンオフセット付きの現地時間ISO 8601文字列を返す
    """
    try:
        tz_name = tf.timezone_at(lat=lat, lng=lon) or "Asia/Tokyo"
        tz_obj = pytz.timezone(tz_name)
        dt_local = dt_utc.astimezone(tz_obj)
        offset_str = dt_local.strftime('%z')
        offset_formatted = f"{offset_str[:3]}:{offset_str[3:]}"
        return dt_local.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + offset_formatted
    except Exception:
        try:
            tz_obj = pytz.timezone("Asia/Tokyo")
            dt_local = dt_utc.astimezone(tz_obj)
            return dt_local.strftime('%Y-%m-%dT%H:%M:%S.000+09:00')
        except Exception:
            return dt_utc.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')

def main():
    parser = argparse.ArgumentParser(description="ofs_link: Get telescope mount & GPS telemetry")
    parser.add_argument("--get", action="store_true", help="Get telemetry data in JSON format")
    parser.add_argument("--mock", action="store_true", help="Return mock data for testing")
    parser.add_argument("--config", type=str, help="Path to config.json file")
    parser.add_argument("--flashair", action="store_true", help="Check FlashAir connection status")
    
    args = parser.parse_args()
    
    if not args.get and not args.flashair:
        parser.print_help()
        sys.exit(1)
        
    if args.flashair:
        config = load_config(args.config)
        base_url = config.get("FLASHAIR_URL", "http://192.168.50.200")
        if args.mock:
            result = {
                "flashair": "CONNECTED",
                "url": base_url
            }
            print(json.dumps(result, indent=2))
            sys.exit(0)
        connected = check_flashair(base_url)
        result = {
            "flashair": "CONNECTED" if connected else "DISCONNECTED",
            "url": base_url
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)
        
    if args.mock:
        # モックデータを返却 (要求された項目をすべて含む)
        mock_data = {
            "indi_server": "CONNECTED",
            "status": "TRACKING",
            "ra_deg": 83.81020833,
            "dec_deg": -5.38966667,
            "ra_str": "05h35m14s",
            "dec_str": "-05°23'23\"",
            "side_of_pier": "EAST",
            "latitude": 34.6493,
            "longitude": 135.0015,
            "elevation": 54.0,
            "timestamp_utc": "2026-06-21T06:55:01.000Z",
            "iso_timestamp": "2026-06-21T15:55:01.000+09:00"
        }
        print(json.dumps(mock_data, indent=2))
        sys.exit(0)
        
    # 設定のロード
    config = load_config(args.config)
    mount_dev = config["INDI_MOUNT"]
    prop_coord = config["PROP_COORD"]
    prop_geo = config["PROP_GEO"]
    
    # --- 1. GPSD から位置情報・時間情報の取得 ---
    gps_tpv = get_gps_data()
    
    latitude = None
    longitude = None
    elevation = None
    dt_utc = None
    
    if gps_tpv:
        latitude = gps_tpv.get("lat")
        longitude = gps_tpv.get("lon")
        elevation = gps_tpv.get("altHAE") or gps_tpv.get("alt") or gps_tpv.get("altMSL")
        
        # GPSDからの時間情報のパース
        time_str = gps_tpv.get("time")
        if time_str:
            try:
                # 'Z' 終端をオフセット表現に置換してパース
                dt_utc = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            except:
                pass
 
    # GPSから位置情報が取得できない場合は設定ファイルのデフォルト値（前回値）にフォールバック
    if latitude is None or longitude is None:
        latitude = config.get("LAST_LATITUDE")
        longitude = config.get("LAST_LONGITUDE")
        
    if elevation is None:
        elevation = config.get("LAST_ELEVATION")
        
    # 時間情報が取得できない場合はシステム現在時間（UTC）を使用
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
        
    # 各種タイムスタンプ文字列の構築
    timestamp_utc = dt_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + "Z"
    iso_timestamp = get_local_timestamp(dt_utc, latitude, longitude)

    # --- 2. INDI サーバーからマウント情報の取得 ---
    connect_state = get_prop(mount_dev, "CONNECTION", "CONNECT")
    
    ra_raw = get_prop(mount_dev, prop_coord, "RA")
    dec_raw = get_prop(mount_dev, prop_coord, "DEC")
    
    is_connected = False
    if connect_state == "On":
        is_connected = True
    elif ra_raw is not None or dec_raw is not None:
        is_connected = True
        
    # 初期値
    indi_server = "DISCONNECTED"
    status = "UNKNOWN"
    ra_deg = None
    dec_deg = None
    pier_side = "UNKNOWN"
    
    if is_connected:
        indi_server = "CONNECTED"
        
        # ステータス (Busy, Ok, Idle, Alert)
        state_raw = get_prop(mount_dev, prop_coord, "STATE")
        if state_raw:
            state_upper = state_raw.upper()
            if state_upper == "OK":
                status = "TRACKING"
            elif state_upper == "BUSY":
                status = "SLEWING"
            elif state_upper == "IDLE":
                status = "IDLE"
            elif state_upper == "ALERT":
                status = "ALERT"
            else:
                status = state_upper
        else:
            status = "IDLE"
            
        # 座標の計算
        if ra_raw:
            ra_val = parse_sexagesimal(ra_raw)
            if ra_val is not None:
                ra_deg = round(ra_val * 15.0, 8)
                
        if dec_raw:
            dec_val = parse_sexagesimal(dec_raw)
            if dec_val is not None:
                dec_deg = round(dec_val, 8)
                
        # ピアーサイドの取得
        pier_side_raw = get_prop(mount_dev, "SIDE_OF_PIER", "PIER_SIDE") or \
                        get_prop(mount_dev, "TELESCOPE_PIER_SIDE", "PIER_SIDE")
                        
        if pier_side_raw:
            pier_side = pier_side_raw.upper()
            
        # ピアーサイドのフォールバック計算 (時角より推測)
        if pier_side == "UNKNOWN" or not pier_side:
            if longitude is not None and ra_raw:
                try:
                    ra_val = parse_sexagesimal(ra_raw)
                    if ra_val is not None:
                        lst_val = calc_lst(longitude, dt_utc)
                        if lst_val is not None:
                            ha_val = lst_val - ra_val
                            if ha_val > 12:
                                ha_val -= 24
                            if ha_val < -12:
                                ha_val += 24
                            pier_side = "EAST" if ha_val < 0 else "WEST"
                except:
                    pass

    # 結果データの組み立て
    result_data = {
        "indi_server": indi_server,
        "status": status,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "ra_str": format_ra(ra_deg),
        "dec_str": format_dec(dec_deg),
        "side_of_pier": pier_side,
        "latitude": round(latitude, 6) if latitude is not None else None,
        "longitude": round(longitude, 6) if longitude is not None else None,
        "elevation": round(elevation, 1) if elevation is not None else None,
        "timestamp_utc": timestamp_utc,
        "iso_timestamp": iso_timestamp
    }
    
    print(json.dumps(result_data, indent=2))

if __name__ == "__main__":
    main()
