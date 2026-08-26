"""想法账本：从灵感到立项的最初一段。

科研的起点不是一个变量表，而是一个「说不定会很有意思」的念头。这一段
没有结构可言，所以只做两件事：低摩擦地记下来，以及随时能把它推进成
一个实验批次（batch_opened 引用 idea id，形成谱系）。

引用方式与信念账本一致：内容 hash 短 ID（idea-7a3c），不用序号——
序号引用只要插入或删除一条，历史上所有引用就静默漂移。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .beliefs import normalize_text

_ID_PREFIX = "idea-"
_MIN_ID_CHARS = 4
_MAX_ID_CHARS = 16

STATUS_OPEN = "待验证"
STATUS_TESTING = "实验中"
STATUS_VERIFIED = "已验证"
STATUS_DISCARDED = "已放弃"


def make_idea_id(text: str, existing: dict[str, str] | None = None) -> str:
    """内容 hash 前 4 位。同文本必得同 ID，重复捕捉是幂等的。"""
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("想法内容不能为空")

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    taken = existing or {}
    for length in range(_MIN_ID_CHARS, _MAX_ID_CHARS + 1):
        candidate = _ID_PREFIX + digest[:length]
        held = taken.get(candidate)
        if held is None or normalize_text(held) == normalized:
            return candidate
    raise ValueError(f"想法 ID 冲突无法解决：{text!r}")


@dataclass
class Idea:
    id: str
    text: str
    motivation: str = ""
    added_ts: str = ""
    batches: list[str] = field(default_factory=list)
    discarded: bool = False
    discard_reason: str = ""

    def status(self, batch_states: dict | None = None) -> str:
        """想法的推进状态由它派生出的批次决定。

        batch_states 是 project() 折叠出的 {id: BatchState}；不传时只看
        有没有关联批次。批次可能是已收口（已验证）或还在跑（实验中）。
        """
        if self.discarded:
            return STATUS_DISCARDED
        if not self.batches:
            return STATUS_OPEN
        states = batch_states or {}
        linked = [states[b] for b in self.batches if b in states]
        if linked and all(batch.closed for batch in linked):
            return STATUS_VERIFIED
        return STATUS_TESTING


def project_ideas(events) -> tuple[dict[str, Idea], list[str]]:
    """把 idea_* 事件折叠成想法账本，并收集 batch_opened 的想法引用。

    返回 (ideas, 警告)。批次引用先于想法出现、或指向不存在的想法时
    只报警告不报错——一条悬空引用不该让整个账本不可用。
    """
    ideas: dict[str, Idea] = {}
    warnings: list[str] = []

    for event in events:
        if event.type == "idea_captured":
            idea_id = event.payload.get("id")
            text = (event.payload.get("text") or "").strip()
            if not idea_id or not text:
                warnings.append(
                    f"第 {event.line_no} 行：idea_captured 缺少 id 或 text，已跳过"
                )
                continue
            if idea_id in ideas:
                continue  # 同一想法重复捕捉，保留最早那次
            ideas[idea_id] = Idea(
                id=idea_id,
                text=text,
                motivation=(event.payload.get("motivation") or "").strip(),
                added_ts=event.ts,
            )

        elif event.type == "idea_discarded":
            idea_id = event.payload.get("id")
            idea = ideas.get(idea_id)
            if idea is None:
                warnings.append(
                    f"第 {event.line_no} 行：idea_discarded 引用了不存在的想法 "
                    f"{idea_id!r}，已跳过"
                )
                continue
            idea.discarded = True
            idea.discard_reason = (event.payload.get("reason") or "").strip()

        elif event.type == "batch_opened":
            idea_id = (event.payload.get("idea") or "").strip()
            if not idea_id:
                continue
            idea = ideas.get(idea_id)
            if idea is None:
                warnings.append(
                    f"第 {event.line_no} 行：批次 {event.batch!r} 引用了不存在的想法 "
                    f"{idea_id!r}，已跳过"
                )
                continue
            if event.batch not in idea.batches:
                idea.batches.append(event.batch)

    return ideas, warnings
