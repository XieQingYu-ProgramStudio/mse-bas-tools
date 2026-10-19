#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "找不到 Python 虚拟环境：$PYTHON" >&2
  exit 1
fi

VERSION="$("$PYTHON" -c 'from tcc_permission_assistant import __version__; print(__version__)')"
BUILD_DIR="$ROOT/build/packaging"
PYI_DIST="$BUILD_DIR/pyinstaller-dist"
APP_ASCII="$PYI_DIST/YuexingBASToolbox.app"
APP_FINAL="$ROOT/dist/月星BAS工具箱.app"
ICON_MASTER="$ROOT/packaging/AppIcon-1024.png"
ICONSET="$ROOT/packaging/AppIcon.iconset"
ICNS="$ROOT/packaging/AppIcon.icns"
DMG_STAGE="$BUILD_DIR/dmg-stage"
DMG_PATH="$ROOT/dist/月星BAS工具箱-$VERSION.dmg"

echo "准备应用图标"
"$PYTHON" "$ROOT/packaging/make_icon.py"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$ICON_MASTER" \
    --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$ICON_MASTER" \
    --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICNS"

echo "清理旧的构建产物"
rm -rf "$BUILD_DIR" "$APP_FINAL" "$DMG_PATH"
mkdir -p "$PYI_DIST" "$ROOT/dist"

echo "使用 PyInstaller 打包 $VERSION"
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "YuexingBASToolbox" \
  --osx-bundle-identifier "com.yuexing.bastoolbox" \
  --icon "$ICNS" \
  --paths "$ROOT" \
  --add-data "$ROOT/tcc_permission_assistant/gui/icons:tcc_permission_assistant/gui/icons" \
  --add-data "$ROOT/tcc_permission_assistant/gui/assets:tcc_permission_assistant/gui/assets" \
  --add-data "$ROOT/oc_theme:oc_theme" \
  --distpath "$PYI_DIST" \
  --workpath "$BUILD_DIR/pyinstaller" \
  --specpath "$BUILD_DIR" \
  "$ROOT/tcc_permission_assistant/app.py"

mv "$APP_ASCII" "$APP_FINAL"
"$PYTHON" "$ROOT/packaging/finalize_app.py" "$APP_FINAL" "$VERSION"

echo "临时签名"
codesign --force --deep --sign - "$APP_FINAL"
codesign --verify --deep --strict "$APP_FINAL"

echo "生成 DMG"
mkdir -p "$DMG_STAGE"
ditto "$APP_FINAL" "$DMG_STAGE/月星BAS工具箱.app"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create \
  -volname "月星BAS工具箱" \
  -srcfolder "$DMG_STAGE" \
  -ov \
  -format UDZO \
  "$DMG_PATH"
hdiutil verify "$DMG_PATH"

echo "APP=$APP_FINAL"
echo "DMG=$DMG_PATH"
shasum -a 256 "$DMG_PATH"

