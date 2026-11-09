"""Build the Windows x64 portable edition on Windows (no Python needed by users)."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from package_common import ROOT, release_resources, windows_native_resources

if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
    raise SystemExit("Run this script with 64-bit Python on Windows, or use the GitHub release workflow.")
os.chdir(ROOT)
version = (ROOT / "VERSION").read_text().strip()
subprocess.run([sys.executable, "scripts/make_icon.py"], check=True)
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
    "--name", "jiji-engine", "--icon", "build/AppIcon.ico", "--add-data", "web:web", "--add-data", "VERSION:.",
    "--collect-all", "pymupdf", "--copy-metadata", "PyMuPDF", "--copy-metadata", "Pillow",
    "--distpath", "build/windows-dist", "--workpath", "build/windows-pyinstaller", "server.py"], check=True)
native = ROOT / "build/windows-native"
if native.exists():
    shutil.rmtree(native)
subprocess.run(["dotnet", "publish", "scripts/windows-native/JijiEditor.csproj", "--configuration", "Release",
                "--runtime", "win-x64", "--self-contained", "true", "-p:PublishSingleFile=false",
                "-p:PublishTrimmed=false", "--output", str(native), f"-p:Version={version}",
                f"-p:FileVersion={version}.0"], check=True)
for filename in ["JijiEditor.exe", "JijiEditor.dll", "JijiEditor.runtimeconfig.json", "coreclr.dll",
                 "hostfxr.dll", "hostpolicy.dll", "System.Private.CoreLib.dll", "System.Windows.Forms.dll",
                 "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"]:
    if not (native / filename).is_file():
        raise RuntimeError(f"The Windows native build is missing {filename}.")
if not any(native.rglob("WebView2Loader.dll")):
    raise RuntimeError("The Windows native build is missing the WebView2 native loader.")
package = ROOT / "output/JijiEditor-Windows-x64"
if package.exists():
    shutil.rmtree(package)
shutil.copytree(native, package)
shutil.copytree(ROOT / "build/windows-dist/jiji-engine", package / "backend")
release_resources(package)
windows_native_resources(package, ROOT / "scripts/windows-native/obj/project.assets.json")
(package / "先读我.txt").write_text(
    "吉吉编辑软件 · Windows 64 位版\n\n"
    "1. 将 ZIP 完整解压到普通文件夹，双击 JijiEditor.exe，直接进入独立的编辑器窗口。\n"
    "2. 已自带 .NET、WebView2 和 Python，无需另装运行环境或浏览器。保留整个文件夹，不要单独移动 EXE。\n"
    "3. 点击“导出 PDF”后，在系统“另存为”窗口选择文件位置。关闭软件前请先导出需要保留的修改。\n"
    "4. 支持 Windows 10 22H2/Windows 11 64 位。请解压到本地普通文件夹，不要放在网络共享路径。\n"
    "   内嵌显示组件 WebView2 随软件提供并更新；首次启动和编辑都不需要联网安装。\n"
    "   .NET、WebView2 SDK 和固定运行时各自的原始许可见 licenses/，使用相应组件须遵守其条款。\n"
    "   WebView2 原始第三方声明可通过 webview2/show_third_party_software_licenses.bat 查看。\n"
    "5. 转换 Word、Excel、PPT 需要独立安装免费的 LibreOffice。\n\n"
    "文档在本机处理，编辑无需联网。窗口关闭时会结束本次本地处理服务。\n",
    encoding="utf-8-sig")
archive = shutil.make_archive(str(ROOT / f"output/JijiEditor-{version}-Windows-x64"), "zip", package.parent, package.name)
print(archive)
