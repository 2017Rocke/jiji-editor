#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -d "output/吉吉编辑软件.app" ]; then
  open "output/吉吉编辑软件.app"
elif [ -x .venv/bin/python ]; then
  exec .venv/bin/python server.py
else
  echo "请先参照 README 安装 Python 依赖，或使用已打包的 Mac 应用。"
  read -r
fi
