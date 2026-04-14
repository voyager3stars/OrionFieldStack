# StarForge v1.0.0

**High-Precision Astronomical Image Stacker & Register**

StarForgeは、`StarFlux` による画像品質解析の結果（楕円率など）を活用し、複数の天体画像を自動的に位置合わせ・スタッキングするツールです。高品質なマスター FITS ファイルの生成を目的としています。

---

## 🛰 Installation & Setup

StarForgeは、画像の幾何学的変換に `astroalign` を、データの操作に `astropy` と `numpy` を使用します。

### 1. 専用仮想環境(venv)の作成
```bash
cd OrionFieldStack/starforge
python3 -m venv --system-site-packages venv
source venv/bin/activate
```

### 2. 依存ライブラリの導入
```bash
pip install -r requirements.txt
```

---

## 🚀 Usage

### 1. 基本コマンド形式
`shutter_log.json` が存在するディレクトリを指定して実行します。
```bash
python3 starforge.py [画像とログが含まれるフォルダパス] [オプション]
```

### 2. 実行例
```bash
# 楕円率 0.2 以下の画像を自動選別してスタック（Sigma-Clip方式）
python3 starforge.py ~/Pictures_test/

# しきい値を厳しくして上位のみをスタック
python3 starforge.py ~/Pictures_test/ --threshold 0.12

# スタック手法を中央値 (Median) に指定し、出力名を変更
python3 starforge.py ~/Pictures_test/ --method median --out M42_master.fits
```

---

## 🛠 Options

| オプション | 実行コマンド例 | 内容説明 |
| :--- | :--- | :--- |
| **しきい値** | `--threshold 0.15` | スタック対象とする「楕円率」の最大値（デフォルト: 0.2）。 |
| **スタック手法** | `--method median` | `median`, `mean`, `sigma_clip` から選択（デフォルト: `sigma_clip`）。 |
| **出力名** | `--out master.fits` | 生成される FITS ファイルの名称。 |
| **枚数制限** | `--limit 50` | 指定した枚数に達したら処理を終了します。 |

---

## 📊 処理フローの詳細

1.  **基準フレームの自動選定**: `shutter_log.json` を読み込み、楕円率 (`sf_ell_med`) が最も低い画像を、位置合わせの基準（Reference）として自動的に選択します。
2.  **品質フィルタリング**: 指定された `--threshold` を超える楕円率を持つ画像は、スタック対象から自動的に除外されます。
3.  **レジストレーション (Registration)**: `astroalign` を使用し、各画像を基準フレームに合わせて回転・平行移動処理します。
4.  **スタッキング**: 全ての画像を重ね合わせ、ノイズ低減とS/N比向上を行います。
5.  **FITS出力**: 高精度な 32-bit (float32) FITS ファイルとして保存されます。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
