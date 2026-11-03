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

echo ==^> 安装 PyInstaller（如未安装）
python -m pip install -q pyinstaller

echo ==^> 打包为单个 exe
python -m PyInstaller --noconfirm --clean --onefile ^
  --name BranchChatCanvas ^
  --add-data "frontend/public;frontend/public" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  --distpath dist-exe --workpath build\pyinstaller --specpath build ^
  backend\desktop.py
if errorlevel 1 ( echo 打包失败 & pause & exit /b 1 )

echo.
echo ==^> 完成：dist-exe\BranchChatCanvas.exe
echo     双击即可运行，首次启动约需 3-8 秒
pause
