"""想法账本：从灵感到立项的投影。"""

from __future__ import annotations

from types import SimpleNamespace

from ari.events import Event
from ari.ideas import make_idea_id, project_ideas


def _events(*rows):
    return [
        Event(ts=f"2026-08-26T10:0{i}:00+00:00", type=row[0], payload=row[1], batch=row[2] if len(row) > 2 else None)
        for i, row in enumerate(rows)
    ]


def test_idea_id_is_content_hash_and_repeatable():
    first = make_idea_id("large 模型更受益于增强")
    second = make_idea_id("large  模型\n更受益于增强")  # 折叠空白后同文本
    assert first == second
    assert first.startswith("idea-")
    assert len(first) == len("idea-") + 4


def test_idea_id_grows_only_on_real_collision():
    base = make_idea_id("想法 A")
    existing = {base: "想法 A"}
    # 同文本重复捕捉：幂等，不加长。
    assert make_idea_id("想法 A", existing) == base
    # 不同文本占用了同 ID：加长一位。
    forced = {base: "完全不同的想法"}
    longer = make_idea_id("想法 A", forced)
    assert len(longer) == len("idea-") + 5


def test_capture_then_promote_marks_testing():
    idea_id = make_idea_id("增强对大模型更有效")
    ideas, warnings = project_ideas(
        _events(
            ("idea_captured", {"id": idea_id, "text": "增强对大模型更有效", "motivation": "容量与正则化"}),
            ("batch_opened", {"hypothesis": "h1", "idea": idea_id}, "b1"),
        )
    )

    assert not warnings
    idea = ideas[idea_id]
    assert idea.motivation == "容量与正则化"
    assert idea.batches == ["b1"]
    assert idea.status() == "实验中"


def test_status_follows_linked_batch_states():
    idea_id = make_idea_id("增强对大模型更有效")
    ideas, _ = project_ideas(
        _events(
            ("idea_captured", {"id": idea_id, "text": "增强对大模型更有效"}),
            ("batch_opened", {"hypothesis": "h1", "idea": idea_id}, "b1"),
            ("batch_opened", {"hypothesis": "h2", "idea": idea_id}, "b2"),
        )
    )
    idea = ideas[idea_id]

    open_batch = SimpleNamespace(closed=False)
    assert idea.status({"b1": open_batch, "b2": open_batch}) == "实验中"

    closed_batch = SimpleNamespace(closed=True)
    assert idea.status({"b1": closed_batch, "b2": open_batch}) == "实验中"
    assert idea.status({"b1": closed_batch, "b2": closed_batch}) == "已验证"


def test_discard_keeps_record_and_reason():
    idea_id = make_idea_id("值得放弃的想法")
    ideas, _ = project_ideas(
        _events(
            ("idea_captured", {"id": idea_id, "text": "值得放弃的想法"}),
            ("idea_discarded", {"id": idea_id, "reason": "文献里已有系统比较"}),
        )
    )
    idea = ideas[idea_id]
    assert idea.discarded is True
    assert idea.status() == "已放弃"
    assert idea.discard_reason == "文献里已有系统比较"


def test_dangling_references_only_warn():
    ideas, warnings = project_ideas(
        _events(
            ("idea_discarded", {"id": "idea-0000", "reason": ""}),
            ("batch_opened", {"hypothesis": "h", "idea": "idea-ffff"}, "b1"),
        )
    )
    assert not ideas
    assert len(warnings) == 2
    assert all("已跳过" in w for w in warnings)


def test_duplicate_capture_is_idempotent():
    idea_id = make_idea_id("同一个想法")
    events = _events(
        ("idea_captured", {"id": idea_id, "text": "同一个想法"}),
        ("idea_captured", {"id": idea_id, "text": "同一个想法"}),
    )
    ideas, _ = project_ideas(events)
    assert len(ideas) == 1
    assert ideas[idea_id].added_ts.endswith("00+00:00")


def test_project_skips_idea_events_without_warning():
    """idea_* 事件不属于批次投影，但也不该在 project() 里报未知类型。"""
    from ari.project import project as project_events

    idea_id = make_idea_id("增强对大模型更有效")
    events = _events(
        ("idea_captured", {"id": idea_id, "text": "增强对大模型更有效"}),
        ("idea_discarded", {"id": idea_id, "reason": ""}),
    )
    batches, warnings = project_events(events)
    assert not batches
    assert not warnings
