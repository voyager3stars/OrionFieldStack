#!/bin/bash
# ofs_setup_env.sh
# OrionFieldStackのシステム要件およびPythonパッケージの自動インストールスクリプト

echo "=========================================="
echo " OrionFieldStack 環境構築スクリプト"
echo "=========================================="

echo "[1/3] システム依存ライブラリのインストール..."
sudo apt-get update
sudo apt-get install -y libdbus-1-dev libglib2.0-dev

echo "[2/3] Python仮想環境の作成..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "仮想環境 'venv' を作成しました。"
else
    echo "仮想環境 'venv' は既に存在します。既存の環境を使用します。"
fi

# 仮想環境のアクティベート
source venv/bin/activate

echo "[3/3] Python依存パッケージのインストール..."
pip install -U pip
pip install -r requirements.txt

echo "=========================================="
echo " 環境構築が完了しました！"
echo " 起動するには以下のコマンドを実行してください："
echo " ./start_ofs.sh"
echo "=========================================="
