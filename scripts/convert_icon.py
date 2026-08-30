#!/usr/bin/env python3
"""将 SVG 图标转换成 macOS ``.icns``，只使用系统自带工具。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)



def main() -> int:
    root = Path(__file__).parent.parent
    source_svg = root / "assets" / "ariadne-app-icon.svg"
    build_dir = root / "build" / "macos"
    iconset = build_dir / "Ariadne.iconset"
    iconset.mkdir(parents=True, exist_ok=True)

    base_png = build_dir / "icon_1024.png"
    generated = build_dir / "ariadne-app-icon.svg.png"
    try:
        _run("qlmanage", "-t", "-s", "1024", "-o", str(build_dir), str(source_svg))
        if not generated.exists():
            raise FileNotFoundError(f"qlmanage 未生成 {generated.name}")
        generated.replace(base_png)

        for size in (16, 32, 128, 256, 512):
            for scale, suffix in ((1, ""), (2, "@2x")):
                pixels = size * scale
                target = iconset / f"icon_{size}x{size}{suffix}.png"
                _run(
                    "sips",
                    "-z",
                    str(pixels),
                    str(pixels),
                    str(base_png),
                    "--out",
                    str(target),
                )

        target_icns = build_dir / "Ariadne.icns"
        _run("iconutil", "-c", "icns", str(iconset), "-o", str(target_icns))
        print(f"图标文件已生成：{target_icns}")
        return 0
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"转换失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
