#!/usr/bin/env bash
# 一键启动：安装依赖 → 构建前端（首次）→ 启动服务
set -e
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || { echo "未找到 python3，请先安装 Python 3.9+"; exit 1; }

echo "==> [1/3] 安装后端依赖"
"$PY" -m pip install -q -r requirements.txt

if [ ! -f frontend/public/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> [2/3] 首次构建前端"
    (cd frontend && npm install --no-fund --no-audit && npm run build && rm -rf public && cp -r dist public)
  else
    echo "缺少前端构建产物，且未安装 Node.js（需 18+）。请安装 Node 后重试。"; exit 1
  fi
else
  echo "==> [2/3] 已存在前端产物，跳过构建"
fi

echo "==> [3/3] 启动服务：http://localhost:${PORT:-8000}"
"$PY" backend/main.py
