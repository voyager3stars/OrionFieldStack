# StarFlux v1.3.2

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
ファイル単体、またはフォルダ内の画像を対象に解析を実行できます。

```bash
python3 starflux.py <path> [オプション]
```

| 引数 | 説明 |
| :--- | :--- |
| `path` | 解析対象の**ファイルパス**または**フォルダパス**（必須） |

**対応ファイル形式:** `.dng`, `.raw`, `.fits`, `.fit`, `.fts`

- **ファイル指定時:** その1枚のみを解析します（`--session` は不要です）。
- **フォルダ指定時:** 上記拡張子を持つファイルを名前順にスキャンし、一括処理します。

### 2. 実行例
```bash
# フォルダ内の全画像を解析し、ログを更新
python3 starflux.py ~/Pictures/M42_Project/

# 特定セッションの画像だけ解析
python3 starflux.py ~/Pictures/M42_Project/ --session 20260321_2345

# 解析結果をヒストグラムで表示（ダッシュボード表示）
python3 starflux.py ~/Pictures/M42_Project/ --plot

# すでに解析済みの画像も強制的に再解析
python3 starflux.py ~/Pictures/M42_Project/ --force

# セッション絞り込み + 強制再解析 + ヒストグラム表示
python3 starflux.py ~/Pictures/M42_Project/ --session 20260321_2345 --force --plot

# カットアウトサイズを変更して解析
python3 starflux.py ~/Pictures/M42_Project/ --box-size 21

# ログを更新せずに画面表示のみ
python3 starflux.py ~/Pictures/M42_Project/ --plot --no-log
```

---

## 🛠 Options

| オプション | デフォルト | 内容説明 |
| :--- | :--- | :--- |
| `--force` | `OFF` | 同一バージョンで解析済み（`success` / `error`）の画像でもスキップせず再解析します。 |
| `--plot` | `OFF` | 解析結果のFWHMと楕円率の分布をテキストベースのヒストグラムで表示します。 |
| `--no-log` | `OFF` | 画面表示のみを行い、`shutter_log.json` および `shutter_log.csv` への書き込みをスキップします。 |
| `--top-stars <N>` | `300` | 検出された星をピーク輝度順にソートし、上位 N 個だけ品質解析の対象とします。 |
| `--snr <値>` | `5.0` | 星検出の閾値。画像のクリップ済み標準偏差 × SNR を DAOStarFinder の閾値に使用します。 |
| `--box-size <N>` | `15` | 各星の品質解析に使うカットアウト（切り出し）サイズ（ピクセル）。 |
| `--session <ID>` | なし | **フォルダ指定時のみ有効。** `shutter_log.json` の `session_id` が一致するファイルだけを処理対象にします。 |

### `--session` の挙動

1. 指定フォルダ内の `shutter_log.json` を読み込みます。
2. `session_id` が一致するレコードの `record.file.name` を収集します。
3. ディレクトリ内の画像ファイルのうち、収集したファイル名に一致するものだけを解析します。
4. 別セッションのファイルやログに記録のないファイルはスキップされます。
5. `shutter_log.json` が存在しない、または読み込みに失敗した場合は警告を表示し、フィルタなしで全画像を対象とします。

---

## 📋 処理の流れ

```
入力 (ファイル or フォルダ)
  → [--session] セッション絞り込み（フォルダ時）
  → 解析済みチェック（同一バージョン + success/error → スキップ、--force で解除）
  → 画像読み込み (DNG/RAW/FITS)
  → 星検出 (DAOStarFinder)
  → 上位 N 個の星で FWHM / 楕円率を統計算出
  → shutter_log.json / shutter_log.csv を更新（--no-log でスキップ）
  → [--plot] ヒストグラム表示
```

**コンソール出力の例:**
```text
StarFlux v1.3.2>> Scanning directory: ~/Pictures/M42_Project/
StarFlux v1.3.2>> Found 12 image(s) to analyze.
  [Skip] IMG_0001.dng already processed by v1.3.2
  [Processing] IMG_0002.dng...
StarFlux v1.3.2>> Finished. 11/12 files processed in 45.3s.
```

解析に失敗した場合（星未検出、読み込みエラー等）も、`--no-log` を指定していなければログに `error` ステータスを記録します。

---

## 📊 ログ統合の仕組み

StarFluxは、解析対象と同じディレクトリにある `shutter_log.json` と `shutter_log.csv` を自動的に探し、解析結果を追記します。書き込みは一時ファイル経由の原子操作（`os.replace`）で行い、処理中の電源断によるログ破損を防ぎます。

これにより、一晩の撮影を通して「どのタイミングでピントが甘くなったか」や「追尾精度が落ちたか」を一覧で確認することが可能になります。

### 1. JSON 形式 (`shutter_log.json`)

各レコードの `analysis` ブロック内に `SF` オブジェクトが生成または更新されます（OrionFieldStack JSON Spec v1.6.2 準拠）。

**成功時:**
```json
"analysis": {
    "SF": {
        "sf_version": "1.3.2",
        "sf_status": "success",
        "sf_timestamp": "2026-06-14T22:30:15",
        "quality": {
            "sf_stars": 300,
            "sf_fwhm_mean": 2.54,
            "sf_fwhm_med": 2.50,
            "sf_fwhm_std": 0.32,
            "sf_ell_mean": 0.12,
            "sf_ell_med": 0.11,
            "sf_ell_std": 0.04
        }
    }
}
```

**失敗時:**
```json
"analysis": {
    "SF": {
        "sf_version": "1.3.2",
        "sf_status": "error",
        "sf_timestamp": "2026-06-14T22:30:15",
        "sf_error": "No stars detected"
    }
}
```

> **Note:** v1.2 以前の `analysis.quality` 形式のログも、スキップ判定時にフォールバック参照されます。

### 2. CSV 形式 (`shutter_log.csv`)

SSE 関連列の後に、以下の StarFlux 列が追記されます（v1.6.2 マスターヘッダー準拠）。

| ヘッダー名 | 内容 |
| :--- | :--- |
| `SF_version` | StarFlux バージョン |
| `SF_status` | 解析ステータス（`success` / `error`） |
| `SF_timestamp` | 解析実行日時 |
| `SF_stars` | 解析された星の数 |
| `SF_fwhm_med` | FWHM 中央値 |
| `SF_fwhm_mean` | FWHM 平均値 |
| `SF_fwhm_std` | FWHM 標準偏差 (σ) |
| `SF_ell_med` | 楕円率 中央値 |
| `SF_ell_mean` | 楕円率 平均値 |
| `SF_ell_std` | 楕円率 標準偏差 (σ) |

旧フォーマットの CSV（レガシー列名）を読み込んだ場合も、書き込み時に v1.6.2 ヘッダーへ自動変換されます。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
