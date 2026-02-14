# ShutterPro03

**Precision Shutter Control & Telemetry Logger for Astrophotography**

ShutterPro03は、天体撮影におけるシャッター制御と、撮影時の環境・機材情報の自動記録を統合するオープンソースのコマンドラインツールです。OrionFieldStack プロジェクトの中核として設計されており、解析エンジンに最適化された標準化ログを出力します。

## 🛰 Overview

本ツールは、物理的なリレー（フォトカプラ）回路によるシャッター制御とFlashAirを組み合わせることで、USB経由の制御やデータ転送に対応していない旧式・エントリークラスのカメラでも、高度な自動撮影とワイヤレスワークフローを実現します。

単なるシャッター操作に留まらず、撮影の瞬間にINDIサーバーから天体座標（RA/Dec）や気象データを取得し、画像メタデータと同期。**OrionFieldStack JSON Log Specification (v1.3.2)** に基づいた高精度な標準化ログを生成します。応用性の高いCUIツールとして、他の解析ツールや自動化パイプラインとの連携も容易です。遠征先での利便性と、緻密なデータ解析を両立したい天文ファンへ最適なプラットフォームを提供します。

---

## 🚀 Key Features

* **Flexible Control**: GPIOを介したバルブ撮影およびカメラトリガー制御に対応。
* **INDI Integration**: マウント情報（RA/Dec）や気象情報、CPU温度などのテレメトリを自動取得。
* **Standardized Logging**: すべてのショット情報を **JSON Spec v1.3.2** に準拠した形式で保存。
* **Field-Ready CLI**: 現場での操作性を重視した短縮エイリアス入力に対応。

---

## 🛠 Usage & Configration
ShutterPro03は、`config.json`によるデフォルト動作と、コマンド引数による柔軟な上書き（オーバーライド）」の二段構えで設計されています。

### 📋 基本構造:
```bash
python3 shutterpro03.py [shots] [mode] [exposure_sec] [options...]
```
* **shots**: 撮影枚数（必須）
* **mode**: シャッターモード (\`bulb\` または \`camera\`) 
* **exposure_sec**: 1枚あたりの露出時間（秒）※bulbモードの場合
* **options**: \`key=value\` 形式で、\`config.json\` の設定を一時的に上書きします。

### 💡 Help & Current Settings
```bash
python3 shutterpro03.py -h
```

* **-h, -help**: ヘルプを表示します。
* **現在の \`config.json\` から読み込まれたデフォルト値（機材名や接続設定など）も一覧で表示されるため、設定確認ツールとしても便利です。**


### 📋 Examples

#### 1. 60秒のバルブ撮影を10枚実行 (対象: M42, 鏡筒: R200SS)
```bash
python3 shutterpro03.py 10 bulb 60 obj=M42 tel=R200SS
```

#### 2. デフォルト設定で撮影 (Easy Start)
`config.json` に機材名などが設定されていれば、最小限の入力で済みます。
```bash
# 60秒のバルブ撮影を20枚実行
python3 shutterpro03.py 20 bulb 60
```

#### 3. 現場での設定上書き (Easy Override)
引数（短縮エイリアス）を入力することで、設定ファイルの内容を一時的に上書きして実行します。
```bash
# ターゲットをM42に変更、テスト撮影(t=test)として実行
python3 shutterpro03.py 1 bulb 10 obj=M42 t=test
```

## ⚙️ Configurable Items & Overrides
以下の項目は \`config.json\` でデフォルト値を設定でき、実行時の引数（Short/Long両対応）で一時的に上書き可能です。


| Category | Item (Config Key) | Arguments (Short/Long) | Impact / 役割の詳細 |
| :--- | :--- | :--- | :--- |
| **Context** | **objective** | \`obj=\` / \`objective=\` | **[ターゲット特定]** 解析エンジンが天体座標データベースと照合する際の主キーとなります。 |
| | **session** | \`sess=\` / \`session=\` | **[データ分類]** 観測夜ごとの管理用。後工程でショットを一括抽出する際に使用します。 |
| | **type** | \`t=\` / \`type=\` | **[パイプライン制御]** Light, Dark, Flat等の指定。スタック時の自動処理フラグとなります。 |
| **Equipment**| **telescope** | \`tel=\` / \`telescope=\` | **[光学特性記録]** 鏡筒ごとの写りの癖や周辺減光の分析を可能にします。 |
| | **camera** | \`cam=\` / \`camera=\` | **[センサー特性記録]** 使用カメラを特定し、ダーク適用ミスやノイズ管理を容易にします。 |
| | **focal_length**| \`f=\` / \`focal=\` | **[解析精度]** プレートソルブ時の画角計算に使用。正確なほど解析が高速化します。 |
| | **optics** | \`opt=\` / \`optics=\` | **[画角変化記録]** レデューサー等の使用を記録。焦点距離の変化をトレースします。 |
| | **filter** | \`filter=\` | **[波長特性記録]** 使用フィルターを記録。カラーバランス調整の参考情報となります。 |
| **System** | **log_dest** | \`log_dest=\` | **[保存先制御]** \`s2cur\` (実行場所) か \`s2save\` (画像保存先) かを選択します。 |
| | **dir** | \`dir=\` / \`directory=\` | **[画像参照先]** FlashAir等から画像を取得・参照する際のベースディレクトリを指定します。 |
| **INDI** | **INDI_SERVER** |  \`server=\` | **[通信設定]** INDIサーバーのIPアドレス。テレメトリ取得の接続先です。 |
| | **INDI_PORT** | \`port=\` | **[通信設定]** INDIサーバーのポート番号（デフォルト: 7624）。 |
| | **INDI_DEVICE** | / \`dev=\` | **[マウント特定]** 座標（RA/Dec）を取得する対象のマウントデバイス名です。 |
---

## 📊 Data Specification

本ツールが出力するログファイルは、OrionFieldStack 標準規格に準拠しています。

* **Software Version**: v13.12.0
* **JSON Log Spec**: [v1.3.2](./OFS_json_spec.md)

### Log Destination Policy
\`log_dest\` オプションにより、保存先を制御可能です:
* \`s2cur\`: スクリプトを実行した現在のディレクトリに保存。
* \`s2save\`: 画像が保存されるディレクトリ（\`dir=\` で指定）に保存。



---

## 📋 Requirements

* Python 3.x
* RPi.GPIO (Raspberry Pi環境の場合)
* PyIndi (INDIテレメトリ取得用)
* 有効な \`config.json\` 設定ファイル

---

## 📝 License

© 2026 OrionFieldStack Project.
Created by @voyager3.stars.
