"""构建独立的 Ariadne.app。

运行：.venv/bin/python packaging/macos/setup.py py2app
"""

import sys
from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "build" / "macos" / "Ariadne.icns"
PYTHON_LIB = Path(sys.base_prefix) / "lib"
RUNTIME_LIBS = [
    PYTHON_LIB / name
    for name in (
        "libbz2.dylib",
        "libcrypto.3.dylib",
        "libexpat.1.dylib",
        "libffi.8.dylib",
        "liblzma.5.dylib",
        "libmpdec.4.dylib",
        "libssl.3.dylib",
        "libz.1.dylib",
    )
    if (PYTHON_LIB / name).exists()
]

OPTIONS = {
    "argv_emulation": False,
    "packages": ["webview"],
    "includes": [
        "webview.platforms.cocoa",
        "WebKit",
        "Foundation",
        "Cocoa",
        "Quartz",
        "Security",
    ],
    "excludes": [
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "pytest",
        "_pytest",
        "setuptools",
        "webview.platforms.winforms",
        "webview.platforms.mshtml",
        "webview.platforms.cef",
        "webview.platforms.gtk",
        "webview.platforms.qt",
    ],
    "iconfile": str(ICON) if ICON.exists() else None,
    "resources": [
        str(ROOT / "src" / "ari" / "desktopui"),
        str(ROOT / "src" / "ari" / "webui"),
    ],
    # Conda Python 的扩展使用 @rpath 链接这些库，py2app 不会自动收集。
    "frameworks": [str(path) for path in RUNTIME_LIBS],
    # py2app 0.28.10 + Python 3.13 在 -O1 下会生成指向不存在 site.pyo 的链接。
    "optimize": 0,
    "plist": {
        "CFBundleName": "Ariadne",
        "CFBundleDisplayName": "Ariadne",
        "CFBundleIdentifier": "ai.openai.ariadne",
        "CFBundleShortVersionString": "0.4.0",
        "CFBundleVersion": "4",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Ariadne local-first research workspace",
    },
}

setup(
    name="Ariadne",
    version="0.4.0",
    description="实验预测、记录与复盘桌面工作台",
    app=["Ariadne.py"],
    package_dir={"": "../../src"},
    packages=find_packages(str(ROOT / "src")),
    # webui/* 匹配不到 webui/lib/dom.js：前端已拆成 lib/ views/ parts/ 子目录。
    package_data={"ari": ["webui/*", "webui/*/*", "desktopui/*"]},
    include_package_data=True,
    options={"py2app": OPTIONS},
)
