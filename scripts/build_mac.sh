#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${JIJI_PYTHON:-.venv/bin/python}"
APP="output/吉吉编辑软件.app"
APP_VERSION="$(tr -d '\r\n' < VERSION)"
APP_ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"
"$PYTHON" -m PyInstaller --noconfirm --clean --name jiji-engine --onedir \
  --add-data 'web:web' --add-data 'VERSION:.' --collect-all pymupdf --copy-metadata PyMuPDF --copy-metadata Pillow \
  --distpath build/dist --workpath build/pyinstaller server.py
"$PYTHON" scripts/make_icon.py
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
rm -rf "$APP/Contents/Resources/backend"
cp -R build/dist/jiji-engine "$APP/Contents/Resources/backend"
swiftc -O -target "$APP_ARCH-apple-macosx13.0" -module-cache-path build/swift-cache scripts/MacApp.swift -o "$APP/Contents/MacOS/JijiEditor" -framework AppKit -framework WebKit
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>吉吉编辑软件</string>
<key>CFBundleDisplayName</key><string>吉吉编辑软件</string>
<key>CFBundleIdentifier</key><string>cn.jiji.pdfeditor</string>
<key>CFBundleVersion</key><string>$APP_VERSION</string>
<key>CFBundleShortVersionString</key><string>$APP_VERSION</string>
<key>CFBundleExecutable</key><string>JijiEditor</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
if [ -f build/AppIcon.icns ]; then cp build/AppIcon.icns "$APP/Contents/Resources/"; fi
"$PYTHON" scripts/package_common.py "$APP/Contents/Resources"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "output/JijiEditor-$APP_VERSION-macOS-$APP_ARCH.zip"
echo "Built: $APP ($APP_ARCH)"
