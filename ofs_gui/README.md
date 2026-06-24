# OrionFieldStack Web GUI (ofs_gui)

**OrionFieldStack 統合ウェブコントロールパネル**

`ofs_gui` は、OrionFieldStackの撮影制御スクリプト（`shutterpro03`）、天体位置解析エンジン（`SSE: SkySolverEngine`）、画像スタック処理（`starforge`）、測光・解析（`starflux`）、および望遠鏡同期制御（`skysync`）をブラウザから一元管理・監視・操作するためのFastAPIベースのWebアプリケーションです。

---

## 🌌 主な機能

### 1. SHUTTER（撮影セッション管理＆テレメトリー）
* **パラメータ設定**: 撮影枚数、シャッターモード（Camera/Bulb）、露出時間（秒）、天体ターゲット（Objective）、フレームタイプ（light, dark, flat, bias等）、保存ディレクトリなどを直感的に設定可能。
* **コンパクトなUI**: 野外観測での限られたディスプレイ（ノートPCやモバイル端末）でもスクロール量を抑え視認性を確保するため、余白や入力枠のサイズを抑えたコンパクトなレイアウト。
* **ライブダッシュボード & ログコンソール**: 現在のステータス（露出中、ダウンロード中、アイドルなど）、現在の進捗（枚数）、プログレスバーをリアルタイムで表示し、撮影プロセスの標準出力をリアルタイムストリーミング形式で表示。
* **テレメトリーダッシュボード**: マウントの現在位置（RA/DEC座標、子午線越え方向）、現地時間/UTC、GPS位置情報（緯度/経度/標高）、FlashAirの接続状態およびURLをリアルタイムで表示・監視可能。
* **デフォルト保存**: 設定をデフォルトとして保存し、次回起動時に自動で読み込ませることができます。

### 2. LOGDATA & ANALYZERS（撮影ログ・解析ブラウザ）
* **3カラムレイアウト**: 
  - **Sessions カラム**: 指定したログフォルダ内の `shutter_log.json` からセッションIDごとに撮影グループを分類して表示。
  - **Files カラム**: 選択したセッションに含まれる画像ファイルを撮影時刻順に一覧表示。
  - **Details カラム**: DNG/RAW（JPEGプレビューの自動生成含む）および通常形式の画像のプレビュー、およびメタデータ（EXIF、マウント座標、位置情報、星像のFWHM品質、機材構成など）を表・Raw JSON形式で表示。
* **インタラクティブプレビュー**: マウスホイールによるズーム、ドラッグによるパン（平行移動）に対応したリッチな画像プレビューモーダルを搭載。FITSファイルのプレビュー画像自動生成にも対応。
* **SkySolverEngine (SSE) Runner**: 撮影したセッションやフォルダを選択し、GUIから直接天体位置解析エンジン（`SkySolverEngine`）を起動可能。ターゲットは「フォルダ全体」「選択したセッション」「選択した特定のファイル」から柔軟に指定可能。リアルタイムの進捗ステータスとストリーミングログをサポート。
* **Starflux (Photometric Analyzer)**: 恒星測光および星像解析を行う `Starflux` をGUIから直接実行可能。SNRや検出星数の上限、ヒストグラムプロットなどの詳細オプションを設定し、解析結果をログに自動反映。

### 3. STARFORGE（画像スタック処理）
* **StarForge Stacker**: 選択したセッションやファイル群を対象に、画像のスタック（コンポジット）処理をGUIから直接実行可能。スタックモード（Mono/Color）やアルゴリズム（Sigma Clip, Median, Mean）を選択可能。
* **キャリブレーション設定**: ダーク減算（Dark Subtraction）およびフラットフィールド補正（Flat Calibration）の適用をサポート。適用するダーク・フラット用のディレクトリおよびセッションの指定が可能。
* **品質ベースの選別（楕円率ヒストグラム）**: 解析された星像の楕円率（Ellipticity）のヒストグラムを表示。ヒストグラムをクリックして閾値を調整することで、高品質なフレームのみを選択してスタック可能。
* **セッションレポート生成**: スタック処理完了時に、MarkdownおよびHTML形式のセッションレポートを自動生成し、結果をブラウザから確認可能。

### 4. SYNC（自動・手動マウント同期）
* **自動同期フロー**: テスト撮影、プレートソルビング（天体位置解析）、マウント同期（INDI）を一連の流れで実行する自動同期フローをGUIから実行・監視。
* **手動同期（Manual Sync）**: 解決された座標（RA/DEC）を確認し、INDIマウントに対して手動で同期コマンドを送信可能。

---

## 🚀 セットアップと起動方法

### 1. 依存ライブラリのインストール
Web GUIの動作に必要なパッケージをインストールします。

```bash
# ofs_gui ディレクトリに移動
cd ofs_gui

# 仮想環境の作成と有効化 (推奨)
python3 -m venv venv
source venv/bin/activate

# 依存関係のインストール
pip install -r requirements.txt
```

### 2. サーバーの起動
`app.py` を実行すると、Uvicorn Webサーバーが起動します（開発用にホットリロード `reload=True` が標準で有効化されています）。

```bash
python3 app.py
```
起動後、ブラウザで [http://localhost:8000](http://localhost:8000) にアクセスしてください。

---

## 📁 ディレクトリ構成

* `app.py`: FastAPIによるWebバックエンドAPI（ShutterPro、SSE、Starflux、Starforge、SkySyncのバックグラウンドプロセス管理、設定の保存読込、画像・ログ閲覧など）。
* `requirements.txt`: Pythonの依存パッケージリスト（FastAPI, Uvicorn, rawpy, Pillow, imageioなど）。
* `static/`: HTML/CSS/JavaScriptによるフロントエンドソース。
  - `index.html`: グラスモルフィズムスタイルを採用したレスポンシブHTML構造（SHUTTER, LOGDATA, STARFORGE, SYNCの4タブ構成）。
  - `style.css`: 天体観測の夜間使用に適した目に優しいダークテーマ、モーダル、スピナーアニメーション等のスタイル。
  - `script.js`: 各種API連携、EventSourceストリーミング、ズーム・パン、動的なステータスバー表示などのインタラクティブ制御ロジック。
* `ofs_gui_sp03_config.json`: Web GUIのデフォルト設定保存用 JSON ファイル。

---

## 📝 更新履歴

### v1.4.2 (2026-06-20)
* **新機能の追加と統合**:
  - **STARFORGE タブ**: 画像スタック処理（Sigma Clip等）、ダーク/フラットキャリブレーション、星像の楕円率ヒストグラムによる選別、およびレポート出力機能。
  - **SYNC タブ**: 自動同期フロー（SkySync連携による撮影・ソルブ・マウント同期）、およびマウントへの手動同期（Manual Sync）機能。
  - **Starflux (Photometric Analyzer)**: LOGDATAタブから起動可能な測光・星像解析機能。
  - **テレメトリー監視**: SHUTTERタブへのリアルタイムテレメトリーダッシュボード（INDI、マウント座標、GPS、FlashAir等）の追加。
* **SHUTTERタブのUI最適化 (コンパクト化)**:
  - 野外での観測作業（ノートPCやモバイル等の小型ディスプレイ）での操作性を高めるため、余白（Padding/Margin）および入力項目間の間隔（Grid Gap）を半分に削減。
  - `Common Settings` および `Advanced Settings`（Equipment Details, Hardware & Network）の両方のカード枠に適用し、スクロールなしで全体を見渡しやすく改善。
* バージョン情報を v1.4.2 に更新。
