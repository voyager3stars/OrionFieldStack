**ShutterPro03 (v12.5)**
Wireless Shutter Control & Observation Data Integrator for Raspberry Pi

**🛰 Overview**
ShutterPro03 is an advanced astronomical photography control tool designed to bring modern automation to almost any camera.

Even for cameras that do not support shutter control or data transfer via USB (such as older DSLRs or entry-level models), shutter03 bridges the gap. By combining a physical relay/optocoupler circuit for shutter triggering with a Toshiba FlashAir wireless SD card, it enables a fully automated, wireless workflow across a vast range of camera models.

It doesn't just trigger the shutter; it acts as a central data integrator. The tool fetches real-time telescope coordinates (RA/DEC) and environmental data (Temperature/Humidity) from an INDI server at the exact moment of exposure, consolidating everything into a comprehensive CSV log for precise post-observation analysis.

**✨ Key Features**
Wireless Workflow: No USB cables needed for image transfer (via FlashAir).

INDI Integration: Automatically records RA/DEC, Latitude/Longitude, and weather data (Temperature, Humidity, Pressure) from your mount or sensors.

Exif Analysis: Extracts ISO, Exposure time, and GPS data directly from captured images to calculate the "Exposure Difference" between requested and actual time.

Flexible Modes: Supports both camera (trigger pulse) and bulb (long exposure) modes.

Execution Modes: Choose from full, simple, or off display verbosity for field use.

**🛠 Hardware Requirements**
Raspberry Pi (Any model with GPIO)
Optocoupler/Relay Circuit connected to GPIO 27 (Default) for shutter triggering.
DSLR/Mirrorless Camera with a remote shutter port.
Toshiba FlashAir Card (W-04 recommended) for wireless data transfer.
INDI Server (OnStep, etc.) for mount and sensor data.

* Raspberry Pi (Any model with GPIO)
* Optocoupler/Relay Circuit connected to GPIO 27 (Default) for shutter triggering.
* DSLR/Mirrorless Camera with a remote shutter port.
* Toshiba FlashAir Card (W-04 recommended) for wireless data transfer.
* INDI Server (OnStep, Sky-Watcher, Vixen, etc.) for mount and sensor data.

> [!IMPORTANT]
> **⚠️ Configuration for Non-OnStep Users**
> This tool is designed to work with any INDI-compatible mount. If you are not using **OnStep**, please open `shutter03v12_5.py` and modify the `CONFIG` section to match your device names:
> ```python
> "INDI_DEVICE": "Your Device Name", # e.g., "SkyWatcher HEQ5"
> ```
> You can find your device and property names by running `indi_getprop` in your terminal.

**🚀 Quick Start**
**1.Clone the repository:**
Bash
git clone https://github.com/voyager3stars/OrionFieldStack.git
cd OrionFieldStack/shutter03

**2.Setup Virtual Environment:**
Bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install requests exifread gpiozero lgpio

**3.Run:**
Bash
# Example: 30 shots, 60s bulb exposure, simple output
python3 shutter03v12_5.py 30 bulb 60 simple

**📊 Log Data (shutter_log.csv)**
The tool generates a detailed CSV including:

Timestamps: UTC and JST.
Camera Data: Filename, Format, ISO, Exposure, Resolution.
Telescope Data: RA, DEC, Altitude (from INDI).
Environment: Temperature, Humidity, Pressure, Dew Point, CPU Temp.
Accuracy: Difference between shutter ON time and Exif reported exposure.

**⚖️ License**
This project is licensed under the MIT License.

日本語説明
shutter03 は、Raspberry Pi を使用した天体撮影制御ツールです。 USB接続によるシャッター制御やデータ送信に対応していないカメラにおいても、リレー（フォトカプラ）回路による物理的なシャッター制御と、FlashAir を組み合わせることで、幅広い機種での自動撮影とデータ管理を可能にします。 カメラ本体に依存せず、撮影セッションの画像データと INDI サーバーからの天体・気象データを同期させ、一つの CSV ファイルに統合。ケーブルを最小限に抑えたい遠征撮影や、緻密なデータ解析を行う天文ファンに最適です。