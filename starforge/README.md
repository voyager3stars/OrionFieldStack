# StarForge v1.3.3

**High-Precision Multi-Session Astronomical Image Stacker & Register**

StarForgeは、`StarFlux` による画像品質解析結果（楕円率など）を活用し、複数の天体画像を自動的に位置合わせ・スタッキングするハイパワーなツールです。

最新バージョンでは、マルチセッション撮影への完全対応に加え、**マスターフラットの自動生成・再利用**、`config.json` による高度な設定管理、**動的な出力ファイル名生成**、そしてフラット補正の明示的な **ON/OFF 切り替え**をサポートしています。

---

## 🛰 Installation & Setup

StarForgeは以下のライブラリを使用します。
- `astroalign`: 画像の幾何学的変換（位置合わせ）
- `rawpy`: RAW/DNGファイルの現像
- `astropy`, `numpy`: データの操作とFITS出力

### セットアップ手順
```bash
cd OrionFieldStack/starforge
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ⚙️ Configuration (`config.json`)

`starforge.py` と同じディレクトリに `config.json` を配置することで、共通設定を保持できます。

```json
{
    "threshold": 0.2,
    "method": "sigma_clip",
    "mode": "mono",
    "out": "AUTO",
    "use_flat": true,
    "flat_dir": "~/Pictures/flat"
}
```
※コマンドライン引数は、この設定ファイルの内容を常に上書き（オーバーライド）します。

---

## 🚀 Usage

### 基本操作
```bash
# 仮想環境を有効化して実行
./venv/bin/python3 starforge.py [入力パス...] [オプション]
```

### ヘルプ表示の活用
`--help` を実行すると、各オプション右側のカラムに **現在適用されている値** が黄緑色で表示されます。設定ファイルやデフォルト値がどのように反映されているか一目で確認できます。

---

## 🛠 Options

| オプション | デフォルト | 内容説明 |
| :--- | :--- | :--- |
| `inputs` | (必須) | 画像ファイル、ディレクトリ、またはワイルドカード。 |
| `--mode` | `mono` | 処理モード (`color` または `mono`) を選択。 |
| `--threshold` | `0.2` | スタック対象とする楕円率の最大しきい値。 |
| `--session` | - | 指定した Session ID(s) の画像のみを抽出。 |
| `--obj` | - | 指定した Objective 名(s) の画像のみを抽出。 |
| `--flat` / `--no-flat` | `ON` | フラット補正の有効/無効を明示的に指定。 |
| `--flat_dir` | - | フラット画像群が含まれるディレクトリ。 |
| `--method` | `sigma_clip` | スタッキング手法 (`median`, `mean`, `sigma_clip`)。 |
| `--out` | `AUTO` | 出力名。`AUTO` で動的ファイル名を生成。 |

### 📁 動的な出力ファイル名 (`AUTO`)
`--out` が `AUTO` の場合、以下のパターンでファイル名を自動生成します。
`[Session]_[Object]_[Mode]_[YYMMDDHHmm].fits`
例: `20260321_2345_NGC4565_color_2604272102.fits`

---

## 📊 処理フローの詳細

1.  **メタデータ同期**: `shutter_log.json` (v1.6.2準拠) から品質・セッション情報を取得。
2.  **マスターフラット処理**:
    - `flat_dir` 内に `master_flat_[Session]_[Mode].fits` があれば自動ロード。
    - なければ全フラットを `median` スタックしてマスターを新規生成・保存。
3.  **レジストレーション**: `astroalign` によるサブピクセル精度の星位置合わせ。
4.  **チャンクスタッキング**: メモリ効率を考慮した分割処理によるマスター合成。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License
