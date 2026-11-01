# OrionFieldStack Map Manager (ofs_map)

`ofs_map` は、OrionFieldStackプロジェクトにおけるオフラインマップ（OSM: OpenStreetMap）タイル管理および地図表示用のGUIアプリケーションです。
指定した領域（Region）のマップタイルをダウンロードしてローカルにキャッシュし、オフライン環境でも地図を閲覧できるように設計されています。

## 特徴
* **オフラインマップサポート**: 指定した緯度・経度範囲およびズームレベルに基づき、OSMタイルを一括ダウンロード・同期します。広域マップ（Zoom 0〜3等）も一括管理可能です。
* **データ保護設計**: ワークスペース（IDE）の負荷軽減とフリーズ防止のため、大容量になるマップデータ（タイル画像および領域設定 `regions.json`）はシステムワークスペース外の **`~/.local/share/ofs_map_data/`** に安全に一元保存されます。
* **高度なGUIと画面レイアウト**: 画面を左右50%ずつに分割し、効率的に情報を配置しています。
  * **左側 (50%)**: メインのオフラインマップ表示。
  * **右側 (50%)**: GPS・テレメトリー情報エリア。上段に現在地周辺の「GPS Map」、下段に「Telemetries（テレメトリー）」と「GPS Satellites（衛星情報）」を配置。
* **高精度GPS & PPS時間同期連携**: `ofs_link` と連携し、以下の高度な位置・時刻情報をリアルタイム表示します。
  * 現在地情報、GPSステータスの表示と手動位置登録機能。
  * **超高精度時刻オフセット表示**: GPSモジュールから得られるPPS（Pulse Per Second）信号を解析し、システムのローカル時間とGPS実時間との誤差（ミリ秒単位）を可視化します。
  * **GPS衛星情報の可視化**: 各衛星の仰角・方位角・SNR（信号強度）、および「測位に使用中（Used in Fix）」かどうかを一覧化し、GPSマップ上に方向と相対位置を図示します。
  * **フリッカー防止機能**: 衛星の受信状況が一時的に不安定になっても画面が点滅しないよう、UI側でデータを数十回分（約30秒間）キャッシュし、視認性を向上させています。

### GPS衛星位置（サブサテライトポイント）の計算方法
GPSマップ上に表示される各衛星のマーカーは、GPS受信機から得られる「仰角（Elevation）」と「方位角（Azimuth）」から、衛星の直下点（サブサテライトポイント）の緯度・経度を逆算して描画しています。
1. **中心角 ($\gamma$) の算出**: 地球の半径 $R \approx 6371.0$ km とGPS衛星の軌道半径 $r \approx 26571.0$ km を用い、仰角 $E$ から地球中心を基準とした衛星とのなす角（中心角 $\gamma$）を求めます。
   $$\cos(E + \gamma) = \frac{R}{r} \cos(E)$$
2. **直下点座標の算出**: 観測地点の緯度・経度を起点に、球面三角法を用いて中心角 $\gamma$（距離に相当）と方位角 $Az$ の方向へ進んだ先の緯度 $lat_2$ と経度 $lon_2$ を計算します。
   $$\sin(lat_2) = \sin(lat_1)\cos(\gamma) + \cos(lat_1)\sin(\gamma)\cos(Az)$$
   $$lon_2 = lon_1 + \mathrm{atan2}\left( \sin(Az)\sin(\gamma)\cos(lat_1), \cos(\gamma) - \sin(lat_1)\sin(lat_2) \right)$$
この計算により、上空にある衛星の地球上の投影位置をリアルタイムにマッピングしています。

## データ保存先
* **マップ設定ファイル**: `~/.local/share/ofs_map_data/regions.json`
* **マップタイル画像**: `~/.local/share/ofs_map_data/tiles/{z}/{x}/{y}.png`
* **保存済み現在地**: `~/.local/share/ofs/location.json`（地図上のクリックから「現在地として登録」を実行した際、`ofs_link --set-location` を介して安全に一元保存されます）

## 使い方

### 1. GUIサーバーの起動（`app.py`）

GUIアプリケーションとタイルサーバーを起動するには、以下のコマンドを実行します。

```bash
cd /path/to/OrionFieldStack/ofs_map
python app.py
```
サーバーが立ち上がったら、ブラウザで以下のURLにアクセスします：
* メインマップビュー (GPS/Telemetry): `http://localhost:8003/`
* 管理画面: `http://localhost:8003/admin`

### 2. コマンドラインツール（`ofs_map.py`）

GUIを使わずに、コマンドラインからも領域の管理やタイルの同期が可能です。

#### 領域の追加 (`add`)
新しいダウンロード領域を追加します。
（例：Zoomレベル0〜3の全世界マップなど、広域の追加も可能です）

```bash
python ofs_map.py add --name "Tokyo" --min-lat 35.5 --max-lat 35.8 --min-lon 139.5 --max-lon 139.9 --min-zoom 10 --max-zoom 14
```

#### 領域の一覧表示 (`list`)
設定されている領域の一覧と、必要となるタイル数を表示します。

```bash
python ofs_map.py list
```

#### タイルの同期 (`sync`)
設定された全領域のマップタイルをOpenStreetMapからダウンロードし、ローカル（`~/.local/share/ofs_map_data/tiles/`）に保存します。不要になったタイルは自動的に削除（クリーンアップ）されます。

```bash
python ofs_map.py sync
```

#### 領域の削除 (`remove`)
設定した領域を削除します。（※削除後、`sync` コマンドを実行することで不要なタイル画像が物理的に削除されます）

```bash
python ofs_map.py remove --name "Tokyo"
```

## 依存関係
* Python 3.x
* FastAPI
* Uvicorn
* Pillow (PIL)
* (現在地・高精度PPS時間・衛星情報取得用として親ディレクトリの `ofs_link.py` に依存)
