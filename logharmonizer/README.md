# LogHarmonizer v1.6.0

**OrionFieldStack ログデータ整合性管理・双方向同期ツール**

LogHarmonizerは、天体撮影ログのマスターデータである `shutter_log.json` と、編集・閲覧用の `shutter_log.csv` の間でデータの整合性を保ち、双方向に同期するためのツールです。OrionFieldStack JSON Spec v1.6.0 に完全準拠しており、ShutterPro03、SkySolverEngine (SSE)、StarFlux によって生成されたデータの管理を容易にします。

---

## 🚀 概要

天体撮影の現場では、JSON形式による詳細なメタデータ保持と、表計算ソフトでの一括編集や統計分析が可能なCSV形式の両方が必要になります。LogHarmonizerは、これら2つのファイルの「橋渡し」を行い、データの欠落や矛盾を防ぎます。

- **CSV to JSON (c2j)**: CSVでの手動編集内容を、マスターとなるJSONへ安全に書き戻します。
- **JSON to CSV (j2c)**: 最新のJSONログをCSV形式にエクスポートし、表計算ソフトでの確認を可能にします。

---

## 🛠 Features

1. **OrionFieldStack v1.6.0 準拠**: 最新の階層構造化されたJSONスキーマに対応しています。
2. **安全なバックアップ**: 同期処理を実行する直前に、既存のログファイルを `backups/` フォルダへ自動退避します。
3. **対話型コンフリクト解消**: 新規レコードの追加や既存レコードの削除を、一つずつ確認しながら実行できます。
4. **高精度データ保持**: 座標や露出時間など、項目ごとに最適な小数点精度（Precision）を維持して同期します。
5. **Latest Shot 連携**: 処理後の最新レコードを `latest_shot.json` として出力し、他のビューアー等との連携を容易にします。

---

## 🛰 Installation

LogHarmonizerはPython標準ライブラリのみで動作するため、追加のパッケージインストールは不要です。

```bash
cd OrionFieldStack/logharmonizer
# 実行権限の付与（必要に応じて）
chmod +x logharmonizer1_6.py
```

---

## 🚀 Usage

### 1. 基本コマンド形式

デフォルトでは `CSV -> JSON` モード（c2j）で動作します。

```bash
python3 logharmonizer1_6.py [オプション]
```

### 2. 実行例

```bash
# CSVの編集内容をJSONに反映（対話モード）
python3 logharmonizer1_6.py

# JSONの内容を最新のCSVへエクスポート
python3 logharmonizer1_6.py -m j2c

# 確認プロンプトを出さずに一括処理（バッチモード）
python3 logharmonizer1_6.py --no-interactive

# 特定の設定ファイルを指定して実行
python3 logharmonizer1_6.py --config my_config.json
```

---

## 🛠 Options

| オプション | 短縮 | 内容説明 |
| :--- | :--- | :--- |
| `--mode [c2j/j2c]` | `-m` | `c2j` (CSVからJSONへ同期 / デフォルト)、`j2c` (JSONをCSVへ出力) を切り替えます。 |
| `--interactive` | `-i` | レコードの追加や削除を個別に対話形式で確認します（デフォルト）。 |
| `--no-interactive` | - | プロンプトを表示せず、自動的に追加処理などを行います。 |
| `--config PATH` | - | 設定ファイル（JSON）のパスを指定します（デフォルト: `config.json`）。 |
| `--csv PATH` | - | 設定ファイルを上書きして、対象とするCSVファイルを指定します。 |
| `--json PATH` | - | 設定ファイルを上書きして、対象とするJSONファイルを指定します。 |

---

## ⚙️ Configuration

`config.json` でログファイルのパスやバックアップ先を定義します。

```json
{
    "SYSTEM": {
        "MASTER_JSON": "./shutter_log.json",
        "EDIT_CSV": "./shutter_log.csv",
        "BACKUP_DIR": "./backups",
        "LATEST_JSON": "latest_shot.json"
    }
}
```

---

## 📊 データの精度管理 (Precision)

LogHarmonizerは、同期時にデータの精度が劣化しないよう、以下の精度設定を自動適用します：

- **8桁**: SSEによる解析座標 (`Solve_RA`, `Solve_DEC`)
- **6桁**: 基本座標、緯度経度、露出誤差
- **3桁**: UnixTime、露出時間、StarFlux 品質指標 (FWHM, Ellipticity)
- **1桁**: 気温、湿度、気圧、CPU温度、F値

---

## 🛡 Backup System

同期処理が開始されると、`backups/` 以下に `YYMMDDHHMM_mode` 形式のディレクトリが作成され、処理前の JSON/CSV 両方がコピーされます。不適切な同期を行ってしまった場合でも、ここから元の状態に復元することが可能です。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
