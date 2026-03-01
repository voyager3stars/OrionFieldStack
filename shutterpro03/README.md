cat << 'EOF' > README.md
# ShutterPro03

**Precision Shutter Control & Telemetry Integrator**

ShutterPro03は、リレー回路によるシャッター制御とFlashAirを使ったデータ通信、INDI連携を統合し、USB制御に対応しないカメラでも高度な自動撮影を実現するツールです。OrionFieldStackプロジェクトの一環として、標準化された撮影ログを出力します。

---

## 🛰 Installation & Setup

OrionFieldStackリポジトリには、天体観測を支援する複数のツール（gpssetup, skysync等）が含まれています。ShutterPro03を使用するには、以下の手順で専用の環境を構築してください。

### 1. リポジトリの取得と移動
まずはリポジトリ全体をクローンし、本ツールのディレクトリへ移動します。
```bash
git clone https://github.com/voyager3stars/OrionFieldStack.git
cd OrionFieldStack/shutterpro03
```

### 2. 専用仮想環境(venv)の作成
システムのライブラリ（RPi.GPIO等）を引用しつつ、ShutterPro03専用の独立した実行環境を作成します。
```bash
# 仮想環境の作成（システムパッケージを引用）
python3 -m venv --system-site-packages venv

# 仮想環境の有効化
# (有効になるとプロンプトの先頭に (venv) と表示されます)
source venv/bin/activate
```

### 3. 依存ライブラリの導入
仮想環境内で、必要なライブラリ（exifread, pyindi-client）を一括インストールします。
```bash
pip install -r requirements.txt
```
## 📂 Directory & File Structure

```text
~ (Home Directory)
├── OrionFieldStack/        # 【プログラム層】
│   ├── README.md
│   ├── requirement.txt     # 必要な依存ライブラリのリスト
│   ├── config.json         # 全体設定（接続先・パス・デフォルト値）
│   ├── shutterpro03.py     # メイン制御（エントリーポイント）
│   ├── sp03_utils.py       # 共通ユーティリティ（時間計算、パス変換等）
│   ├── sp03_logger.py      # ログ生成エンジン
│   ├── sp03_manual.md      # 詳細取扱説明書
│   └── OFS_json_spec.md    # ログファイルの仕様書
│
└── Pictures/               # 【データ層】
    ├── IMG_XXXX.dng        # 撮影された生画像
    ├── latest_shot.json    # ツール間連携用リアルタイムバッファ
    ├── shutter_log.json    # 累積詳細ログ (JSON)
    └── shutter_log.csv     # 閲覧用累積ログ (CSV)
```
---

## 📊 配線図

```text
[ Raspberry Pi ]          [ PC817 Photocoupler ]         [ Camera ]
                         +---------------+
  GPIO 18 >---[ 220Ω ]---| 1 (Anode)   4 |--------------> Shutter (Tip)
                         |    (LED) (Tr) | 
  GND     >--------------| 2 (Cath)    3 |--------------> Common (Sleeve)
                         +---------------+
                                 ^
                           (ここが絶縁境界)
```
### ⚡ 抵抗値の計算
LEDの順方向電圧を $V_f = 1.2V$、RPiの出力を $V_{cc} = 3.3V$、流したい電流を $I = 10mA$ とすると、必要な抵抗 $R$ は以下の式で求められます。

$$
R = \frac{V_{cc} - V_f}{I} = \frac{3.3 - 1.2}{0.01} = 210 \Omega
$$

よって、入手しやすい **220Ω** の抵抗を使用します。

## 🛠️ ShutterPro03 構成コンポーネントの役割
### 1. shutterpro03.py (Main Controller)
システムの司令塔です。ユーザーからのCLI引数を解釈し、GPIOによる物理シャッター制御と、撮影瞬間のINDIテレメトリ取得を同期させます。

### 2. sp03_utils.py (Utilities)
計算やシステム操作を抽象化したモジュールです。

* Time Conversion: 天文計算に必要な時刻形式への変換。

* Path Resolver: ~/Pictures などのチルダを含むパスを絶対パスへ安全に展開。

* Device Checker: GPIO やカメラ、INDI接続の状態確認。

### 3. sp03_logger.py (Data Architect)
「データの信頼性」を担保する最重要モジュールです。

* JSON Spec v1.3.2: 撮影データ、マウント座標、機材情報を統合し、厳格なスキーマで  shutter_log.json を生成します。

* Auto-Recovery: 書き込み中の電源断などでログが破損するのを防ぐ安全なファイル操作を担当。

## 🚀 Usage

### 設定の確認
撮影前に、現在の \`config.json\` の設定内容が正しく読み込まれているか確認します。
```bash
python3 shutterpro03.py -h
```

### 撮影の実行
```bash
# 例：10枚、バルブ、60秒、対象M42
python3 shutterpro03.py 10 bulb 60 obj=M42
```

---

## 📖 Detailed Documentation
* **[User Manual (sp03_manual.md)](./sp03_manual.md)**: 全設定項目の詳細、エイリアス、Impact（役割）の解説。
* **[Data Spec (OFS_json_spec.md)](./OFS_json_spec.md)**: 出力されるJSONログの技術仕様。

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
EOF