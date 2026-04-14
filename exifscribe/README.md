# ExifScribe v1.6.0

**DNG EXIFメタデータ統合・同期ツール**

ExifScribeは、撮影されたDNGファイルからEXIF情報を抽出し、`shutter_log.json` の該当レコードを補完または更新するためのツールです。OrionFieldStack v1.6.0 仕様に準拠し、記録漏れや情報の不一致を効率的に解消します。

---

## 🚀 概要

カメラが記録した本来のメタデータ（ISO、露出時間、GPS、解像度等）を、撮影ログ（JSON）に後付けで統合します。「ShutterPro03で記録し忘れた」「SSEの解析前に正確な露出時間を入れたい」といった場合に最適です。

- **スマートマッチング**: 大文字・小文字を区別せず、ファイル名に基づいてJSONレコードを自動特定します。
- **データ保護**: `record.exif` および `record.file` セクションのみを対象とし、SSEやStarFluxの解析結果（analysis）には一切干渉しません。

---

## 🛠 Features

1. **柔軟なマッチング**: `IMGP1234.DNG` ↔ `imgp1234.dng` のような表記揺れを許容します。
2. **多項目抽出**: ISO感度、露出時間、撮影日時、カメラモデル、GPS座標、画像サイズ、ファイルサイズを網羅。
3. **対話型解決**:
   - **新規追加**: JSONにないDNGが見つかった場合、新規レコードとして追加するか選択。
   - **不一致解消**: EXIFとJSONの値が異なる場合、上書きするか保持するかを選択。
   - **欠落確認**: JSONにあるがDNGファイルが見当たらないレコードの削除を選択。
4. **セッションバックアップ**: 処理実行前に `backups/` フォルダへ現在のJSONを退避します。
5. **ドライランモード**: `--dry-run` を指定することで、実際の変更を伴わずに処理内容をプレビューできます。

---

## 🛰 Installation

実行には `exifread` ライブラリが必要です。

```bash
pip install exifread
```

---

## 🚀 Usage

### 1. 基本コマンド形式

```bash
python3 exifscribe.py [DNGディレクトリ] [オプション]
```

### 2. 実行例

```bash
# カレントディレクトリのDNGをスキャンしてJSONを更新
python3 exifscribe.py

# 特定のプロジェクトフォルダのDNGをスキャン
python3 exifscribe.py ~/Pictures/Orion_Project/

# すでに値が入っているフィールドも強制的にEXIFで上書き
python3 exifscribe.py --force

# プレビューのみ実行（ファイル書き込みなし）
python3 exifscribe.py --dry-run
```

---

## 🛠 Options

| オプション | 内容説明 |
| :--- | :--- |
| `dir` | DNGファイルが存在するディレクトリ（デフォルト: カレントディレクトリ）。 |
| `--json PATH` | 対象とする `shutter_log.json` のパスを指定します。 |
| `--force` | すでに値が存在する項目も、EXIFデータで強制的に再処理します。 |
| `--dry-run` | 変更内容の表示のみを行い、JSONファイルへの保存をスキップします。 |
| `--ext EXT` | 対象とする拡張子を指定します（デフォルト: `.dng`）。 |
| `--backup PATH` | バックアップディレクトリの保存先を指定します。 |

---

## 📊 抽出・統合される項目

| JSONキー | 内容 |
| :--- | :--- |
| `record.exif.iso` | ISO感度 |
| `record.exif.shutter_sec` | 露出時間（秒） |
| `record.exif.datetime_original` | 撮影日時（Original） |
| `record.exif.model` | カメラモデル名 |
| `record.exif.lat / lon / alt` | GPS座標（緯度・経度・高度） |
| `record.file.width / height` | 画像解像度 |
| `record.file.size_mb` | ファイルサイズ（MB） |

---

## 🛡 Backup System

同期処理が開始されると、`backups/` 以下に `YYMMDDHHMM_exifscribe` 形式のディレクトリが作成され、処理前の JSON がコピーされます。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
