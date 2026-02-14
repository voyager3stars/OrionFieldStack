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

---

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