"""定位源码、wheel 与 macOS .app 中的静态资源。"""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path


def asset_file(group: str, name: str):
    """返回一项界面资源。

    ``name`` 可以带 ``/``（如 ``lib/dom.js``）——前端拆成了多个 ES 模块。
    调用方负责校验 name 的合法性，见 ``web._static_target``。

    wheel/源码安装时资源位于 ``ari/<group>``；py2app 会把目录显式复制到
    ``Contents/Resources/<group>``。不能只依赖 importlib.resources，因为
    py2app 的 modulegraph 会把 Python 包放进 zip，却可能丢掉包数据。
    """
    parts = name.split("/")
    executable = Path(sys.executable).resolve()
    if len(executable.parents) >= 2:
        bundled = executable.parents[1] / "Resources" / group
        for part in parts:
            bundled = bundled / part
        if bundled.is_file():
            return bundled
    resource = files("ari").joinpath(group)
    for part in parts:
        resource = resource.joinpath(part)
    return resource
