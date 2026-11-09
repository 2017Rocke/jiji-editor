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
subprocess.run(["dotnet", "build", "scripts/windows-native/JijiEditor.csproj", "--configuration", "Release",
                "--output", str(native), f"-p:Version={version}", f"-p:FileVersion={version}.0"], check=True)
for filename in ["JijiEditor.exe", "JijiEditor.exe.config", "Microsoft.Web.WebView2.Core.dll",
                 "Microsoft.Web.WebView2.WinForms.dll"]:
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
    "2. 无需选择或打开浏览器，无需安装 Python。保留 backend、runtimes（如有）及所有 DLL，不要单独移动 EXE。\n"
    "3. 点击“导出 PDF”后，在系统“另存为”窗口选择文件位置。关闭软件前请先导出需要保留的修改。\n"
    "4. 支持 Windows 10/11 64 位，需要 .NET Framework 4.8 和 Microsoft WebView2 Runtime。\n"
    "   WebView2 是软件内嵌的网页显示组件，不需要更改默认浏览器或安装 Microsoft Edge 浏览器。\n"
    "   如果电脑缺少此组件，按窗口提示安装包内 WebView2Setup.exe；首次安装需要联网，完成后重新打开软件。\n"
    "   安装程序来自微软官方，构建时已核验有效的微软数字签名；运行时由微软单独维护和更新。\n"
    "   WebView2 官方信息及运行时下载/许可：https://developer.microsoft.com/microsoft-edge/webview2/\n"
    "   SDK 原始许可及第三方声明见 licenses/Microsoft.Web.WebView2/。\n"
    "5. 转换 Word、Excel、PPT 需要独立安装免费的 LibreOffice。\n\n"
    "文档在本机处理，编辑无需联网。窗口关闭时会结束本次本地处理服务。\n",
    encoding="utf-8-sig")
archive = shutil.make_archive(str(ROOT / f"output/JijiEditor-{version}-Windows-x64"), "zip", package.parent, package.name)
print(archive)
