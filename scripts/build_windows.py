"""Build the Windows x64 portable edition on Windows (no Python needed by users)."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from package_common import ROOT, release_resources

if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
    raise SystemExit("Run this script with 64-bit Python on Windows, or use the GitHub release workflow.")
os.chdir(ROOT)
subprocess.run([sys.executable, "scripts/make_icon.py"], check=True)
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
    "--name", "JijiEditor", "--icon", "build/AppIcon.ico", "--add-data", "web:web", "--add-data", "VERSION:.",
    "--collect-all", "pymupdf", "--copy-metadata", "PyMuPDF", "--copy-metadata", "Pillow",
    "--distpath", "build/windows-dist", "--workpath", "build/windows-pyinstaller", "windows_launcher.py"], check=True)
package = ROOT / "output/JijiEditor-Windows-x64"
if package.exists():
    shutil.rmtree(package)
shutil.copytree(ROOT / "build/windows-dist/JijiEditor", package)
release_resources(package)
(package / "先读我.txt").write_text("吉吉编辑软件\n\n解压整个文件夹后，双击 JijiEditor.exe。编辑器会在默认浏览器打开。\n保留 _internal 文件夹，不要单独移动 EXE。\n无需安装 Python。转换 Word、Excel、PPT 需要独立安装免费的 LibreOffice。\n文档仅在本机处理。结束前先导出 PDF，再从启动窗口退出。\n", encoding="utf-8-sig")
version = (ROOT / "VERSION").read_text().strip()
archive = shutil.make_archive(str(ROOT / f"output/JijiEditor-{version}-Windows-x64"), "zip", package.parent, package.name)
print(archive)
