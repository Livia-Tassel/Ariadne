"""ari result：结果文件的发现与解析。见 spec §5。

v1 只做确定性解析，不调用 LLM。对齐靠 plan 阶段声明的 result_path 模板
反解出 (run, seed)——上一版设想的「依据训练脚本命令行参数自动对齐」依赖
日志里打印了完整命令行，很多脚本不打；模板方式把这件事前置成一次性声明。

抽到的结果不直接落盘，先给人看一眼再确认：错误的指标进表比缺失指标更有害。
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .drafts import parse_number
from .runkey import make_run_key

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class FoundFile:
    run: str
    seed: int
    path: Path


@dataclass
class ParsedResult:
    run: str
    seed: int
    metrics: dict[str, float]
    missing: list[str] = field(default_factory=list)
    kind: str = "structured"
    path: Path | None = None
    mtime: str = ""
    note: str = ""


def compile_template(template: str) -> re.Pattern:
    """把 logs/{model}_{lr}/s{seed}/results.json 编译成带命名组的正则。

    变量不跨路径分隔符，否则 `logs/a/b_1e-3/...` 会被错误地匹配上。
    """
    pieces = []
    last = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        pieces.append(re.escape(template[last : match.start()]))
        pieces.append(f"(?P<{match.group(1)}>[^/]+)")
        last = match.end()
    pieces.append(re.escape(template[last:]))
    return re.compile("^" + "".join(pieces) + "$")


def discover(
    root: Path, template: str, runs: list[str]
) -> tuple[list[FoundFile], list[str]]:
    """在 root 下按模板找结果文件。

    返回 (对上号的文件, 形状对但对不上任何 run 的路径)。后者明确列出，
    不静默跳过——多半意味着模板写错了或者跑了计划外的配置。
    """
    pattern = compile_template(template)
    known = set(runs)
    found: list[FoundFile] = []
    unmatched: list[str] = []

    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        match = pattern.match(relative)
        if not match:
            continue
        variables = match.groupdict()
        seed = variables.pop("seed", None)
        run = make_run_key(variables)
        if run not in known:
            unmatched.append(relative)
            continue
        found.append(FoundFile(run=run, seed=int(seed) if seed is not None else 0, path=path))

    return found, unmatched


def _lookup(data: dict, name: str):
    """先找顶层，再找点号路径，最后在一层嵌套里找同名键。"""
    if name in data:
        return data[name]

    if "." in name:
        cursor = data
        for part in name.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return None
            cursor = cursor[part]
        return cursor

    for value in data.values():
        if isinstance(value, dict) and name in value:
            return value[name]
    return None


def _mtime(path: Path) -> str:
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return stamp.astimezone().replace(microsecond=0).isoformat()


def parse_result_file(path: Path, metric_names: list[str]) -> ParsedResult:
    """从一个结果文件里取出关心的指标。取不到的明确报告，不填空。"""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path} 的顶层不是一个对象")
        lookup = lambda name: _lookup(raw, name)  # noqa: E731
        note = ""
    elif suffix == ".csv":
        rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        last = rows[-1] if rows else {}
        lookup = last.get
        note = "CSV 取的是最后一行" if rows else ""
    else:
        raise ValueError(f"不认识的结果文件格式 {suffix!r}：{path}（支持 .json / .csv）")

    metrics: dict[str, float] = {}
    missing: list[str] = []
    for name in metric_names:
        value = lookup(name)
        if value is None:
            missing.append(name)
            continue
        try:
            metrics[name] = parse_number(value)
        except ValueError:
            missing.append(name)

    return ParsedResult(
        run="",
        seed=0,
        metrics=metrics,
        missing=missing,
        kind="structured",
        path=path,
        mtime=_mtime(path),
        note=note,
    )


_MANUAL_HEADER = """\
# ── {title} ────────────────────────────────────────────────────────
# 填实测值。同一配置跑了多个 seed 就复制该行、改 seed 号——
# 多个 seed 的离散程度就是噪声基线，只跑一个 seed 时判定无法校准。
# 留空的条目会被跳过，不会写入。
# 想放弃就清空整个文件再保存。

results:
"""


def build_manual_draft(runs: list[str], metric_names: list[str], batch_id: str = "") -> str:
    title = f"批次 {batch_id} 的结果录入" if batch_id else "结果录入"
    lines = [_MANUAL_HEADER.format(title=title)]
    for run in runs:
        lines.append(f"  - run: {run}")
        lines.append("    seed: 0")
        for metric in metric_names:
            lines.append(f"    {metric}:")
        lines.append("")
    return "\n".join(lines)


def parse_manual(text: str, runs: list[str], metric_names: list[str]) -> list[ParsedResult]:
    """解析手填草稿。整条留空的跳过；run 名不认识的报错。"""
    data = yaml.safe_load(text) or {}
    entries = data.get("results") or []
    known = set(runs)
    parsed: list[ParsedResult] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        run = entry.get("run")
        if not run:
            continue
        if run not in known:
            raise ValueError(f"run {run!r} 不在这个批次的变量组合里")

        metrics = {}
        for name in metric_names:
            raw = entry.get(name)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            metrics[name] = parse_number(raw)
        if not metrics:
            continue

        parsed.append(
            ParsedResult(
                run=run,
                seed=int(entry.get("seed") or 0),
                metrics=metrics,
                kind="manual",
                mtime="",
            )
        )
    return parsed
