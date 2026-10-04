# 🔗 ofs_link v1.2 - Telemetry Linker

`ofs_link` は、INDI サーバーおよび GPSD から、望遠鏡架台（マウント）のステータス、赤経・赤緯、ピアーサイド、GPS位置情報、および高精度なタイムスタンプ情報を取得し、標準化された JSON 形式で出力する CUI ユーティリティです。

OrionFieldStack システムの各コンポーネントにおける「現在位置・状態の把握」の役割を担い、将来的には `ofs_gui` などのバックエンドデータコレクタとしても活用できるように設計されています。

---

## 🛠️ 主な機能

*   **INDI・GPSD 統合データ取得**: 
    外部コマンド `indi_getprop` および `gpspipe` を用いて、別個のデーモンからシームレスに各種テレメトリを取得・結合します。
*   **堅牢なパッケージ独立性**:
    Python用の重い `gps` パッケージ等に依存せず、標準のコマンドラインツール経由でソケット通信データを安全にパースするため、仮想環境（venv）下でも依存関係の衝突なく動作します。
*   **高精度タイムゾーン特定**:
    GPSから取得した経度（Longitude）を基に、`timezonefinder` と `pytz` を使って観測地のタイムゾーンを自動特定し、適切なオフセット（例: `+09:00`）付きの現地時間（ISO 8601）を算出します。
*   **位置情報の一元管理**:
    OFS 全体の「保存済み観測地（`~/.local/share/ofs/location.json`）」は `ofs_link` が唯一の窓口として管理・保持します（`ofs_map` の「現在地として登録」、`shutterpro03` のフォールバックも `ofs_link` を介して参照）。
*   **多彩なフォールバック機能**:
    *   **GPSオフライン時**: 保存済み位置情報 `~/.local/share/ofs/location.json` に自動フォールバックします。
    *   **ピアーサイド不明時**: マウントからピアーサイド（望遠鏡が子午線の東/西どちらにあるか）が取得できない場合、経度と赤経、UTC時間から地方恒星時（LST）および時角（Hour Angle）を逆算して自律判定します。
*   **モックモード (`--mock`)**:
    実際のハードウェアやサーバーに接続していない環境でも、開発やテストができるようにダミーの標準化JSONデータを返却するモックモードを備えています。

---

## ⚙️ インストールとセットアップ

### 1. セットアップ
本モジュールの依存パッケージは、プロジェクトルートの `requirements.txt` で一括管理されています。
セットアップ方法は [プロジェクトルートの README](../README.md) を参照してください。

### 2. 実行権限の付与
```bash
chmod +x ofs_link.py
```

---

## 🚀 使用方法

### コマンド形式
```bash
./venv/bin/python3 ofs_link.py --get [options...]
# または
./venv/bin/python3 ofs_link.py --flashair [options...]
# 位置情報の保存・参照
./venv/bin/python3 ofs_link.py --set-location LAT LON [--elevation ELEV]
./venv/bin/python3 ofs_link.py --get-location
```

### 引数オプション
*   `--get`: 望遠鏡およびGPSの情報を取得してJSON出力します。
*   `--flashair`: FlashAir SDカードとの通信状態（接続確認）をチェックし、JSON出力します。
*   `--set-location LAT LON`: 観測地を `~/.local/share/ofs/location.json` に保存し、保存内容をJSON出力します（範囲外の座標はエラー）。
*   `--elevation ELEV`: `--set-location` と併用して標高(m)を指定します。省略時は前回の標高を維持します。
*   `--get-location`: 保存済みの観測地のみをJSON出力します（GPSへの問い合わせなし）。
*   `--mock`: 実際の通信を行わず、テスト用のモックデータを返却します。
*   `--config <path>`: 特定の設定ファイルパスを指定してロードします。指定がない場合は `../shutterpro03/config.json` を読み込みます。

---

## 📊 出力 JSON 仕様

### 1. `--get` 実行時
`--get` を実行した際に出力される標準化 JSON データの各項目は以下の通りです。

```json
{
  "indi_server": "CONNECTED",
  "status": "TRACKING",
  "ra_deg": 83.81020833,
  "dec_deg": -5.38966667,
  "ra_str": "05h35m14s",
  "dec_str": "-05°23'23\"",
  "side_of_pier": "EAST",
  "latitude": 34.6493,
  "longitude": 135.0015,
  "elevation": 54.0,
  "gpsd_status": "enable",
  "time_source": "gpsd",
  "timestamp_utc": "2026-06-21T06:55:01.000Z",
  "iso_timestamp": "2026-06-21T15:55:01.000+09:00",
  "temp_c": 25.9,
  "humidity_pct": 55.6,
  "pressure_hPa": 1010.0,
  "dew_point_c": 17.0,
  "cpu_temp_mount_c": 38.0,
  "cpu_temp_rpi_c": 45.2
}
```

| 項目 | 型 | 説明 |
| :--- | :--- | :--- |
| **`indi_server`** | String | INDIサーバーおよびマウントとの通信状態 (`CONNECTED` / `DISCONNECTED`) |
| **`status`** | String | 架台の現在の動作ステータス (`TRACKING` / `SLEWING` / `IDLE` / `ALERT` / `UNKNOWN`) |
| **`ra_deg`** | Float / null | 現在の赤経 (Right Ascension) を度数法 (0.0〜360.0) で表現した値。取得失敗時は `null`。 |
| **`dec_deg`** | Float / null | 現在の赤緯 (Declination) を度数法 (-90.0〜90.0) で表現した値。取得失敗時は `null`。 |
| **`ra_str`** | String / null | `ra_deg` を `XXhXXmXXs` 形式の文字列にフォーマットした値 |
| **`dec_str`** | String / null | `dec_deg` を `±XX°XX'XX"` 形式の文字列にフォーマットした値 |
| **`side_of_pier`** | String | 望遠鏡のピアーサイド状態 (`EAST` / `WEST` / `UNKNOWN`) |
| **`latitude`** | Float / null | 観測地の緯度（Decimal度数）。GPS失敗時は `location.json` の保存値。 |
| **`longitude`** | Float / null | 観測地の経度（Decimal度数）。GPS失敗時は `location.json` の保存値。 |
| **`elevation`** | Float / null | 観測地の標高/高度 (メートル)。GPS失敗時は `location.json` の保存値。 |
| **`gpsd_status`** | String | GPSDから正常に位置情報を取得できているかを示すフラグ (`enable` / `disable`) |
| **`time_source`** | String | 現在時刻の取得元を示す情報 (`gpsd` または `system`) |
| **`timestamp_utc`** | String | 取得時刻 ofs_link の UTC タイムスタンプ (ISO 8601, `YYYY-MM-DDTHH:MM:SS.fffZ`) |
| **`iso_timestamp`** | String | 観測地のタイムゾーンを考慮した高精度ローカルタイムスタンプ (オフセット付き) |
| **`temp_c`** | Float / null | 観測地の気温/マウント温度（摂氏） |
| **`humidity_pct`** | Float / null | 観測地の相対湿度（%） |
| **`pressure_hPa`** | Float / null | 観測地の気圧（hPa） |
| **`dew_point_c`** | Float / null | 露点温度（摂氏） |
| **`cpu_temp_mount_c`** | Float / null | マウント内蔵コンピュータのCPU温度（摂氏） |
| **`cpu_temp_rpi_c`** | Float / null | Raspberry Pi（システム）のCPU温度（摂氏） |

### 2. `--flashair` 実行時
`--flashair` を実行した際に出力される JSON データの各項目は以下の通りです。

```json
{
  "flashair": "CONNECTED",
  "url": "http://192.168.50.200"
}
```

| 項目 | 型 | 説明 |
| :--- | :--- | :--- |
| **`flashair`** | String | FlashAirとの通信状態 (`CONNECTED` / `DISCONNECTED`) |
| **`url`** | String | 接続確認を行ったFlashAirのベースURL |

---

## 📍 保存済み位置情報 (`~/.local/share/ofs/location.json`)

GPSが利用できない場合に使用される観測地です。OFS全体でこのファイルが唯一の保存先であり、読み書きは `ofs_link` が担当します。

```json
{
    "latitude": 34.6493,
    "longitude": 135.0015,
    "elevation": 54.0,
    "source": "manual",
    "updated_at": "2026-10-04T12:00:00Z"
}
```

*   `source`: 保存元 (`manual`: 手動登録 / `migrated`: 旧設定からの移行 / `default`: 初期値)
*   **更新方法**: `ofs_map` の「現在地として登録」ボタン、または `--set-location` コマンド。GPS取得時の自動保存は行いません。
*   **他モジュールからの利用**: Pythonからは `ofs_link.load_location()` / `ofs_link.save_location()` を import して利用できます（`shutterpro03` が使用）。
*   **自動移行**: ファイルが存在しない場合、旧形式の `shutterpro03/config.json` の `SYSTEM.LAST_*` から初回のみ移行します。いずれも無い場合は明石市立天文科学館 (34.6493, 135.0015, 54.0m) を使用します。

---

## 🛠️ 設定ファイル

ofs_link 専用の設定ファイルは持たず、`../shutterpro03/config.json` の `SYSTEM` セクションから以下のキーを読み込みます（`--config` で別ファイルも指定可能）。

*   `INDI_MOUNT`: INDI上のマウントデバイス名。
*   `PROP_COORD`: 天体座標を取得するプロパティ名。
*   `PROP_GEO`: 観測地情報を取得するプロパティ名。
*   `FLASHAIR_URL`: FlashAirカードのベースURL。省略時は `http://192.168.50.200` が適用されます。

---

## 📜 更新履歴

*   **v1.2** (2026-10-04)
    *   位置情報の保存先を `~/.local/share/ofs/location.json` に一元化（`--set-location` / `--get-location` を追加）
    *   `ofs_link/config.json` を廃止し、設定は `shutterpro03/config.json` から読み込むように変更
    *   `LAST_LATITUDE` / `LAST_LONGITUDE` / `LAST_ELEVATION` 設定キーを廃止（初回起動時に自動移行）
*   **v1.1** (2026-09-04)
    *   環境情報（気温 `temp_c`、湿度 `humidity_pct`、気圧 `pressure_hPa`、露点 `dew_point_c`、マウントCPU温度 `cpu_temp_mount_c`）の取得を追加
    *   システム（Raspberry Pi等）のCPU温度 `cpu_temp_rpi_c` 取得を追加
    *   出力JSONに `ra_str` および `dec_str` を追加
*   **v1.0** (2026-06-21)
    *   初期リリース

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
