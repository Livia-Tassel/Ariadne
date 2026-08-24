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
from dataclasses import dataclass, field

_ID_PREFIX = "bel-"
_MIN_ID_CHARS = 4
_MAX_ID_CHARS = 16

# 状态变更事件 → 给人看的动词。
CHANGE_TYPES = {
    "belief_weakened": "动摇",
    "belief_reinforced": "加强",
    "belief_refuted": "推翻",
}


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


@dataclass(frozen=True)
class BeliefChange:
    kind: str
    ts: str
    note: str = ""
    batch: str | None = None
    run: str | None = None


@dataclass
class Belief:
    id: str
    text: str
    added_ts: str = ""
    batch: str | None = None
    run: str | None = None
    changes: list[BeliefChange] = field(default_factory=list)

    @property
    def refuted(self) -> bool:
        return any(c.kind == "belief_refuted" for c in self.changes)

    @property
    def status(self) -> str:
        """在册 / 已加强 / 动摇中 / 已推翻。

        只数次数，不做加权：加权需要一张说不清来源的权重表，而这里的
        用途只是排序和提示，撑不起那个复杂度。
        """
        if self.refuted:
            return "已推翻"
        weakened = sum(1 for c in self.changes if c.kind == "belief_weakened")
        reinforced = sum(1 for c in self.changes if c.kind == "belief_reinforced")
        if weakened > reinforced:
            return "动摇中"
        if reinforced:
            return "已加强"
        return "在册"


def project_beliefs(events) -> tuple[dict[str, Belief], list[str]]:
    """把 belief_* 事件折叠成账本。返回 (ledger, 警告)。

    引用不存在的 ID 只报警告不抛错：事件流可能被手动编辑过，一条悬空
    引用不该让整个账本不可用——这与 events.py 逐行容错是同一条原则。
    """
    ledger: dict[str, Belief] = {}
    warnings: list[str] = []

    for event in events:
        if event.type == "belief_added":
            belief_id = event.payload.get("id")
            text = (event.payload.get("text") or "").strip()
            if not belief_id or not text:
                warnings.append(
                    f"第 {event.line_no} 行：belief_added 缺少 id 或 text，已跳过"
                )
                continue
            if belief_id in ledger:
                continue  # 同一条信念重复添加，保留最早那次
            ledger[belief_id] = Belief(
                id=belief_id,
                text=text,
                added_ts=event.ts,
                batch=event.batch,
                run=event.run,
            )

        elif event.type in CHANGE_TYPES:
            belief_id = event.payload.get("id")
            belief = ledger.get(belief_id)
            if belief is None:
                warnings.append(
                    f"第 {event.line_no} 行：{event.type} 引用了不存在的信念 "
                    f"{belief_id!r}，已跳过"
                )
                continue
            belief.changes.append(
                BeliefChange(
                    kind=event.type,
                    ts=event.ts,
                    note=(event.payload.get("note") or "").strip(),
                    batch=event.batch,
                    run=event.run,
                )
            )

    return ledger, warnings
