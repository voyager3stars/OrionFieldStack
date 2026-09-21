# StarFlux v1.3.4

**High-Precision Image Quality Analyzer & Statistics Integrator**

StarFluxは、撮影された天体画像から星を検出し、その形状（FWHM：半値幅、楕円率）を統計的に解析するツールです。OrionFieldStackプロジェクトの一環として、解析結果を `shutter_log.json` および `shutter_log.csv` に自動的に統合し、撮影データの品質管理を容易にします。

---

## 🛰 Installation & Setup

StarFluxは、画像の読み込みに `rawpy` や `astropy` を、星の検出に `photutils` を使用します。

### セットアップ
本モジュールの依存パッケージは、プロジェクトルートの `requirements.txt` で一括管理されています。
セットアップ方法は [プロジェクトルートの README](../README.md) を参照してください。

**主な依存ライブラリ:** `rawpy`, `astropy`, `photutils`, `numpy`

---

## 🚀 Usage

### 1. 基本コマンド形式
ファイル単体、またはフォルダ内の画像を対象に解析を実行できます。

```bash
python3 starflux.py <path> [オプション]
```

| 引数 | 説明 |
| :--- | :--- |
| `path` | 解析対象の**ファイルパス**または**フォルダパス**（必須） |

**対応ファイル形式:** `.dng`, `.raw`, `.fits`, `.fit`, `.fts`

- **ファイル指定時:** その1枚のみを解析します（`--session` は不要です）。
- **フォルダ指定時:** 上記拡張子を持つファイルを名前順にスキャンし、一括処理します。

### 2. 実行例
```bash
# フォルダ内の全画像を解析し、ログを更新
python3 starflux.py ~/Pictures/M42_Project/

# 特定セッションの画像だけ解析
python3 starflux.py ~/Pictures/M42_Project/ --session 20260321_2345

# 解析結果をヒストグラムで表示（ダッシュボード表示）
python3 starflux.py ~/Pictures/M42_Project/ --plot

# すでに解析済みの画像も強制的に再解析
python3 starflux.py ~/Pictures/M42_Project/ --force

# セッション絞り込み + 強制再解析 + ヒストグラム表示
python3 starflux.py ~/Pictures/M42_Project/ --session 20260321_2345 --force --plot

# カットアウトサイズを変更して解析
python3 starflux.py ~/Pictures/M42_Project/ --box-size 21

# ログを更新せずに画面表示のみ
python3 starflux.py ~/Pictures/M42_Project/ --plot --no-log
```

---

## 🛠 Options

| オプション | デフォルト | 内容説明 |
| :--- | :--- | :--- |
| `--force` | `OFF` | 同一バージョンで解析済み（`success` / `error`）の画像でもスキップせず再解析します。 |
| `--plot` | `OFF` | 解析結果のFWHMと楕円率の分布をテキストベースのヒストグラムで表示します。 |
| `--no-log` | `OFF` | 画面表示のみを行い、`shutter_log.json` および `shutter_log.csv` への書き込みをスキップします。 |
| `--top-stars <N>` | `300` | 検出された星をピーク輝度順にソートし、上位 N 個だけ品質解析の対象とします。 |
| `--snr <値>` | `5.0` | 星検出の閾値。画像のクリップ済み標準偏差 × SNR を DAOStarFinder の閾値に使用します。 |
| `--box-size <N>` | `15` | 各星の品質解析に使うカットアウト（切り出し）サイズ（ピクセル）。 |
| `--session <ID>` | なし | **フォルダ指定時のみ有効。** `shutter_log.json` の `session_id` が一致するファイルだけを処理対象にします。 |
| `--save-bg-image` | `OFF` | 画像の背景モデル（2D背景画像）を抽出し、指定された形式で保存します。 |
| `--bg-format` | `fit` | `--save-bg-image` 時に保存する画像フォーマットを指定します（`fit` または `npz`）。`npz` 指定時はファイルサイズ削減のため 1/4 ダウンサンプリングと `float16` 変換が行われます。 |
| `-outpath / --outpath` | なし | `--save-bg-image` 時にファイルを保存するディレクトリパスを指定します（指定がない場合は元画像と同じディレクトリ）。 |

### `--session` の挙動

1. 指定フォルダ内の `shutter_log.json` を読み込みます。
2. `session_id` が一致するレコードの `record.file.name` を収集します。
3. ディレクトリ内の画像ファイルのうち、収集したファイル名に一致するものだけを解析します。
4. 別セッションのファイルやログに記録のないファイルはスキップされます。
5. `shutter_log.json` が存在しない、または読み込みに失敗した場合は警告を表示し、フィルタなしで全画像を対象とします。

---

## 📋 処理の流れ

```
入力 (ファイル or フォルダ)
  → [--session] セッション絞り込み（フォルダ時）
  → 解析済みチェック（同一バージョン + success/error → スキップ、--force で解除）
  → 画像読み込み (DNG/RAW/FITS)
  → 星検出 (DAOStarFinder)
  → 上位 N 個の星で FWHM / 楕円率を統計算出
  → shutter_log.json / shutter_log.csv を更新（--no-log でスキップ）
  → [--plot] ヒストグラム表示
```

**コンソール出力の例:**
```text
StarFlux v1.3.4>> Scanning directory: ~/Pictures/M42_Project/
StarFlux v1.3.4>> Found 12 image(s) to analyze.
  [Skip] IMG_0001.dng already processed by v1.3.4
  [Processing] IMG_0002.dng...
StarFlux v1.3.4>> Finished. 11/12 files processed in 45.3s.
```

解析に失敗した場合（星未検出、読み込みエラー等）も、`--no-log` を指定していなければログに `error` ステータスを記録します。

---

## 🌌 背景（Background）モデリングのアルゴリズム

StarFluxは、天体写真特有の「周辺減光（ドーム状の減光）」と「局所的な背景ムラ（光害やカブリ）」の両方を高精度に抽出するため、**ハイブリッド背景モデリング手法**（Global Polynomial + Local Spline）を採用しています。この手法により、画像の中心から4隅の端まで滑らかで物理的に自然な背景画像を生成します。

### 1. Global Fit (大域モデル)
まず、画像全体に対して粗いメッシュ（デフォルトで `128×128` ピクセルのボックスサイズ）で `photutils.background.Background2D` を適用し、各ボックスの背景値を算出します。さらに `3×3` のメジアンフィルタをかけて星などの影響を除去した代表値のメッシュを取得します。

このメッシュの中心座標 $(x, y)$ と代表値 $z$ に対し、レンズの周辺減光と形状的によく一致する「2次2次元多項式（パラボロイド）」を最小二乗法でフィッティングします（`astropy.modeling.models.Polynomial2D(degree=2)`）。近似される大域モデル $B_{global}$ の計算式は以下の通りです。

$$ B_{global}(x, y) = c_{00} + c_{10}x + c_{01}y + c_{20}x^2 + c_{11}xy + c_{02}y^2 $$

この多項式モデルを画像全体のピクセル座標で評価することで、4隅の枠外でも値が急激に落ち込まない、滑らかで安定したドーム状の大域的背景を作成します。

### 2. Local Fit (局所モデル)
次に、元の画像データから「大域的背景」を差し引きます。

$$ Residual(x, y) = Data(x, y) - B_{global}(x, y) $$

周辺減光がキャンセルされたことにより、画像全体がほぼ平坦（ゼロ付近）な残差（Residual）画像になります。
この残差画像に対して、再度同じメッシュサイズ（`128×128`）で `Background2D`（デフォルトのスプライン補間）を実行し、$B_{residual}$ を算出します。データがすでに平坦化されているため、スプライン補間特有の「エッジでのオーバーシュート（境界付近での波打ちや急降下）」が発生せず、局所的なカブリやムラだけを安全かつ精緻に抽出できます。

### 3. 合成と背景統計値
最終的に、大域モデルと局所モデルを足し合わせて最終的な背景画像とします。

$$ B_{final}(x, y) = B_{global}(x, y) + B_{residual}(x, y) $$

生成された背景画像から以下の統計値が算出され、ログに記録されます。
- **`bg_median` (背景の中央値)**: 最終背景画像全体の中央値。
- **`bg_mad` (背景のMAD)**: 元画像から背景を引いたデータの中央絶対偏差（Median Absolute Deviation）。背景ノイズの大きさを表します。

---

## 📊 ログ統合の仕組み

StarFluxは、解析対象と同じディレクトリにある `shutter_log.json` と `shutter_log.csv` を自動的に探し、解析結果を追記します。書き込みは一時ファイル経由の原子操作（`os.replace`）で行い、処理中の電源断によるログ破損を防ぎます。

これにより、一晩の撮影を通して「どのタイミングでピントが甘くなったか」や「追尾精度が落ちたか」を一覧で確認することが可能になります。

### 1. JSON 形式 (`shutter_log.json`)

各レコードの `analysis` ブロック内に `SF` オブジェクトが生成または更新されます（OrionFieldStack JSON Spec v1.6.3 準拠）。

**成功時:**
```json
"analysis": {
    "SF": {
        "sf_version": "1.3.4",
        "sf_status": "success",
        "sf_timestamp": "2026-06-28T23:12:37",
        "bg_image": {
            "path": "/home/mtorig/Pictures",
            "name": "IMG_1234_bg_image.npz"
        },
        "quality": {
            "sf_stars": 300,
            "sf_fwhm_mean": 2.54,
            "sf_fwhm_med": 2.50,
            "sf_fwhm_std": 0.32,
            "sf_ell_mean": 0.12,
            "sf_ell_med": 0.11,
            "sf_ell_std": 0.04,
            "sf_bg_median": 7883.372,
            "sf_bg_mad": 710.304
        }
    }
}
```

**失敗時:**
```json
"analysis": {
    "SF": {
        "sf_version": "1.3.4",
        "sf_status": "error",
        "sf_timestamp": "2026-06-28T23:12:37",
        "sf_error": "No stars detected"
    }
}
```

> **Note:** v1.2 以前の `analysis.quality` 形式のログも、スキップ判定時にフォールバック参照されます。

### 2. CSV 形式 (`shutter_log.csv`)

SSE 関連列の後に、以下の StarFlux 列が**固定で BM列 (65列目)** から追記されます（v1.6.3 マスターヘッダー準拠）。

| ヘッダー名 | 内容 |
| :--- | :--- |
| `SF_version` | StarFlux バージョン |
| `SF_status` | 解析ステータス（`success` / `error`） |
| `SF_timestamp` | 解析実行日時 |
| `bg_image_path` | 背景画像（FITS/NPZ）の保存先パス |
| `bg_image_name` | 背景画像（FITS/NPZ）のファイル名 |
| `SF_stars` | 解析された星の数 |
| `SF_fwhm_med` | FWHM 中央値 |
| `SF_fwhm_mean` | FWHM 平均値 |
| `SF_fwhm_std` | FWHM 標準偏差 (σ) |
| `SF_ell_med` | 楕円率 中央値 |
| `SF_ell_mean` | 楕円率 平均値 |
| `SF_ell_std` | 楕円率 標準偏差 (σ) |
| `SF_bg_median` | 背景の明るさ 中央値 (ADU) |
| `SF_bg_mad` | 背景ノイズ MAD値 |

旧フォーマットの CSV（レガシー列名）を読み込んだ場合も、書き込み時に v1.6.3 ヘッダーへ自動変換されます。

---

## ⚖️ License
© 2026 OrionFieldStack Project / MIT License

---

## 📝 更新履歴
* **v1.3.4**: 背景画像（`--save-bg-image`）の出力形式として `--bg-format npz` を指定した場合、解像度の 1/4 ダウンサンプリングとデータ精度の `float16` 変換を適用し、保存時のファイルサイズを大幅に削減（約 1/32）するよう最適化しました。
* **v1.3.3**: 背景の明るさ(`bg_median`)および背景ノイズ(`bg_mad`)の算出に対応。2D背景のFITS画像保存機能(`--save-bg-image`)と、保存先指定オプション(`-outpath`)を追加。JSONおよびCSVの出力フォーマットをアップデート。
* **v1.3.2**: FWHMおよび楕円率の処理の最適化とバグフィックス。
* **v1.1.0**: フォルダ一括処理、`shutter_log.json` 自動統合機能の実装。
