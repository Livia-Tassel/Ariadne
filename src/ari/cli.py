"""ari 命令行入口。见 spec §4。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from .board import render_markdown
from .drafts import with_errors
from .editor import EditorUnavailable, edit_text
from .events import Event, append_event, read_events
from .ingest import build_manual_draft, discover, parse_manual, parse_result_file
from .planning import (
    ValidationFailed,
    build_design_draft,
    build_events,
    build_prediction_draft,
    expand_runs,
    next_batch_id,
    parse_design,
    parse_predictions,
)
from .project import project as project_events

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


@app.command()
def board(
    project_dir: str = typer.Option(".", "--project", "-p", help="项目目录"),
    write: bool = typer.Option(True, help="同时写出 board.md"),
) -> None:
    """渲染看板。board.md 是派生产物，可随时重新生成。"""
    root = Path(project_dir)
    events, parse_errors = read_events(root / "runs.jsonl")
    batches, warnings = project_events(events)
    markdown = render_markdown(batches, warnings, parse_errors)

    if write:
        (root / "board.md").write_text(markdown, encoding="utf-8")

    Console().print(Markdown(markdown))


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _edit_until_valid(draft: str, parse, name: str):
    """反复编辑直到校验通过。

    校验不过时把用户填的原文连同错误注释一起送回编辑器——绝不丢内容，
    也绝不让人从头再填一遍。用户清空文件表示放弃，返回 None。
    """
    text = draft
    while True:
        edited = edit_text(text, name=name)
        if edited is None:
            return None
        try:
            return parse(edited)
        except ValidationFailed as exc:
            text = with_errors(edited, exc.errors)


def _parse_dims(specs: list[str]) -> dict[str, list[str]]:
    """把 --dims "model=base,large" 解析成 {"model": ["base", "large"]}。"""
    dimensions: dict[str, list[str]] = {}
    for spec in specs:
        name, sep, values = spec.partition("=")
        if not sep or not values.strip():
            raise typer.BadParameter(f"--dims 应该形如 name=v1,v2，收到 {spec!r}")
        dimensions[name.strip()] = [v.strip() for v in values.split(",") if v.strip()]
    return dimensions


@app.command()
def plan(
    project_dir: str = typer.Option(".", "--project", "-p", help="项目目录"),
    dims: list[str] = typer.Option(
        None, "--dims", help='预置变量维度，形如 --dims "model=base,large"，可重复'
    ),
) -> None:
    """开启一个批次：写假设、声明变量维度、填预测表并锁定。"""
    root = Path(project_dir)
    runs_path = root / "runs.jsonl"
    events, _ = read_events(runs_path)
    batches, _ = project_events(events)
    batch_id = next_batch_id(batches)

    draft = build_design_draft(batch_id)
    if dims:
        draft = _preset_dimensions(draft, _parse_dims(dims))

    try:
        design = _edit_until_valid(draft, parse_design, name=f"plan-{batch_id}-design")
        if design is None:
            typer.echo("已放弃，没有写入任何内容。")
            return

        runs = expand_runs(design.dimensions)
        typer.echo(f"批次 {batch_id}：{len(runs)} 个 run，接下来填预测表。")

        predictions = _edit_until_valid(
            build_prediction_draft(design, runs, batch_id),
            lambda text: parse_predictions(text, design, runs),
            name=f"plan-{batch_id}-predictions",
        )
    except EditorUnavailable as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if predictions is None:
        typer.echo("已放弃，没有写入任何内容。")
        return

    for event in build_events(batch_id, design, predictions, now=_now()):
        append_event(runs_path, event)

    typer.echo(f"批次 {batch_id} 已锁定，{len(runs)} 条预测已写入。")
    typer.echo("跑完实验后运行 ari result 录入结果。")


def _preset_dimensions(draft: str, dimensions: dict[str, list[str]]) -> str:
    """把命令行给的维度替换进草稿的 dimensions 段。"""
    rendered = ["dimensions:"]
    for name, values in dimensions.items():
        rendered.append(f"  {name}: [{', '.join(values)}]")
    return draft.replace("dimensions:\n  model: [base, large]", "\n".join(rendered))


def _latest_batch(batches: dict, wanted: str | None):
    if not batches:
        typer.echo("这个项目还没有批次。先运行 ari plan 开一个。", err=True)
        raise typer.Exit(code=1)
    if wanted:
        if wanted not in batches:
            typer.echo(f"没有批次 {wanted}。现有：{', '.join(batches)}", err=True)
            raise typer.Exit(code=1)
        return batches[wanted]
    return list(batches.values())[-1]


def _metric_names(batch) -> list[str]:
    """本批次关心哪些指标——以预测表声明的为准。"""
    names: list[str] = []
    for run in batch.runs.values():
        for name in (run.prediction or {}).get("metrics", {}):
            if name not in names:
                names.append(name)
    return names


@app.command()
def result(
    project_dir: str = typer.Option(".", "--project", "-p", help="项目目录"),
    batch_id: str = typer.Option(None, "--batch", "-b", help="批次 id，默认最新的"),
    manual: bool = typer.Option(False, "--manual", help="强制手工填写，不自动发现文件"),
) -> None:
    """录入实测结果：按 result_path 模板自动发现，或手工填写。"""
    root = Path(project_dir)
    runs_path = root / "runs.jsonl"
    events, _ = read_events(runs_path)
    batches, _ = project_events(events)
    batch = _latest_batch(batches, batch_id)

    runs = list(batch.runs)
    metrics = _metric_names(batch)
    if not metrics:
        typer.echo(f"批次 {batch.id} 还没有预测，先运行 ari plan。", err=True)
        raise typer.Exit(code=1)

    if manual or not batch.result_path:
        parsed = _collect_manually(batch, runs, metrics)
    else:
        parsed = _collect_from_files(root, batch, runs, metrics)

    if not parsed:
        return
    if not _confirm(parsed, batch):
        typer.echo("没有写入任何内容。")
        return

    for item in parsed:
        append_event(
            runs_path,
            Event(
                ts=_now(),
                type="run_result",
                batch=batch.id,
                run=item.run,
                payload={
                    "seed": item.seed,
                    "metrics": item.metrics,
                    "source": {
                        "path": str(item.path.relative_to(root)) if item.path else None,
                        "kind": item.kind,
                        "mtime": item.mtime or None,
                    },
                },
            ),
        )

    typer.echo(f"已写入 {len(parsed)} 条结果。运行 ari board 看判定。")


def _collect_from_files(root: Path, batch, runs: list[str], metrics: list[str]):
    found, unmatched = discover(root, batch.result_path, runs)

    if unmatched:
        typer.echo("这些文件路径对得上模板，但不属于本批次的任何 run：")
        for path in unmatched:
            typer.echo(f"  {path}")
        typer.echo("（模板写错了？还是跑了计划外的配置？）\n")

    if not found:
        typer.echo(f"按模板 {batch.result_path} 没找到结果文件。")
        typer.echo("跑完实验了吗？或者用 ari result --manual 手工填。")
        return []

    parsed = []
    for item in found:
        one = parse_result_file(item.path, metrics)
        one.run, one.seed = item.run, item.seed
        parsed.append(one)
    return parsed


def _collect_manually(batch, runs: list[str], metrics: list[str]):
    draft = build_manual_draft(runs, metrics, batch.id)
    try:
        text = edit_text(draft, name=f"result-{batch.id}")
    except EditorUnavailable as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if text is None:
        typer.echo("已放弃，没有写入任何内容。")
        return []
    try:
        return parse_manual(text, runs, metrics)
    except ValueError as exc:
        typer.echo(f"填写有问题：{exc}", err=True)
        raise typer.Exit(code=1) from exc


def _confirm(parsed, batch) -> bool:
    """抽到的结果先给人看一眼。错误的指标进表比缺失指标更有害。"""
    table = Table(title=f"批次 {batch.id}：抽到了这些，对吗？", box=box.SIMPLE)
    table.add_column("run")
    table.add_column("seed", justify="right")
    table.add_column("指标")
    table.add_column("来源")

    notes = set()
    for item in parsed:
        values = "  ".join(f"{k}={v:g}" for k, v in item.metrics.items())
        if item.missing:
            values += f"   [缺失: {', '.join(item.missing)}]"
        source = str(item.path.name) if item.path else "手工填写"
        table.add_row(item.run, str(item.seed), values or "—", source)
        if item.note:
            notes.add(item.note)

    console = Console()
    console.print(table)
    for note in sorted(notes):
        console.print(f"[dim]{note}[/dim]")

    return typer.confirm("写入？", default=True)
