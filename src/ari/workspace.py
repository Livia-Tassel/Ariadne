"""项目目录的创建逻辑，供 CLI 与 GUI 共用。"""

from __future__ import annotations

from pathlib import Path


CONFIG_TEMPLATE = """\
# 本文件会进 git —— 只放平台地址与环境变量名，绝不放密钥。
#
# 整份配置都是可选的。删掉这个文件，或者不设下面这些环境变量，
# ari 的每一条命令都照常工作，只是没有 AI 那一段。

[providers.openai]
base_url = "https://api.deepseek.com"
api_key_env = "OPENAI_API_KEY"

[providers.anthropic]
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"

[roles]
# 复盘追问与 plan 阶段的定性判断。
reason = "openai:deepseek-v4-pro"
# 日志抽取，v0.2 未启用（见 spec §5.3）
# extract = "openai:gpt-5.5"

[openalex]
# 领域调研的数据源。不需要 API key；填邮箱只是进入 OpenAlex 的礼貌池，
# 不填也能用。限流是信用点制，界面上会显示剩余额度。
mailto = ""
"""


def initialize_project(path: str | Path, *, exist_ok: bool = False) -> Path:
    """创建一个项目骨架。

    GUI 使用 ``exist_ok=True``，这样用户可以直接打开一个新目录；CLI init
    保持原来的防覆盖行为。已有配置绝不重写。
    """
    root = Path(path).expanduser().resolve()
    runs = root / "runs.jsonl"
    if runs.exists() and not exist_ok:
        raise FileExistsError(runs)

    (root / "logs").mkdir(parents=True, exist_ok=True)
    runs.touch(exist_ok=True)
    config = root / "config.toml"
    if not config.exists():
        config.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return root
