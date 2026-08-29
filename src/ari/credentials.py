"""密钥与用户级设置。

**密钥永远不进项目目录。** `config.toml` 与 `runs.jsonl` 都会进 git——
把 key 写进去就等于把它提交进仓库。所以存在应用数据目录（macOS 是
~/Library/Application Support/Ariadne），权限 0600。

这也更符合事实：API key 是**你的**，不是某个项目的。一次填好，所有项目
都能用。

按**环境变量名**存，不按 provider 存：config.toml 里已经是「provider →
环境变量名」的映射，按同一个名字存就是环境变量的一个直接替补，任何
provider 配置都自动适用。

环境变量优先于这里存的值——那是 CI 与自动化的路径，显式且不该被一个
GUI 里填的东西盖掉。
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

_SECTION = "env"
_SETTINGS = "settings"


def application_data_dir() -> Path:
    """符合当前操作系统习惯的应用数据目录。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Ariadne"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "Ariadne"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ariadne"


def credentials_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else application_data_dir() / "credentials.toml"


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        # 读不了就当作没有。密钥缺失本来就是常态，不该让整个应用起不来。
        return {}


def load_secrets(path: str | Path | None = None) -> dict[str, str]:
    """环境变量名 → 值。"""
    raw = _read(credentials_path(path)).get(_SECTION) or {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v.strip()}


def load_settings(path: str | Path | None = None) -> dict[str, str]:
    """非密钥的用户级设置，例如 OpenAlex 的 mailto。"""
    raw = _read(credentials_path(path)).get(_SETTINGS) or {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def secret_for(env_name: str, path: str | Path | None = None) -> str:
    """取一个密钥。环境变量优先——那是 CI 与自动化的显式路径。"""
    if not env_name:
        return ""
    return os.environ.get(env_name) or load_secrets(path).get(env_name, "")


def _dump(mapping: dict[str, dict[str, str]]) -> str:
    """写一份最小的 TOML。值里的反斜杠与引号要转义。

    不引 tomli-w：这个文件的结构是我们自己定的两段扁平表，为它加一个
    依赖不划算——与 llm/__init__.py 拒绝为一个够用的 schema 子集引入
    jsonschema 是同一笔账。
    """
    lines = ["# Ariadne 的密钥与用户级设置。", "# 这个文件不属于任何项目，也不应进入版本库。", ""]
    for section, values in mapping.items():
        if not values:
            continue
        lines.append(f"[{section}]")
        for key, value in sorted(values.items()):
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        lines.append("")
    return "\n".join(lines)


def save(
    secrets: dict[str, str] | None = None,
    settings: dict[str, str] | None = None,
    path: str | Path | None = None,
) -> Path:
    """合并写入。值为空字符串表示删除该项。

    权限 0600：这个文件里是明文密钥，同机其他用户不该读得到。
    """
    target = credentials_path(path)
    merged_secrets = load_secrets(target)
    merged_settings = load_settings(target)
    for key, value in (secrets or {}).items():
        if value:
            merged_secrets[key] = value
        else:
            merged_secrets.pop(key, None)
    for key, value in (settings or {}).items():
        if value:
            merged_settings[key] = value
        else:
            merged_settings.pop(key, None)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _dump({_SECTION: merged_secrets, _SETTINGS: merged_settings}), encoding="utf-8"
    )
    try:
        target.chmod(0o600)
    except OSError:
        # 某些文件系统（网络盘、FAT）不支持改权限。写入本身已经成功，
        # 不该因此失败——但这件事值得让调用方知道，见 web.settings()。
        pass
    return target


def mask(value: str) -> str:
    """给人看的形式。永远不把完整密钥回传给界面。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "…" * 3
    return f"{value[:3]}…{value[-4:]}"
