"""复盘追问。见 spec §7 第 2 步。

「你觉得是为什么呢」这种问题不如不问——它只会让人写下「不知道」。所以
prompt 里必须塞进三样具体的东西：偏差数字、当初写下的理由、历史上类似
的那几次及其结论（由 recall.py 检索）。

输出只有问题和假设，没有结论。结论必须由人写——这一步是整套流程里唯一
真正产出知识的地方，把它让给模型就等于把这个项目的意义让掉了。
"""

from __future__ import annotations

from pathlib import Path

from .config import load_config, resolve_role
from .llm import LLMUnavailable, complete
from .recall import similar
from .reviewing import deviation_lines

PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
        "hypotheses": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions", "hypotheses"],
    "additionalProperties": False,
}

SYSTEM = """\
一位科研人员的实验结果超出了他自己的预测区间，正在写复盘。你的任务是
帮他把注意力引到对的地方，不是替他下结论。

给两样东西：

1. questions —— 三条以内可以动手去查的具体问题。「增强的配置两组一样吗」
   是具体的，「是否存在其他影响因素」不是。
2. hypotheses —— 三条以内关于原因的具体猜测。如果历史记录里有类似的意外，
   优先指出「是否与那次同一个原因」，并说清依据。

不要下结论，不要安慰，不要复述他已经知道的数字。没有把握的就不说——
一条空话会让他下次直接跳过这一段。
"""


def build_prompt(
    batch: str,
    run: str,
    hypothesis: str,
    deviations: list[str],
    rationale: str,
    history: list,
) -> str:
    lines = [
        f"批次 {batch} 的假设：{hypothesis}",
        "",
        f"出意外的 run：{run}",
        "偏差：",
        *(f"  {line}" for line in deviations),
        "",
        f"他当初写下的理由：{rationale or '（没写）'}",
        "",
    ]

    if history:
        lines.append("这个项目历史上类似的意外：")
        for item in history:
            lines += [
                f"  · {item.batch} / {item.run}（当时的指标：{'、'.join(item.metrics)}）",
                f"    当初的理由：{item.rationale or '（没写）'}",
                f"    复盘结论：{item.cause}",
            ]
            if item.next_step:
                lines.append(f"    当时打算：{item.next_step}")
    else:
        lines.append("这个项目还没有别的已复盘的意外，没有历史可以参照——不要编造。")

    return "\n".join(lines)


def check_probe(probe: dict) -> dict:
    """空话过滤。一个具体问题都没有，不如不显示这一段。"""
    questions = [q.strip() for q in (probe.get("questions") or []) if q and q.strip()]
    if not questions:
        raise LLMUnavailable("AI 没能提出任何具体问题")
    hypotheses = [h.strip() for h in (probe.get("hypotheses") or []) if h and h.strip()]
    return {"questions": questions, "hypotheses": hypotheses}


def probe(root: Path, batches: dict, run) -> dict:
    """问一次有针对性的追问。任何问题都抛 LLMUnavailable。

    先检索本项目历史上相似的意外与当时写下的结论，再问具体的问题——
    「两组的数据增强配置一样吗」，而不是「你觉得是为什么呢」。
    """
    ref = resolve_role(load_config(root), "reason")
    history = similar(batches, run)
    hypothesis = batches[run.batch].hypothesis if run.batch in batches else ""
    result = complete(
        ref,
        SYSTEM,
        build_prompt(
            batch=run.batch,
            run=run.run,
            hypothesis=hypothesis,
            deviations=deviation_lines(run),
            rationale=(run.prediction or {}).get("rationale", ""),
            history=history,
        ),
        PROBE_SCHEMA,
    )
    return check_probe(result)
