# SkySolverEngine (SSE) v2.0.2

**High-Speed Plate Solving & Log Enricher**

SSEは、Astrometry.netをバックエンドに使用し、撮影画像から天体座標を特定してログを自動更新する解析エンジンです。

## 🌌 依存ソフトウェア Astrometryのインストール
本ツールの動作には \`solve-field\` (Astrometry.net) がシステムにインストールされている必要があります。

```bash
sudo apt install astrometry.net
```

### 📖インデックスデータの準備

解析には、ご使用の機材（センサーサイズと焦点距離）に適合したインデックスファイルが必要です。

### 📖適合表 (目安)
| Index Series | Field of View | Full Frame (Focal Length) | APS-C (Focal Length) |
| :--- | :--- | :--- | :--- |
| **4213-4219** | Wide ($>2^\circ$) | < 500mm | < 350mm |
| **4208-4212** | Middle ($0.5^\circ \sim 2^\circ$) | 500mm - 2500mm | 350mm - 1700mm |
| **4207以下** | Narrow ($<0.5^\circ$) | > 2500mm | > 1700mm |

### 📖インストール手順
自身の機材に合わせて、必要なパッケージを選択してインストールしてください。
### 1. 推奨インデックスデータ
フルサイズセンサー・焦点距離 760mm（画角 約2.7°×1.8°）の場合、以下のシリーズが必要です。
* **4208 - 4212**: メイン画角をカバー（必須）
* **4207**: 補完データ（推奨）
* **4213 - 4219**: 広域・全天検索用（ヒントなし解析に必要）

### 2. インストールコマンド (Debian/Raspberry Pi OS)
以下のコマンドで、必要なデータを一括インストールできます。
```bash
# 例: R200SS (760mm) + フルサイズカメラの場合
sudo apt update
sudo apt install astrometry-data-4208-4219 astrometry-data-4207
```



### 📖設定の確認
インストール後、データが正しく認識されているか確認してください。

* **データの場所: /usr/share/astrometry/ に .fits ファイルがあること。
* **設定ファイル: /etc/astrometry.cfg 内に add_path /usr/share/astrometry が記述されていること。


## 📖 Python環境構築
システムパッケージを引用しつつ、仮想環境を構築します。
```bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```
**Note:** 依存ライブラリとして `rawpy`, `imageio`が導入されます。

## 🚀 Usage

## 1.  基本コマンド形式
```bash
python3 SSE.py [モード] [解析対象のパス] [追加オプション]
```

## 2. モード
### Mode 1: Latest (最新ショットの解析)
最新の `latest_shot.json` を参照し、座標ヒント(RA/Dec)を用いて高速解析を行います。
```bash
python3 SSE01_V1_7_1.py latest ~/Pictures/
```

### Mode 2: Select (一括・個別解析)
指定したフォルダ内の `shutter_log.json` を参照しながら、未解析の画像を一括処理します。

```bash
# フォルダ内の未解析分を自動スキップしながら一括処理
python3 SSE01_V1_7_1.py select ~/Pictures/M42_Project/
```

## 3. オプション機能

SSEの実行時に指定できる主要なオプションは以下の通りです。

| オプション | 実行コマンド例 | 内容説明 |
| :--- | :--- | :--- |
| **全天探索** | `--allsky` | ヒント座標（RA/Dec）で解決できない場合に、自動的に全天領域から場所を特定するブラインドサーチ（Pass 4〜6）を実行します。 |
| **強制再解析** | `--force` | ログ上で「解析成功」と記録されている画像であっても、スキップせずに最初から解析（Pass 1〜3）をやり直します。 |

### 📊 ログ参照の仕組み
SSEは画像ファイル単体ではなく、常に`shutter_log.json` とセットで動作します。

* **読込: ログから撮影時のマウント座標を取得し、解析時間を短縮します。**
* **判定: ログ内のステータスを確認し、解析済みのものはスキップします。**
* **更新: 解析結果（座標、成功/失敗）を JSON と CSV の両方に書き戻します。**



## ⚖️ License
© 2026 OrionFieldStack Project / MIT License

