"""信念账本。见 spec §3.2、§7.1。"""

from __future__ import annotations

import pytest

from ari.beliefs import make_belief_id, normalize_text, project_beliefs, render_markdown
from ari.events import Event


def test_same_text_gets_the_same_id():
    assert make_belief_id("lr 调低对大模型没用") == make_belief_id("lr 调低对大模型没用")


def test_id_looks_like_bel_plus_four_hex():
    belief_id = make_belief_id("lr 调低对大模型没用")

    assert belief_id.startswith("bel-")
    assert len(belief_id) == len("bel-") + 4
    int(belief_id.removeprefix("bel-"), 16)  # 是合法的十六进制


def test_different_text_gets_a_different_id():
    assert make_belief_id("A 比 B 好") != make_belief_id("B 比 A 好")


def test_reformatting_does_not_mint_a_new_id():
    # 换行位置变了、缩进变了，还是同一句话
    assert make_belief_id("lr 调低\n对大模型没用") == make_belief_id("lr 调低 对大模型没用")


def test_collision_with_different_text_extends_the_id():
    text = "lr 调低对大模型没用"
    short = make_belief_id(text)
    # 假装这个 ID 已经被另一条内容占了
    extended = make_belief_id(text, {short: "完全不同的另一条信念"})

    assert extended != short
    assert extended.startswith(short)


def test_collision_with_the_same_text_reuses_the_id():
    text = "lr 调低对大模型没用"
    short = make_belief_id(text)

    assert make_belief_id(text, {short: text}) == short


def test_empty_text_is_rejected():
    with pytest.raises(ValueError):
        make_belief_id("   \n  ")


def test_normalize_text_ignores_whitespace():
    assert normalize_text("  a\n\n  b  ") == "ab"


def _added(belief_id, text, ts="2026-08-24T10:00:00+08:00", batch="b1", run="model=large"):
    return Event(
        ts=ts,
        type="belief_added",
        batch=batch,
        run=run,
        payload={"id": belief_id, "text": text},
    )


def _changed(kind, belief_id, ts="2026-08-25T10:00:00+08:00", batch="b2", note=""):
    return Event(
        ts=ts,
        type=kind,
        batch=batch,
        run=None,
        payload={"id": belief_id, "note": note},
    )


def test_added_belief_lands_in_the_ledger():
    ledger, warnings = project_beliefs([_added("bel-aaaa", "大模型吃不下小 lr")])

    assert warnings == []
    assert ledger["bel-aaaa"].text == "大模型吃不下小 lr"
    assert ledger["bel-aaaa"].added_ts == "2026-08-24T10:00:00+08:00"
    assert ledger["bel-aaaa"].batch == "b1"
    assert ledger["bel-aaaa"].run == "model=large"
    assert ledger["bel-aaaa"].status == "在册"


def test_refuted_belief_is_marked_and_keeps_its_text():
    ledger, _ = project_beliefs(
        [
            _added("bel-aaaa", "大模型吃不下小 lr"),
            _changed("belief_refuted", "bel-aaaa", note="换了调度器就不成立了"),
        ]
    )

    belief = ledger["bel-aaaa"]
    assert belief.refuted
    assert belief.status == "已推翻"
    assert belief.text == "大模型吃不下小 lr"  # 推翻不是删除，历史必须留着
    assert belief.changes[0].note == "换了调度器就不成立了"
    assert belief.changes[0].batch == "b2"


def test_reinforced_and_weakened_shape_the_status():
    reinforced, _ = project_beliefs(
        [_added("bel-aaaa", "x"), _changed("belief_reinforced", "bel-aaaa")]
    )
    weakened, _ = project_beliefs(
        [_added("bel-aaaa", "x"), _changed("belief_weakened", "bel-aaaa")]
    )

    assert reinforced["bel-aaaa"].status == "已加强"
    assert weakened["bel-aaaa"].status == "动摇中"


def test_change_to_an_unknown_id_warns_instead_of_crashing():
    ledger, warnings = project_beliefs([_changed("belief_refuted", "bel-zzzz")])

    assert ledger == {}
    assert len(warnings) == 1
    assert "bel-zzzz" in warnings[0]


def test_duplicate_add_keeps_the_first_one():
    ledger, warnings = project_beliefs(
        [
            _added("bel-aaaa", "x", ts="2026-08-24T10:00:00+08:00"),
            _added("bel-aaaa", "x", ts="2026-08-26T10:00:00+08:00"),
        ]
    )

    assert len(ledger) == 1
    assert ledger["bel-aaaa"].added_ts == "2026-08-24T10:00:00+08:00"
    assert warnings == []


def test_malformed_add_is_reported_not_silently_dropped():
    ledger, warnings = project_beliefs(
        [Event(ts="2026-08-24T10:00:00+08:00", type="belief_added", payload={"text": "没有 id"})]
    )

    assert ledger == {}
    assert len(warnings) == 1


def test_ledger_order_follows_the_event_stream():
    ledger, _ = project_beliefs(
        [_added("bel-bbbb", "第二个先写不行"), _added("bel-aaaa", "第一个")]
    )

    assert list(ledger) == ["bel-bbbb", "bel-aaaa"]


def test_unrelated_events_are_ignored():
    ledger, warnings = project_beliefs(
        [
            Event(
                ts="2026-08-24T10:00:00+08:00",
                type="run_result",
                batch="b1",
                run="model=large",
                payload={"seed": 0, "metrics": {"top1_acc": 0.9}},
            )
        ]
    )

    assert ledger == {} and warnings == []


def test_render_shows_human_numbering_and_the_immutable_id():
    ledger, _ = project_beliefs([_added("bel-aaaa", "大模型吃不下小 lr")])

    text = render_markdown(ledger)

    assert "1." in text
    assert "bel-aaaa" in text
    assert "大模型吃不下小 lr" in text
    assert "编号" in text  # 明确说明编号只是渲染层的产物


def test_render_separates_refuted_beliefs_and_keeps_them_visible():
    ledger, _ = project_beliefs(
        [
            _added("bel-aaaa", "还成立的"),
            _added("bel-bbbb", "被推翻的"),
            _changed("belief_refuted", "bel-bbbb", note="换了调度器"),
        ]
    )

    text = render_markdown(ledger)

    assert "在册" in text and "已推翻" in text
    assert text.index("还成立的") < text.index("被推翻的")  # 已推翻的排在后面
    assert "换了调度器" in text


def test_render_shows_where_a_belief_came_from_and_what_touched_it():
    ledger, _ = project_beliefs(
        [
            _added("bel-aaaa", "x", batch="b1", run="model=large"),
            _changed("belief_reinforced", "bel-aaaa", batch="b3"),
        ]
    )

    text = render_markdown(ledger)

    assert "b1" in text and "model=large" in text
    assert "b3" in text and "加强" in text


def test_render_on_an_empty_ledger_explains_how_to_get_one():
    text = render_markdown({})

    assert "review" in text  # 告诉用户信念从哪来，而不是丢一张空表
    assert "还没有" in text


def test_render_reports_dangling_references():
    ledger, warnings = project_beliefs([_changed("belief_refuted", "bel-zzzz")])

    text = render_markdown(ledger, warnings)

    assert "bel-zzzz" in text
