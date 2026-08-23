"""ari 命令行入口。见 spec §4。"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="实验预测、记录与复盘闭环")


@app.callback()
def main() -> None:
    """实验的预测、记录、差异分析与复盘。

    显式声明 callback 让 typer 始终以子命令模式运行，
    否则单命令时会被折叠成裸命令。
    """

CONFIG_TEMPLATE = """\
# 本文件会进 git —— 只放平台地址与环境变量名，绝不放密钥。

[providers.openai]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[providers.anthropic]
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"

[roles]
# 复盘追问与 plan 阶段的定性判断
reason = "anthropic:<strong-model>"
# 日志抽取，v1 暂未启用
extract = "openai:<fast-model>"
"""


@app.command()
def init(path: str = typer.Argument(..., help="项目目录")) -> None:
    """建立项目目录骨架。"""
    project = Path(path)
    runs = project / "runs.jsonl"
    if runs.exists():
        typer.echo(f"{runs} 已存在，拒绝覆盖。", err=True)
        raise typer.Exit(code=1)

    (project / "logs").mkdir(parents=True, exist_ok=True)
    runs.touch()
    (project / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")

    typer.echo(f"已初始化 {project}")
    typer.echo("下一步：ari plan 开启第一个批次（尚未实现，当前可手写 runs.jsonl 后 ari board）")
