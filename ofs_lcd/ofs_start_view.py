#!/usr/bin/env python3
"""
ofs_start_view.py - シンプルなスタート画面表示
OrionFieldStack の文字と OrionFieldStack_white_s.png を指定秒数表示します。
使い方: python3 ofs_start_view.py [表示秒数(デフォルト:3)]
"""
import os
import sys
import time
from PIL import Image, ImageDraw, ImageFont

# ofs_lcd 内の st7789 を読み込めるようにパス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OFS_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..")) if os.path.basename(BASE_DIR) == "ofs_lcd" else BASE_DIR
sys.path.insert(0, os.path.join(OFS_ROOT, "ofs_lcd"))

try:
    from st7789 import ST7789
except ImportError:
    ST7789 = None

def get_font(size, bold=True):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def main():
    # 表示時間（秒）の取得（引数があればそれを使用、なければデフォルト3秒）
    duration = 3.0
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
        except ValueError:
            pass

    # 1. 画像の作成 (240x240)
    img = Image.new("RGB", (240, 240), color=(10, 14, 20))
    draw = ImageDraw.Draw(img)

    # 画面枠線
    draw.rectangle([(1, 1), (238, 238)], outline=(35, 48, 66), width=1)

    # タイトル "OrionFieldStack"
    font_title = get_font(19, bold=True)
    draw.text((16, 12), "OrionFieldStack", fill=(225, 228, 232), font=font_title)

    # バージョンタグ "v1.5.5"
    font_tag = get_font(10, bold=True)
    draw.rounded_rectangle([(180, 15), (224, 30)], radius=3, fill=(201, 160, 99))
    draw.text((184, 16), "v1.5.5", fill=(0, 0, 0), font=font_tag)

    # サブタイトル
    font_sub = get_font(10, bold=False)
    draw.text((120, 38), "Astrophotography Field Toolkit", fill=(201, 160, 99), font=font_sub, anchor="mm")
    draw.line([(24, 48), (216, 48)], fill=(45, 58, 78), width=1)

    # ロゴ画像 (OrionFieldStack_white_s.png)
    logo_path = os.path.join(OFS_ROOT, "images", "OrionFieldStack_white_s.png")
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo = logo.resize((140, 140), Image.Resampling.LANCZOS)
        img.paste(logo, (50, 52), logo)

    # ステータス "● SYSTEM READY"
    font_ready = get_font(11, bold=True)
    draw.ellipse([(66, 203), (74, 211)], fill=(0, 255, 136))
    draw.text((80, 207), "SYSTEM READY", fill=(0, 255, 136), font=font_ready, anchor="lm")

    # 2. LCDに表示
    if ST7789 is None:
        img.save(os.path.join(OFS_ROOT, "ofs_lcd", "preview_ofs_start.png"))
        print("[WARN] ST7789 driver not found, generated preview only.")
        return

    try:
        display = ST7789(width=240, height=240, rotation=2, bl_duty=100.0)
        display.display(img)
        time.sleep(duration)
        display.close()
    except Exception as e:
        print(f"[ERROR] LCD Display Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
