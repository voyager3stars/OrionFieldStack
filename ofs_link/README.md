# 🔗 ofs_link v1.0.0 - Telemetry Linker

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
*   **多彩なフォールバック機能**:
    *   **GPSオフライン時**: `config.json` に設定されているデフォルト/前回位置情報 (`LAST_LATITUDE` 等) に自動フォールバックします。
    *   **ピアーサイド不明時**: マウントからピアーサイド（望遠鏡が子午線の東/西どちらにあるか）が取得できない場合、経度と赤経、UTC時間から地方恒星時（LST）および時角（Hour Angle）を逆算して自律判定します。
*   **モックモード (`--mock`)**:
    実際のハードウェアやサーバーに接続していない環境でも、開発やテストができるようにダミーの標準化JSONデータを返却するモックモードを備えています。

---

## ⚙️ インストールとセットアップ

### 1. 仮想環境の作成とライブラリインストール
プログラムが存在するディレクトリに移動し、専用の仮想環境を作成して依存関係をインストールします。

```bash
cd OrionFieldStack/ofs_link

# 仮想環境の作成
python3 -m venv venv
source venv/bin/activate

# 依存ライブラリのインストール
pip install -r requirements.txt
```

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
```

### 引数オプション
*   `--get`: 望遠鏡およびGPSの情報を取得してJSON出力します（`--flashair` が指定されていない場合は必須）。
*   `--flashair`: FlashAir SDカードとの通信状態（接続確認）をチェックし、JSON出力します。
*   `--mock`: 実際の通信を行わず、テスト用のモックデータを返却します。
*   `--config <path>`: 特定の `config.json` パスを指定してロードします。指定がない場合は、以下の優先順位で自動ロードされます。
    1.  スクリプトと同階層の `./config.json`
    2.  隣接する `shutterpro03` パッケージ内の `../shutterpro03/config.json`

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
  "side_of_pier": "EAST",
  "latitude": 34.6493,
  "longitude": 135.0015,
  "elevation": 54.0,
  "timestamp_utc": "2026-06-21T06:55:01.000Z",
  "iso_timestamp": "2026-06-21T15:55:01.000+09:00"
}
```

| 項目 | 型 | 説明 |
| :--- | :--- | :--- |
| **`indi_server`** | String | INDIサーバーおよびマウントとの通信状態 (`CONNECTED` / `DISCONNECTED`) |
| **`status`** | String | 架台の現在の動作ステータス (`TRACKING` / `SLEWING` / `IDLE` / `ALERT` / `UNKNOWN`) |
| **`ra_deg`** | Float / null | 現在の赤経 (Right Ascension) を度数法 (0.0〜360.0) で表現した値。取得失敗時は `null`。 |
| **`dec_deg`** | Float / null | 現在の赤緯 (Declination) を度数法 (-90.0〜90.0) で表現した値。取得失敗時は `null`。 |
| **`side_of_pier`** | String | 望遠鏡のピアーサイド状態 (`EAST` / `WEST` / `UNKNOWN`) |
| **`latitude`** | Float / null | 観測地の緯度（Decimal度数）。GPS失敗時は `config.json` のデフォルト値。 |
| **`longitude`** | Float / null | 観測地の経度（Decimal度数）。GPS失敗時は `config.json` のデフォルト値。 |
| **`elevation`** | Float / null | 観測地の標高/高度 (メートル)。GPS失敗時は `config.json` のデフォルト値。 |
| **`timestamp_utc`** | String | 取得時刻 ofs_link の UTC タイムスタンプ (ISO 8601, `YYYY-MM-DDTHH:MM:SS.fffZ`) |
| **`iso_timestamp`** | String | 観測地のタイムゾーンを考慮した高精度ローカルタイムスタンプ (オフセット付き) |

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

## 🛠️ 設定ファイル (config.json)

デフォルト設定は `config.json` で管理されます。`shutterpro03` の設定ファイルと共通化することが可能です。

```json
{
  "INDI_MOUNT": "LX200 OnStep",
  "PROP_COORD": "EQUATORIAL_EOD_COORD",
  "PROP_GEO": "GEOGRAPHIC_COORD",
  "LAST_LATITUDE": 34.6493,
  "LAST_LONGITUDE": 135.0015,
  "LAST_ELEVATION": 54.0,
  "FLASHAIR_URL": "http://192.168.50.200"
}
```

*   `INDI_MOUNT`: INDI上のマウントデバイス名。
*   `PROP_COORD`: 天体座標を取得するプロパティ名。
*   `PROP_GEO`: 観測地情報を取得するプロパティ名。
*   `LAST_LATITUDE` / `LAST_LONGITUDE` / `LAST_ELEVATION`: GPSオフライン時に適用されるフォールバック用の緯度・経度・高度情報。
*   `FLASHAIR_URL`: FlashAirカードのベースURL。省略時は `http://192.168.50.200` が適用されます。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
