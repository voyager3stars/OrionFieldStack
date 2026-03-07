# 🛰️ SkySync v2.0.2 - Observation Sequence Manager
SkySyncは、OrionFieldStackシステムにおける撮影（ShutterPro）、プレートソルブ（SSE）、そして架台の同期（INDI）を一つの流れ（シーケンス）として統合するメインコントローラーです。
## 🛠️ 主な機能
* ワンストップ・ワークフロー: 撮影から解析、架台への座標同期までを全自動で実行します。
* 高度な解析連携: SSE v2.0.x が出力する最新の latest_shot.json を読み取り、解析結果を即座に反映します。
* INDIマウント同期: 解析された度（Degree）単位の座標を、INDI標準の時（Hours）単位へ自動変換して架台へ送信します。
* 柔軟な運用モード: 撮影からのフル自動、既存画像の解析・同期、または座標の直接指定に対応しています。
 ## 🏗️ 観測シーケンスの全体図
SkySyncがハブとなり、各コンポーネントを繋いで観測を進行させます。
 ```mermaid
 graph LR
    User([ユーザー]) --> SkySync[SkySync v2.0.2]
    
    subgraph "Capture & Solve"
        SkySync --> ShutterPro[shutterpro03.py<br/>画像撮影]
        ShutterPro --> SSE[SSE.py<br/>プレートゾルブ]
    end
    
    subgraph "Synchronization"
        SSE --> JSON[(latest_shot.json)]
        JSON --> SkySync
        SkySync --> INDI[INDI Mount<br/>同期完了]
    end
```
## ⚙️ 設定ファイル (config.json)
システム全体の動作設定は config.json で管理します。
```json
{
    "paths": {
        "shutter_pro_dir": "~/OrionFieldStack/shuterpro03",
        "sse_dir": "~/OrionFieldStack/SSE",
        "default_image_dir": "~/Pictures/sync"
    },
    "indi": {
        "device": "LX200 OnStep"
    },
    "shutter_defaults": {
        "session": "sync",
        "type": "Sync",
        "count": "1",
        "mode": "bulb",
        "exposure": "5"
    }
}
```

# 🚀 使い方
## 1. フル自動モード (Capture + Solve + Sync)
撮影を実行し、成功したら解析を行い、その結果を架台に同期します。
```Bash
python3 skysync.py full
```
## 2. 解析・同期モード (Solve + Sync)
すでに撮影済みの最新画像（latest_shot.json）を解析し、架台に同期します。
```Bash
python3 skysync.py sync
```
## 3. マニュアル同期モード
解析結果を使わず、指定した座標を直接架台へ送信します。
```Bash
python3 skysync.py manual --ra 83.82 --dec -5.39
```
## 🔍 技術仕様：
天体位置解析（Astrometry.net）の出力は「度（Degrees）」ですが、多くの架台制御プロトコル（INDI等）では赤経を「時（Hours）」で扱う必要があります。SkySyncは以下の計算により、高精度な同期を実現しています。
$$RA_{hours} = \frac{RA_{deg}}{15.0}$$
Note: 浮動小数点は第8位まで精度を保持して計算されます。
## 📋 必要条件
* INDI Library: indi_setprop が動作する環境であること。
* Python 3.x: 仮想環境（venv）の使用を推奨。

#### ⚖️ License© 2026 OrionFieldStack Project / MIT License