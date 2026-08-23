"""看板渲染。见 spec §4。

两条硬要求：
1. 未复盘的 SURPRISE 置顶——这是对抗「跳过思考」的具体机制；
2. 不使用任何暗示「失败」的措辞——负结果与正结果同等重要。

渲染只产出 markdown 字符串：board.md 写它，终端也打印它。单一来源，
避免两套渲染逻辑各自漂移。
"""

from __future__ import annotations

from .project import BatchState
from .verdict import Verdict

_VERDICT_LABEL = {
    Verdict.CONFIRMED: "CONFIRMED 符合预期",
    Verdict.SURPRISE: "SURPRISE 超出预期区间",
    Verdict.NOISY: "NOISY 噪声大于判定分辨率",
    Verdict.NO_RESULT: "NO_RESULT 尚无结果",
    Verdict.UNVERIFIED: "UNVERIFIED 待人工确认",
}


def _format_actual(agg) -> str:
    if agg is None:
        return "—"
    if agg.sd is None:
        return f"{agg.mean:.4g}"
    return f"{agg.mean:.4g} ± {agg.sd:.3g} (n={agg.n})"


def _format_prediction(value) -> str:
    if isinstance(value, (list, tuple)):
        return f"[{float(value[0]):.4g}, {float(value[1]):.4g}]"
    return f"{float(value):.4g}"


def render_markdown(batches: dict[str, BatchState], warnings, parse_errors) -> str:
    lines: list[str] = [
        "# 看板",
        "",
        "> 由 runs.jsonl 派生，可随时用 `ari board` 重新生成。",
        "",
    ]

    pinned = [
        run
        for batch in batches.values()
        for run in batch.runs.values()
        if run.verdict is Verdict.SURPRISE and not run.closed
    ]
    if pinned:
        lines += [f"## 待复盘（{len(pinned)}）", ""]
        for run in pinned:
            lines.append(f"- `{run.batch}` / `{run.run}`")
            for name, judgement in run.metric_judgements.items():
                if judgement.verdict is not Verdict.SURPRISE:
                    continue
                predicted = _format_prediction(run.prediction["metrics"][name])
                actual = _format_actual(run.aggregates.get(name))
                lines.append(f"  - **{name}** 预测 {predicted} → 实测 {actual}")
            rationale = (run.prediction or {}).get("rationale")
            if rationale:
                lines.append(f"  - 当初的理由：{rationale}")
        lines += ["", "运行 `ari review` 逐个处理。", ""]

    for batch in batches.values():
        lines += _render_batch(batch)

    if parse_errors:
        lines += ["## 数据问题", ""]
        for err in parse_errors:
            lines.append(
                f"- 第 {err.line_no} 行：{err.reason}（该行已跳过，其余数据不受影响）"
            )
        lines.append("")

    if warnings:
        lines += ["## 提示", ""] + [f"- {w}" for w in warnings] + [""]

    return "\n".join(lines)


def _render_batch(batch: BatchState) -> list[str]:
    status = "已收口" if batch.closed else "进行中"
    lines = [f"## 批次 {batch.id}（{status}）", ""]
    if batch.hypothesis:
        lines += [f"**假设：**{batch.hypothesis}", ""]

    lines += ["| run | 指标 | 预测 | 实测 | 判定 | 复盘 |", "|---|---|---|---|---|---|"]
    for key, run in batch.runs.items():
        label = f"`{key}`" + ("（已修订）" if run.revised else "")
        metrics = (run.prediction or {}).get("metrics", {})
        if not metrics:
            lines.append(f"| {label} | — | — | — | {_VERDICT_LABEL[run.verdict]} | — |")
            continue
        for i, (name, predicted) in enumerate(metrics.items()):
            judgement = run.metric_judgements.get(name)
            verdict = judgement.verdict if judgement else run.verdict
            closure = "✓" if run.closed else ("待复盘" if verdict is Verdict.SURPRISE else "—")
            lines.append(
                f"| {label if i == 0 else ''} | {name} | {_format_prediction(predicted)} "
                f"| {_format_actual(run.aggregates.get(name))} | {_VERDICT_LABEL[verdict]} "
                f"| {closure} |"
            )
    lines.append("")

    for run in batch.runs.values():
        for judgement in run.metric_judgements.values():
            if judgement.verdict is Verdict.NOISY:
                lines += [f"- `{run.run}`：{judgement.note}", ""]
                break
        if "result_predates_prediction" in run.integrity:
            lines += [
                f"- ⚠ `{run.run}`：结果文件的修改时间早于预测写入时间（预测晚于结果），"
                f"请确认这不是补记的预测",
                "",
            ]
        for warning in run.warnings:
            lines += [f"- `{run.run}`：{warning}", ""]

    if batch.ranking is not None:
        lines += [f"**排序预测：**{_VERDICT_LABEL[batch.ranking.verdict]}", ""]
        for better, worse in batch.ranking.real_flips:
            lines.append(f"- 预期 `{better}` 优于 `{worse}`，实测相反")
        for better, worse in batch.ranking.noisy_flips:
            lines.append(f"- 预期 `{better}` 优于 `{worse}`，实测差异落在噪声内，无法判定")
        lines.append("")

    if batch.info_signal:
        lines += [f"> {batch.info_signal}", ""]
    for warning in batch.warnings:
        lines += [f"- {warning}", ""]

    return lines
