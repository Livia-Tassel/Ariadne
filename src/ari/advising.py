"""AI 的那份判断。见 spec §4.2。

只给三样东西：相对排序、定性方向、混淆因素。**不给数值。**

理由：通用模型对「你的私有数据集上 large 比 base 高几个点」没有任何
有效先验，给出的数字看似精确实则编造；第一次出现明显离谱的数值就会把
信任耗光，而这个功能的全部价值都建立在信任上。相对排序与混淆因素提示
则是模型真正有优势的地方。

schema 里一个数值字段都没有，且 additionalProperties 为 false——这是
结构保证，不是 prompt 里的一句请求。prompt 里再说一遍只是双保险。
"""

from __future__ import annotations

from pathlib import Path

from .config import load_config, resolve_role
from .llm import LLMUnavailable, complete

ADVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {"type": "array", "items": {"type": "string"}},
        "directions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "variable": {"type": "string"},
                    "effect": {"type": "string"},
                },
                "required": ["variable", "effect"],
                "additionalProperties": False,
            },
        },
        "confounders": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ranking", "directions", "confounders"],
    "additionalProperties": False,
}

SYSTEM = """\
你在协助一位科研人员做实验前的预判。你只提供三样东西：

1. ranking —— 这些配置按目标指标从好到差的相对排序；
2. directions —— 每个变量的影响方向与强弱，用定性语言；
3. confounders —— 对方可能没考虑到的混淆因素。

绝不给任何数值点估计或区间。你对这个私有数据集没有有效先验，编出来的
数值看似精确实则是猜的，一次离谱就会让对方不再信任这一整个功能。

ranking 只能使用给定的 run 标识，一个不漏、一个不多，不要发明新的配置。
confounders 要具体到可以动手检查，不要写「注意超参数的影响」这类空话。
"""


def build_prompt(hypothesis: str, dimensions: dict, runs: list[str], metrics: list[str]) -> str:
    lines = [
        f"假设：{hypothesis}",
        "",
        "变量维度：",
    ]
    for name, values in dimensions.items():
        lines.append(f"  {name}: {', '.join(str(v) for v in values)}")
    lines += [
        "",
        f"关心的指标：{', '.join(metrics)}",
        "",
        "这一批的 run（ranking 必须正好用这些标识）：",
        *(f"  {run}" for run in runs),
        "",
        "只给相对排序、定性方向与混淆因素，不要给任何数值。",
    ]
    return "\n".join(lines)


def check_advice(advice: dict, runs: list[str]) -> dict:
    """结构之外的语义校验：ranking 必须恰好是本批次 run 的一个排列。

    模型编出一个不存在的配置，比不给排序更有害——它看起来像个结论。
    """
    ranking = advice.get("ranking") or []
    unknown = [r for r in ranking if r not in runs]
    if unknown:
        raise LLMUnavailable(f"AI 的排序里出现了不存在的 run：{'、'.join(unknown)}")
    if len(set(ranking)) != len(ranking):
        raise LLMUnavailable("AI 的排序里有重复的 run")
    missing = [r for r in runs if r not in ranking]
    if missing:
        raise LLMUnavailable(f"AI 的排序漏掉了 run：{'、'.join(missing)}")
    return advice


def advise(root: Path, design, runs: list[str]) -> dict:
    """问一次 AI 的定性判断。任何问题都抛 LLMUnavailable。

    单独提出来是为了让接线测试能整体替换它——测试不该碰网络。CLI 与 GUI
    共用这一个入口，两边的降级行为因此不会漂移。
    """
    ref = resolve_role(load_config(root), "reason")
    advice = complete(
        ref,
        SYSTEM,
        build_prompt(design.hypothesis, design.dimensions, runs, design.metrics),
        ADVICE_SCHEMA,
    )
    return check_advice(advice, runs)
