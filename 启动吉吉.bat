@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "output\JijiEditor-Windows-x64\JijiEditor.exe" (
  start "" "output\JijiEditor-Windows-x64\JijiEditor.exe"
  exit /b
)
echo 请下载 Releases 中的 Windows 独立窗口安装包，或按 docs/DEVELOPMENT.md 构建。
pause
exit /b 1
