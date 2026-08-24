"""信念账本。见 spec §3.2、§7.1。

信念是这套流程真正沉淀下来的东西：批次会过去，run key 会失效，但
「lr 调低对大模型没用」这类判断会一直被下一次预测引用。账本记录它们
被哪次实验加强、被哪次实验推翻——既是自学习的载体，也是将来写
discussion 的原材料。

引用一律用不可变短 ID（bel-7a3c，内容 hash 前 4 位），不用序号：序号
引用只要插入或删除一条，历史上所有引用就会静默指向别的东西，那是会
污染全部历史数据的缺陷。beliefs.md 里的 1. 2. 只是渲染层给人看的编号。
"""

from __future__ import annotations

import hashlib

_ID_PREFIX = "bel-"
_MIN_ID_CHARS = 4
_MAX_ID_CHARS = 16


def normalize_text(text: str) -> str:
    """折叠空白。同一句话换个换行位置不该变成另一条信念。"""
    return " ".join(text.split())


def make_belief_id(text: str, existing: dict[str, str] | None = None) -> str:
    """内容 hash 前 4 位。同文本必得同 ID，所以重复添加是幂等的。

    existing 是已占用的 {id: text}。只在撞上同 ID 但不同文本时加长——
    加长是给真实 hash 碰撞留的后路，不是常态。
    """
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("信念内容不能为空")

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    taken = existing or {}
    for length in range(_MIN_ID_CHARS, _MAX_ID_CHARS + 1):
        candidate = _ID_PREFIX + digest[:length]
        held = taken.get(candidate)
        if held is None or normalize_text(held) == normalized:
            return candidate
    raise ValueError(f"信念 ID 冲突无法解决：{text!r}")
