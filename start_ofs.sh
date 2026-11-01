#!/bin/bash

# 1. LCDのスタート画面を3秒表示
python3 ~/dev/OrionFieldStack/ofs_lcd/ofs_start_view.py 3

# 2. LCDのステータス画面をバックグラウンドで常駐実行
python3 ~/dev/OrionFieldStack/ofs_lcd/ofs_status_view.py &

# 3. ofs_mapのフォルダに移動してバックグラウンドで実行
cd ~/dev/OrionFieldStack/ofs_map
../venv/bin/python app.py &

# 4. ofs_guiのフォルダに移動して実行
cd ~/dev/OrionFieldStack/ofs_gui
../venv/bin/python app.py
