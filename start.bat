@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==^> [1/3] 检查 Python
where python >nul 2>&1
if errorlevel 1 (
  echo 未找到 python，请先安装 Python 3.9+ 并加入 PATH
  pause & exit /b 1
)

echo ==^> [2/3] 安装后端依赖
python -m pip install -q -r requirements.txt

if not exist "frontend\public\index.html" (
  where npm >nul 2>&1
  if errorlevel 1 (
    echo 缺少前端构建产物，且未安装 Node.js（需 18+）。请安装 Node 后重试。
    pause & exit /b 1
  )
  echo ==^> 首次构建前端
  pushd frontend
  call npm install --no-fund --no-audit
  if errorlevel 1 ( popd & echo npm install 失败，可尝试加 --registry=https://registry.npmmirror.com & pause & exit /b 1 )
  call npm run build
  if errorlevel 1 ( popd & pause & exit /b 1 )
  if exist public rmdir /s /q public
  xcopy /e /i /q dist public >nul
  popd
)

echo ==^> [3/3] 启动服务：http://localhost:8000
python backend\main.py
pause
