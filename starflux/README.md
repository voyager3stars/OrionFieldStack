# StarFlux v1.2.0

**High-Precision Image Quality Analyzer & Statistics Integrator**

StarFluxは、撮影された天体画像から星を検出し、その形状（FWHM：半値幅、楕円率）を統計的に解析するツールです。OrionFieldStackプロジェクトの一環として、解析結果を `shutter_log.json` および `shutter_log.csv` に自動的に統合し、撮影データの品質管理を容易にします。

---

## 🛰 Installation & Setup

StarFluxは、画像の読み込みに `rawpy` や `astropy` を、星の検出に `photutils` を使用します。

### 1. 専用仮想環境(venv)の作成
システムのライブラリを引用しつつ、独立した実行環境を作成します。
```bash
cd OrionFieldStack/starflux
python3 -m venv --system-site-packages venv
source venv/bin/activate
```

### 2. 依存ライブラリの導入
```bash
pip install -r requirements.txt
```
**主な依存ライブラリ:** `rawpy`, `astropy`, `photutils`, `numpy`

---

## 🚀 Usage

### 1. 基本コマンド形式
ファイル単体、またはフォルダ内の全画像を対象に解析を実行できます。
```bash
python3 starflux.py [解析対象のファイルパス または フォルダパス] [オプション]
```

### 2. 実行例
```bash
# フォルダ内の全ての画像を解析し、ログを更新
python3 starflux.py ~/Pictures/M42_Project/

# 解析結果をヒストグラムで表示（ダッシュボード表示）
python3 starflux.py ~/Pictures/M42_Project/ --plot

# すでに解析済みの画像も強制的に再解析
python3 starflux.py ~/Pictures/M42_Project/ --force
```

---

## 🛠 Options

| オプション | 実行コマンド例 | 内容説明 |
| :--- | :--- | :--- |
| **グラフ表示** | `--plot` | 解析結果のFWHMと楕円率の分布をテキストベースのヒストグラムで表示します。 |
| **強制再解析** | `--force` | ログに記録がある画像でもスキップせずに再解析を実行します。 |
| **ログ更新無効** | `--no-log` | 画面表示のみを行い、`shutter_log`（JSON/CSV）への書き込みをスキップします。 |
| **検出数制限** | `--top-stars 300` | 解析対象とする明るい星の最大数を指定します（デフォルト: 300）。 |
| **SNRしきい値** | `--snr 5.0` | 星を検出するための信号対雑音比を指定します（デフォルト: 5.0）。 |

---

## 📊 ログ統合の仕組み

StarFluxは、解析対象と同じディレクトリにある `shutter_log.json` と `shutter_log.csv` を自動的に探し、以下の情報を追記します。

これにより、一晩の撮影を通して「どのタイミングでピントが甘くなったか」や「追尾精度が落ちたか」を一覧で確認することが可能になります。

### 1. JSON 形式 (`shutter_log.json`)

各レコードの `analysis` ブロックの中に `quality` オブジェクトが生成または更新されます。

```json
"analysis": {
    "quality": {
        "sf_stars": 300,            // 解析された星の数
        "sf_fwhm_mean": 2.54,       // FWHM 平均値
        "sf_fwhm_med": 2.50,        // FWHM 中央値
        "sf_fwhm_std": 0.32,        // FWHM 標準偏差 (σ)
        "sf_ell_mean": 0.12,        // 楕円率 平均値
        "sf_ell_med": 0.11,         // 楕円率 中央値
        "sf_ell_std": 0.04,         // 楕円率 標準偏差 (σ)
        "sf_status": "success",     // 解析ステータス
        "sf_timestamp": "2026...",  // 解析実行日時
        "sf_version": "1.2.0"       // StarFlux バージョン
    }
}
```

### 2. CSV 形式 (`shutter_log.csv`)

`SSE_Version` 列（AN列 / index 39）の直後、**AO列 (index 40) 以降**に以下の項目が追加されます。

| 列 (Index) | ヘッダー名 | 内容 |
| :--- | :--- | :--- |
| **AO (40)** | `sf_stars` | 解析された星の数 |
| **AP (41)** | `sf_fwhm_med` | FWHM 中央値 |
| **AQ (42)** | `sf_ell_med` | 楕円率 中央値 |
| **AR (43)** | `sf_status` | 解析ステータス |
| **AS (44)** | `sf_timestamp` | 解析実行日時 |
| **AT (45)** | `sf_version` | StarFlux バージョン |

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
