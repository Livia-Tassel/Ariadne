"""源码与文案里不该出现替换字符。

U+FFFD 是解码失败的痕迹：某个字节在写入时被截断了。它不会让程序崩溃，
只会在界面上留下「人工改\uFFFD的分层」这种句子——而中文界面里这种损坏
很容易一直没人发现。加这条测试是因为已经发生过一次。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPLACEMENT = chr(0xFFFD)
SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".toml", ".sh"}
SKIP = {".git", ".venv", "dist", "build", "node_modules", "__pycache__", ".superpowers"}


def _sources():
    for path in ROOT.rglob("*"):
        if any(part in SKIP for part in path.parts):
            continue
        if path.is_file() and path.suffix in SUFFIXES:
            yield path


@pytest.mark.parametrize("path", sorted(_sources(), key=str), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_replacement_characters(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    bad = [
        f"第 {i} 行：{line.strip()[:70]}"
        for i, line in enumerate(text.splitlines(), 1)
        if REPLACEMENT in line
    ]
    assert not bad, f"{path.relative_to(ROOT)} 里有替换字符（写入时字节被截断）：\n" + "\n".join(bad)
