"""ari review：复盘。见 spec §7。

SURPRISE 未复盘就一直钉在看板顶部。自动化降低了记录成本，但不能降低
思考成本——这是整套流程里唯一真正产出知识的一步。

草稿里把预测、实测、**具体哪个指标偏了多少**、以及当初写下的 rationale
并排摆出来。没有这些，人只会写「不知道为什么」；有了偏差数字和当初的
理由，才有可能定位到错的是哪个假设。

本模块不含 LLM 追问（留给计划三）。spec §8 要求 LLM 不可用时 review
降级为无追问的纯手写模式——这里就是那个模式。
"""

from __future__ import annotations

import yaml

from .verdict import Verdict

_CAUSE_PLACEHOLDER = "<为什么会这样？>"
_NEXT_PLACEHOLDER = "<下一步做什么？可以留空>"


def pending(batches: dict) -> list:
    """待复盘队列：未写过 reflection 的 SURPRISE run，按批次顺序。

    NOISY 不进队列——那说明这次实验分辨不出你要问的差异，该做的是补
    seed 或拉大变量跨度，不是写复盘。
    """
    return [
        run
        for batch in batches.values()
        for run in batch.runs.values()
        if run.verdict is Verdict.SURPRISE and not run.closed
    ]


def _format_actual(agg) -> str:
    if agg is None:
        return "尚无结果"
    if agg.sd is None:
        return f"{agg.mean:.4g}"
    return f"{agg.mean:.4g} ± {agg.sd:.3g} (n={agg.n})"


def _format_prediction(value) -> str:
    if isinstance(value, (list, tuple)):
        return f"[{float(value[0]):.4g}, {float(value[1]):.4g}]"
    return f"{float(value):.4g}"


def build_reflection_draft(run) -> str:
    prediction = run.prediction or {}
    metrics = prediction.get("metrics", {})

    lines = [
        f"# ── 复盘 {run.batch} / {run.run} ──────────────────────────────",
        "#",
    ]

    for name, judgement in run.metric_judgements.items():
        if judgement.verdict is not Verdict.SURPRISE:
            continue
        agg = run.aggregates.get(name)
        lines.append(
            f"#   {name}：预测 {_format_prediction(metrics[name])}"
            f" → 实测 {_format_actual(agg)}"
        )
        if judgement.deviation is not None:
            lines.append(
                f"#     偏差 {judgement.deviation:+.4g}，容差 {judgement.threshold:.4g}"
            )
        elif agg is not None:
            low, high = sorted(float(v) for v in metrics[name])
            outside = agg.mean - high if agg.mean > high else agg.mean - low
            lines.append(f"#     超出区间 {outside:+.4g}")

    other = [
        f"{n}={_format_actual(run.aggregates.get(n))}"
        for n, j in run.metric_judgements.items()
        if j.verdict is not Verdict.SURPRISE and n in run.aggregates
    ]
    if other:
        lines += ["#", f"#   同批其余指标：{'  '.join(other)}"]

    rationale = prediction.get("rationale")
    if rationale:
        lines += ["#", f"#   当初你写的理由：{rationale}"]

    lines += [
        "#",
        "# 结果与预期不符，说明某个假设有问题。找到那个假设，是这一步唯一的目的。",
        "# 想放弃就清空整个文件再保存。",
        "",
        f"cause: {_CAUSE_PLACEHOLDER}",
        f"next:  {_NEXT_PLACEHOLDER}",
        "",
    ]
    return "\n".join(lines)


def parse_reflection(text: str, scope: str = "run") -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("草稿的顶层应该是 cause 与 next 两个字段")

    cause = (data.get("cause") or "")
    cause = cause.strip() if isinstance(cause, str) else str(cause)
    if not cause or cause == _CAUSE_PLACEHOLDER:
        raise ValueError("cause 不能为空——写不出原因，就写下「还不知道」和你打算怎么查")

    nxt = (data.get("next") or "")
    nxt = nxt.strip() if isinstance(nxt, str) else str(nxt)
    if nxt == _NEXT_PLACEHOLDER:
        nxt = ""

    return {"scope": scope, "cause": cause, "next": nxt}


BATCH_DRAFT = """\
# ── 收口 {batch_id} ──────────────────────────────────────────────────
# 所有 SURPRISE 都复盘完了。写一句这个批次整体的结论，批次即收口。
# 想跳过就清空整个文件再保存。

cause: <这一批整体学到了什么？>
next:  <下一批打算验证什么？可以留空>
"""


def build_batch_draft(batch_id: str) -> str:
    return BATCH_DRAFT.format(batch_id=batch_id)
