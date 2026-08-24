"""$EDITOR 调用的唯一入口。

整个项目里只有这个函数会打开编辑器，其余模块全是纯函数。测试时
monkeypatch 这一处即可，不需要为了测业务逻辑去伪造一个终端。

自己实现而不用 click.edit：typer 0.27 起不再依赖 click，为一个函数
引入依赖不划算；而且自己实现可以给临时文件起有意义的名字，编辑器的
标题栏会显示它（`plan-b1.yaml` 比 `tmpx8f2a1.yaml` 有用得多）。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path


class EditorUnavailable(RuntimeError):
    """打不开编辑器。"""


def _editor_command() -> list[str]:
    raw = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not raw:
        # 兜底：几乎所有类 Unix 系统都有 vi
        raw = "vi"
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        raise EditorUnavailable(f"EDITOR 的值无法解析：{raw!r}（{exc}）") from exc
    if not parts:
        raise EditorUnavailable("EDITOR 是空的")
    return parts


def edit_text(initial: str, name: str = "draft", suffix: str = ".yaml") -> str | None:
    """打开编辑器编辑一段文本。

    name 会成为临时文件名的一部分，方便用户在编辑器里认出自己在编什么。

    返回编辑后的内容；用户未做改动或把内容清空时返回 None
    （两种情况都按「放弃」处理）。
    """
    command = _editor_command()

    with tempfile.TemporaryDirectory(prefix="ari-") as tmpdir:
        path = Path(tmpdir) / f"{name}{suffix}"
        path.write_text(initial, encoding="utf-8")
        try:
            subprocess.run([*command, str(path)], check=True)
        except FileNotFoundError as exc:
            raise EditorUnavailable(
                f"找不到编辑器 {command[0]!r}。请设置 EDITOR 环境变量，"
                f"例如 export EDITOR=vim"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise EditorUnavailable(f"编辑器 {command[0]!r} 非正常退出（{exc}）") from exc
        edited = path.read_text(encoding="utf-8")

    if not edited.strip() or edited == initial:
        return None
    return edited
