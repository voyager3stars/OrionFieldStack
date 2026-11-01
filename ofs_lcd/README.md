# Raspberry Pi 5 + AE-ATM0130B3 (ST7789V2) 液晶制御

Raspberry Pi 5 上で、秋月電子通商の1.3インチIPSカラー液晶モジュールキット **「AE-ATM0130B3（ST7789V2 / 240×240）」** を高速・安全に制御するためのPythonプログラムです。

外部の重いフレームワーク（CircuitPython Blinka等）を使わず、Raspberry Pi 5 標準の **`spidev`**、**`gpiod` (RP1直接制御)**、**`Pillow`**、**`numpy`** だけで構築されているため、軽量かつ他の用途で使用中のピンに一切干渉しません。

---

## 1. 配線仕様 (Wiring)

Raspberry Pi 5 の 40ピンヘッダーと AE-ATM0130B3 の配線図です。

| Raspberry Pi 5 物理ピン | BCM GPIO 番号 | AE-ATM0130B3 ピン | 信号名 | 機能 / 説明 |
| :--- | :--- | :--- | :--- | :--- |
| **Pin 1** | - | **Pin 1 (VDD)** | 3.3V | メイン電源 |
| **Pin 17** | - | **Pin 2 (VDDIO)** | 3.3V | ロジック電源 |
| **Pin 6** | - | **Pin 3 (GND)** | GND | グランド |
| **Pin 23** | **GPIO11** | **Pin 4 (SCK)** | SPI0_SCLK | SPIクロック |
| **Pin 19** | **GPIO10** | **Pin 5 (MOSI)** | SPI0_MOSI | SPIデータ送信 |
| **Pin 24** | **GPIO8** | **Pin 6 (/CS)** | SPI0_CE0 | チップセレクト |
| **Pin 22** | **GPIO25** | **Pin 7 (D/C)** | データ/コマンド切替 | Low=コマンド, High=データ |
| **Pin 18** | **GPIO24** | **Pin 8 (/RES)** | リセット | Lowでハードウェアリセット |
| **Pin 16** | **GPIO23** | **(2N7000 Gate → BL)** | バックライト PWM | 保護抵抗(100Ω)・プルダウン抵抗(10kΩ)・2N7000を介したDUTY調光 |

### 【重要】他用途ピンへの干渉防止設計とバックライト駆動回路
* **`/RES` に Pin 18 (BCM GPIO24) を採用**:
  * 物理 Pin 18（GPIO24）を制御対象とし、PPS時刻同期等で使用中の BCM GPIO18（物理 Pin 12）には一切触れないよう厳密にBCM番号24を指定しています。
* **`BL` に Pin 16 (BCM GPIO23) + 2N7000（Nch MOSFET）を採用（バックライトPWM調光）**:
  * Pin 16 (GPIO23) から回路保護抵抗（**100Ω**）およびプルダウン抵抗（**10kΩ**、GND間）を介して **2N7000** のゲートを駆動し、起動時やHi-Z状態での意図しない点灯や過電流を防止しています。`lgpio` のハードウェア支援PWMにより0%〜100%のDUTY比で滑らかな輝度調整が可能です。
* **SPI0の最小専有 (`spi0-1cs,no_miso`)**:
  * 通常のSPI有効化では未使用の MISO (GPIO9) や CE1 (GPIO7) も予約されてしまいますが、本設定では **GPIO8, 10, 11 の3本のみ** を専有し、他のピンを一切専有・初期化しません。

---

## 2. 事前準備 (Raspberry Pi 5 設定)

### 2.1 `/boot/firmware/config.txt` の設定
SPI0 を必要最小限のピン（1CS、MISO解放）で有効化します。

`/boot/firmware/config.txt` の末尾に以下を追記します（設定済み）：
```ini
dtparam=spi=on
dtoverlay=spi0-1cs,no_miso
```

### 2.2 必要なパッケージの確認
Raspberry Pi OS (Bookworm / 64-bit) では標準で導入されています。
```bash
sudo apt update
sudo apt install -y python3-spidev python3-libgpiod python3-pil python3-numpy
```

---

## 3. ファイル構成

```text
ofs_lcd/
├── ofs_start_view.py       # OrionFieldStack 起動画面（スプラッシュロゴ）表示スクリプト
├── ofs_status_view.py      # OrionFieldStack リアルタイムテレメトリ・通信状況表示 (Web風デザイン)
├── st7789.py               # ST7789V2 液晶ディスプレイドライバ (SPI/gpiod/lgpio/NumPy)
├── set_bl.py               # バックライトPWM調光デーモン制御スクリプト
└── README.md               # 本ドキュメント
```

---

## 4. 使い方

### 4.1 リアルタイム通信情報表示 (`ofs_status_view.py`)
Web版 OrionFieldStack のダッシュボードデザインに準拠し、液晶画面に以下の5つのテレメトリ状況をリアルタイム表示します：
* **INDI STATUS**: Server（ONLINE/OFFLINE）、Mount（TRACKING/IDLE/SLEWING等）
* **TIME**: Local時刻（JST等）、UTC時刻、Time Source（GPSD / OS）
* **GPS**: 緯度 (Lat)、経度 (Lon)、標高 (Elev)、GPSD接続状況 (ACTIVE/OFFLINE)
* **ENVIRONMENT**: 気温 (Temp)、湿度 (Humid)、気圧 (Press)、露点 (Dew P)、CPU温度 (Mount / RPi)、子午線ピアー側 (Pier)
* **FLASH AIR**: 接続状態 (ACTIVE/OFFLINE)、ホストIP、リンク状況

```bash
# リアルタイム表示 (1秒周期更新、上下反転 rotation=2、明るさ100%)
python3 ofs_status_view.py

# 明るさ 80%、更新周期 2秒で起動
python3 ofs_status_view.py --brightness 80 --interval 2.0

# モックデータでのシミュレーション実行
python3 ofs_status_view.py --mock

# プレビュー画像のみ生成 (ハードウェア未接続でも確認可能)
python3 ofs_status_view.py --preview-only
```
* **終了方法**: コンソールで `q` または `Enter`（あるいは `Ctrl+C`）を押すと、画面をクリア・バックライトを消灯して安全に終了します。

### 4.2 基本実行 (OrionFieldStack 起動画面の表示と常駐)
標準設定（上下反転: rotation=2、明るさ100%）で OrionFieldStack の起動画面を表示し、表示を継続します。
```bash
python3 ofs_lcd.py
```
* **表示の継続**: 起動すると画面が表示され続け、コンソールで終了キーを押すまで待機します。
* **終了方法**: コンソールで **`q`** キー または **`Enter`**（あるいは `Ctrl+C`）を押すと、画面が黒でクリアされ、バックライトが完全に消灯して安全に終了します。
* 実行時、同時に作業ディレクトリに最新の画面プレビュー画像 `preview_ofs_lcd.png` が生成されます。

### 4.2 プレビューのみの生成 (--preview-only)
ハードウェア（SPI/GPIO）を制御せずに、画面プレビュー画像のみを保存・確認したい場合に便利です。
```bash
python3 ofs_lcd.py --preview-only
```

### 4.3 画面の回転（上下反転など）
ハードウェアの MADCTL レジスタにより、画面の向きを90度単位で回転できます。
```bash
# 180度回転（上下反転 / デフォルト）
python3 ofs_lcd.py --rotation 2

# 0度（標準）
python3 ofs_lcd.py --rotation 0

# 90度回転（時計回り）
python3 ofs_lcd.py --rotation 1

# 270度回転
python3 ofs_lcd.py --rotation 3
```

### 4.4 バックライトの調光
```bash
# 明るさ 80% で起動
python3 ofs_lcd.py --brightness 80

# バックライト単体での調光設定 (常駐デーモン)
python3 set_bl.py 50
```

### 4.5 バックライト調光テスト
段階的調光（100%→75%→50%→25%→10%→5%→100%）および滑らかなフェードイン・フェードアウトのブリージングアニメーションをテストできます。
```bash
python3 test_backlight.py
```

### 4.6 コマンドラインオプション一覧 (`ofs_lcd.py`)
| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `--rotation {0,1,2,3}` | `2` | 画面の回転向き（0: 0°, 1: 90°, 2: 180°上下反転, 3: 270°） |
| `--brightness FLOAT` | `100.0` | バックライト明るさ（DUTY比 0.0〜100.0%） |
| `--preview-only` | オフ | SPIハードウェアを操作せず、プレビュー画像の保存のみ行う |
| `--output FILE` | `preview_ofs_lcd.png` | プレビュー画像の保存先ファイル名 |
| `--x-offset INT` | `None (自動)` | X軸（列）オフセット調整（通常は自動計算） |
| `--y-offset INT` | `None (自動)` | Y軸（行）オフセット調整（Rotation 2 では自動的に 80px 補正） |
| `--no-invert` | オフ (反転有効) | IPSパネル用色反転（INVON）を無効化する場合に指定 |

---

## 5. 自作プログラムへの組み込み方法

ご自身のスクリプトから液晶を利用する場合は、`st7789.py` をインポートし、Pillow (PIL) で画像を作成して `display.display(img)` に渡すだけで簡単に描画できます。

### 5.1 基本フロー (3ステップ)

1. **初期化**: `ST7789` クラスをインスタンス化（`with` 構文で自動リソース解放）
2. **描画**: 240×240 の画像バッファ（`Image.new`）を作成し、`ImageDraw.Draw` で文字や図形を描画
3. **転送**: `display.display(img)` で液晶へ一括送信

```python
from PIL import Image, ImageDraw, ImageFont
from st7789 import ST7789

# 1. ディスプレイの初期化（rotation=2 で上下反転/180度）
with ST7789(rotation=2) as display:
    # 2. 240x240 のキャンバスを作成 (背景色: スレートネイビー)
    img = Image.new("RGB", (240, 240), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    # 3. 図形やテキストを描画
    draw.rectangle([(10, 10), (230, 230)], outline=(56, 189, 248), width=2)
    draw.text((120, 120), "Hello ATM0130!", fill=(255, 255, 255), anchor="mm")

    # 4. 液晶へ送信
    display.display(img)
```

---

### 5.2 各種描画コマンドのリファレンス (ImageDraw)

Pillow の `ImageDraw` モジュールを使った代表的な描画コマンドです。

#### ① テキスト・文字列の描画 (`draw.text`)
TrueType フォント（`.ttf`）を読み込むことで、美しい任意のフォント・サイズで日本語や英数字を描画できます。
`anchor="mm"` を指定すると、指定した座標がテキストの幾何学的中心（Middle-Middle）になり、中央揃えが極めて簡単に行えます。

```python
# フォントの読み込み (太字・サイズ指定)
font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)

# 左上基準 (x=20, y=30) で描画
draw.text((20, 30), "Status: Running", fill=(148, 163, 184), font=font_small)

# 画面中央 (x=120, y=100) にテキストの中心を合わせて描画 (anchor="mm")
draw.text((120, 100), "24.5 °C", fill=(0, 240, 255), font=font_large, anchor="mm")
```

#### ② 四角形・カードUIの描画 (`draw.rectangle` / `draw.rounded_rectangle`)
枠線のみ、塗りつぶし、角丸四角形（ボタンやカード）を直感的に配置できます。

```python
# 枠線のみの四角形 (左上座標, 右下座標)
draw.rectangle([(5, 5), (235, 235)], outline=(59, 130, 246), width=2)

# 塗りつぶしの四角形
draw.rectangle([(20, 50), (100, 90)], fill=(30, 41, 59))

# 角丸四角形 (radius で角の丸みを指定) - カードやボタンのUIに最適
draw.rounded_rectangle(
    [(20, 140), (220, 200)],
    radius=8,
    fill=(30, 41, 59),
    outline=(71, 85, 105),
    width=1
)
```

#### ③ 円・楕円・円弧の描画 (`draw.ellipse` / `draw.arc`)
円形ゲージ、インジケータランプ（LED表示）、ダイヤルなどの描画に使用します。

```python
# 塗りつぶしの円 (ステータスLED風: 緑ランプ)
# 外接する矩形 [(x0, y0), (x1, y1)] を指定
draw.ellipse([(20, 20), (36, 36)], fill=(34, 197, 94))

# 円の枠線のみ (メーターの外枠など)
draw.ellipse([(60, 60), (180, 180)], outline=(59, 130, 246), width=3)

# 円弧 (ゲージやプログレスリング)
# start と end は角度（度単位、3時方向が0度で時計回り）
draw.arc([(60, 60), (180, 180)], start=135, end=405, fill=(100, 116, 139), width=6)
```

#### ④ 直線・折れ線グラフの描画 (`draw.line`)
セパレーター（区切り線）や、センサー値の推移グラフを描くのに最適です。

```python
# 水平の区切り線
draw.line([(20, 45), (220, 45)], fill=(51, 65, 85), width=1)

# 折れ線グラフ (複数の (x, y) 座標タプルのリストを結ぶ)
trend_data = [(20, 180), (60, 150), (100, 160), (140, 120), (180, 135), (220, 95)]
draw.line(trend_data, fill=(244, 63, 94), width=2)
```

#### ⑤ 多角形・矢印の描画 (`draw.polygon`)
三角形や矢印アイコンを描くことができます。

```python
# 上向き矢印（三角形アイコン）
draw.polygon([(120, 10), (108, 26), (132, 26)], fill=(52, 211, 153))

# 下向き矢印
draw.polygon([(120, 230), (108, 214), (132, 214)], fill=(244, 63, 94))
```

#### ⑥ 外部画像・アイコンの貼り付け (`img.paste`)
PNG画像やアイコン、イラストをキャンバス上に合成できます（透過PNG対応）。

```python
# アイコン画像を読み込んでリサイズ
icon = Image.open("icon.png").convert("RGBA").resize((32, 32))

# 指定した座標に貼り付け（第3引数に icon を渡すことで透明度が正しく適用されます）
img.paste(icon, (20, 20), icon)
```

---

### 5.3 実践例：リアルタイム・ダッシュボード (定期更新ループ)

センサー値やシステム負荷を定期的に更新して表示する典型的なメインループのコード例です。

```python
import time
from PIL import Image, ImageDraw, ImageFont
from st7789 import ST7789

# フォントの初期化
font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
font_val   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
font_unit  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)

# ディスプレイ起動（上下反転: rotation=2）
with ST7789(rotation=2) as display:
    count = 0
    try:
        while True:
            # 1. フレームごとに背景を作成
            img = Image.new("RGB", (240, 240), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)

            # 2. タイトルヘッダー
            draw.text((120, 24), "DEVICE MONITOR", fill=(148, 163, 184), font=font_title, anchor="mm")
            draw.line([(20, 42), (220, 42)], fill=(51, 65, 85), width=1)

            # 3. メインの測定値表示
            draw.text((120, 100), f"{count:04d}", fill=(0, 240, 255), font=font_val, anchor="mm")
            draw.text((120, 135), "COUNTS / SEC", fill=(100, 116, 139), font=font_unit, anchor="mm")

            # 4. プログレスバー (ゲージ)
            progress = (count % 100) / 100.0
            draw.rounded_rectangle([(20, 175), (220, 190)], radius=4, fill=(30, 41, 59))
            bar_w = int(progress * 200)
            if bar_w > 0:
                draw.rounded_rectangle([(20, 175), (20 + bar_w, 190)], radius=4, fill=(59, 130, 246))

            # 5. ステータスLEDインジケータ
            draw.ellipse([(20, 210), (32, 222)], fill=(34, 197, 94))
            draw.text((40, 216), "SYSTEM NORMAL", fill=(148, 163, 184), font=font_unit, anchor="lm")

            # 6. 液晶へ一括転送
            display.display(img)

            count += 1
            time.sleep(0.1)  # 約 10 FPS で更新
    except KeyboardInterrupt:
        # Ctrl+C で画面を黒で消灯して終了
        display.clear((0, 0, 0))
```

---

### 5.4 ST7789 クラスのコンストラクタ引数

`ST7789` クラスを初期化する際に指定できる主なオプションです。

| 引数名 | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `width` | `240` | ディスプレイの解像度（幅） |
| `height` | `240` | ディスプレイの解像度（高さ） |
| `rotation` | `0` | 画面の向き（`0`: 通常, `1`: 90°, `2`: 180°上下反転, `3`: 270°） |
| `spi_speed_hz` | `24_000_000` | SPI通信速度（24MHz。安定かつ高速な描画が可能） |
| `pin_dc` | `25` | データ/コマンド切替ピン（BCM GPIO25 / 物理 Pin 22） |
| `pin_res` | `24` | リセットピン（BCM GPIO24 / 物理 Pin 18） |
| `pin_bl` | `23` | バックライトPWM調光ピン（BCM GPIO23 / 物理 Pin 16。Noneで無効化） |
| `bl_duty` | `100.0` | バックライト初期明るさ（DUTY比 0.0〜100.0%） |
| `bl_freq` | `1000` | バックライトPWM周波数（1000Hz） |
| `invert_colors` | `True` | IPSパネル用色反転（`True` で正常な色合いになります） |
| `x_offset` | `0` | X座標オフセット（パネル個体差によるズレ補正用） |
| `y_offset` | `0` | Y座標オフセット（80pxの表示ズレがある場合は `80` を指定） |

#### バックライト明るさの動的変更 (`display.set_backlight`)
プログラム実行中、いつでも明るさを動的に変更できます。
```python
# 明るさを 50% に変更
display.set_backlight(50.0)

# フェードアウト（徐々に暗くする）
for d in range(100, -1, -5):
    display.set_backlight(d)
    time.sleep(0.02)
```

---

## 6. 技術仕様・実装のポイント

* **Raspberry Pi 5 RP1 チップ最適化**:
  * RPi5 の GPIO コントローラである `gpiochip15`（pinctrl-rp1）を直接リクエストするため、従来の `RPi.GPIO` のような警告や非互換性がありません。
* **NumPy による超高速 RGB565 変換**:
  * Pillow (RGB888) の240×240ピクセル配列を、NumPyのベクトル演算で瞬時に 16-bit RGB565 (Big-Endian) に一括変換します（Pythonループと比較して数十倍高速）。
* **SPI バッファチャンク送信**:
  * Linux の `spidev` 転送制限（通常 4096 バイト）に合わせてデータを自動分割して連続送信するため、転送エラーが発生しません。

# フェードアウト（徐々に暗くする）
for d in range(100, -1, -5):
    display.set_backlight(d)
    time.sleep(0.02)
```

---

## 6. 技術仕様・実装のポイント

* **Raspberry Pi 5 RP1 チップ最適化**:
  * RPi5 の GPIO コントローラである `gpiochip15`（pinctrl-rp1）を直接リクエストするため、従来の `RPi.GPIO` のような警告や非互換性がありません。
* **NumPy による超高速 RGB565 変換**:
  * Pillow (RGB888) の240×240ピクセル配列を、NumPyのベクトル演算で瞬時に 16-bit RGB565 (Big-Endian) に一括変換します（Pythonループと比較して数十倍高速）。
* **SPI バッファチャンク送信**:
  * Linux の `spidev` 転送制限（通常 4096 バイト）に合わせてデータを自動分割して連続送信するため、転送エラーが発生しません。
