@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==^> 检查前端产物
if not exist "frontend\public\index.html" (
  echo 未找到 frontend\public，正在构建前端...
  pushd frontend
  call npm install --no-fund --no-audit || (popd & pause & exit /b 1)
  call npm run build || (popd & pause & exit /b 1)
  if exist public rmdir /s /q public
  xcopy /e /i /q dist public >nul
  popd
)

echo ==^> 检查应用图标
if not exist "assets\icon.ico" (
  echo 未找到 assets\icon.ico，正在生成...
  python tools\make_icon.py || (echo 图标生成失败 & pause & exit /b 1)
)

echo ==^> 安装依赖（如未安装）
python -m pip install -q pyinstaller pywebview pillow

echo ==^> 打包为独立窗口桌面应用（无控制台、带图标）
rem 注意：--specpath 会使相对路径按 spec 目录解析，资源一律用 %~dp0 绝对路径
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name BranchChatCanvas ^
  --icon "%~dp0assets\icon.ico" ^
  --add-data "%~dp0frontend\public;frontend\public" ^
  --add-data "%~dp0assets;assets" ^
  --collect-all webview ^
  --collect-all pythonnet ^
  --collect-all clr_loader ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  --distpath dist-exe --workpath build\pyinstaller --specpath build ^
  backend\app_desktop.py
if errorlevel 1 ( echo 打包失败 & pause & exit /b 1 )

echo.
echo ==^> 完成：dist-exe\BranchChatCanvas.exe
echo     双击运行：打开独立应用窗口（不依赖浏览器）
echo     首次启动约需 5-10 秒
pause
