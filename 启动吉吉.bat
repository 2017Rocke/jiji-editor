@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "output\JijiEditor-Windows-x64\JijiEditor.exe" (
  start "" "output\JijiEditor-Windows-x64\JijiEditor.exe"
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  echo 请下载 Releases 中的 Windows 免安装包，或按 README 安装源码依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" server.py
