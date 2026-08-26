#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
BUILD_DIR="$ROOT/build/macos"
ICONSET="$BUILD_DIR/Ariadne.iconset"
SOURCE_ICON="$ROOT/assets/ariadne-app-icon.svg"
PYTHON_BIN=${ARIADNE_BUILD_PYTHON:-"$ROOT/.venv/bin/python"}

if [ ! -x "$PYTHON_BIN" ]; then
    echo "找不到构建环境。先运行：uv sync --extra desktop --group package" >&2
    exit 1
fi

rm -rf "$BUILD_DIR" "$ROOT/build/bdist.macosx-*" "$ROOT/dist/Ariadne.app"
mkdir -p "$ICONSET"

sips -s format png "$SOURCE_ICON" --out "$BUILD_DIR/icon_1024.png" >/dev/null
for size in 16 32 128 256 512; do
    double=$((size * 2))
    sips -z "$size" "$size" "$BUILD_DIR/icon_1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z "$double" "$double" "$BUILD_DIR/icon_1024.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD_DIR/Ariadne.icns"

cd "$ROOT/packaging/macos"
"$PYTHON_BIN" setup.py py2app \
    --bdist-base "$ROOT/build/py2app" \
    --dist-dir "$ROOT/dist"

# iCloud/File Provider 工作区可能给新 bundle 继承 FinderInfo，严格签名校验会拒绝。
xattr -cr "$ROOT/dist/Ariadne.app"
xattr -d com.apple.FinderInfo "$ROOT/dist/Ariadne.app" 2>/dev/null || true
xattr -d 'com.apple.fileprovider.fpfs#P' "$ROOT/dist/Ariadne.app" 2>/dev/null || true
codesign --force --deep --sign - "$ROOT/dist/Ariadne.app" >/dev/null

echo "构建完成：$ROOT/dist/Ariadne.app"
