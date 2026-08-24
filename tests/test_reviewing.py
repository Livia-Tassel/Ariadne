import pytest
from conftest import make_batch_opened, make_prediction, make_result

from ari.beliefs import BeliefChange, make_belief_id, project_beliefs
from ari.events import Event
from ari.project import project
from ari.reviewing import (
    build_batch_draft,
    build_reflection_draft,
    build_reflection_events,
    parse_reflection,
    pending,
)


def _batch_with(prediction, actual, **kw):
    events = [
        make_batch_opened(**kw),
        make_prediction("model=large", {"top1_acc": prediction}),
    ]
    values = actual if isinstance(actual, list) else [actual]
    for seed, value in enumerate(values):
        events.append(make_result("model=large", {"top1_acc": value}, seed=seed))
    return events


def test_pending_lists_unreflected_surprises():
    batches, _ = project(_batch_with(0.830, 0.950))

    queue = pending(batches)

    assert [r.run for r in queue] == ["model=large"]


def test_confirmed_runs_are_not_in_the_queue():
    batches, _ = project(_batch_with(0.830, 0.831))

    assert pending(batches) == []


def test_reflected_surprises_leave_the_queue():
    events = _batch_with(0.830, 0.950)
    events.append(
        Event(
            ts="2026-08-24T10:00:00+08:00",
            type="reflection",
            batch="b1",
            run="model=large",
            payload={"scope": "run", "cause": "增强没关"},
        )
    )

    batches, _ = project(events)

    assert pending(batches) == []


def test_noisy_runs_are_not_pending():
    # NOISY 说明这次实验分辨不出差异，要补 seed 而不是写复盘
    batches, _ = project(_batch_with(0.830, [0.80, 0.83, 0.86]))

    assert pending(batches) == []


def test_draft_shows_prediction_actual_and_the_original_rationale():
    batches, _ = project(_batch_with(0.830, 0.950))
    run = pending(batches)[0]

    draft = build_reflection_draft(run)

    assert "0.83" in draft
    assert "0.95" in draft
    assert "因为容量更大" in draft  # conftest 里预测时写下的 rationale


def test_draft_names_the_metric_and_the_deviation():
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0])

    assert "top1_acc" in draft
    assert "0.12" in draft  # 偏差 0.950 - 0.830


def test_draft_shows_spread_across_seeds():
    batches, _ = project(_batch_with(0.830, [0.949, 0.951]))

    draft = build_reflection_draft(pending(batches)[0])

    assert "±" in draft or "n=2" in draft


def test_parse_reflection_reads_cause_and_next():
    payload = parse_reflection("cause: 数据增强没关\nnext: 关掉重跑\n")

    assert payload["cause"] == "数据增强没关"
    assert payload["next"] == "关掉重跑"
    assert payload["scope"] == "run"


def test_blank_cause_is_rejected():
    with pytest.raises(ValueError) as exc:
        parse_reflection("cause:\nnext: 重跑\n")

    assert "cause" in str(exc.value)


def test_next_is_optional():
    assert parse_reflection("cause: 想不出原因，先记下来\n")["next"] == ""


def test_placeholder_cause_is_rejected():
    draft_default = "cause: <为什么会这样？>\n"

    with pytest.raises(ValueError):
        parse_reflection(draft_default)


def _ledger(*texts):
    events = [
        Event(
            ts="2026-08-20T10:00:00+08:00",
            type="belief_added",
            batch="b0",
            payload={"id": f"bel-{i:04d}", "text": text},
        )
        for i, text in enumerate(texts)
    ]
    ledger, _ = project_beliefs(events)
    return ledger


def test_draft_asks_what_you_now_believe():
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0])

    assert "beliefs_added" in draft


def test_draft_lists_existing_beliefs_with_their_ids():
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0], _ledger("大模型吃不下小 lr"))

    assert "bel-0000" in draft
    assert "大模型吃不下小 lr" in draft  # 光有 ID 认不出是哪条
    assert "unchanged" in draft


def test_draft_hides_refuted_beliefs():
    ledger = _ledger("还成立的", "被推翻的")
    ledger["bel-0001"].changes.append(
        BeliefChange(kind="belief_refuted", ts="2026-08-21T10:00:00+08:00")
    )
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0], ledger)

    assert "bel-0000" in draft
    assert "bel-0001" not in draft  # 已经推翻的不再问


def test_batch_draft_also_carries_the_belief_section():
    # 全 CONFIRMED 的批次没有 run 级复盘，收口是记信念的唯一入口
    assert "beliefs_added" in build_batch_draft("b1", _ledger("x"))


def test_parse_reads_added_beliefs():
    parsed = parse_reflection(
        "cause: 增强没关\nbeliefs_added:\n  - 大模型吃不下小 lr\n  - 增强对小数据集有害\n"
    )

    assert parsed["beliefs_added"] == ["大模型吃不下小 lr", "增强对小数据集有害"]


def test_parse_skips_the_untouched_placeholder():
    draft = build_reflection_draft(pending(project(_batch_with(0.830, 0.950))[0])[0]).replace(
        "<为什么会这样？>", "增强没关"
    )

    parsed = parse_reflection(draft)

    assert parsed["beliefs_added"] == []
    assert parsed["belief_changes"] == {}


def test_parse_reads_belief_changes_and_drops_unchanged():
    parsed = parse_reflection(
        "cause: 增强没关\nbeliefs:\n  bel-0000: refuted\n  bel-0001: unchanged\n"
        "  bel-0002: reinforced\n"
    )

    assert parsed["belief_changes"] == {
        "bel-0000": "belief_refuted",
        "bel-0002": "belief_reinforced",
    }


def test_parse_rejects_an_unknown_belief_status():
    with pytest.raises(ValueError) as exc:
        parse_reflection("cause: 增强没关\nbeliefs:\n  bel-0000: 大概吧\n")

    assert "bel-0000" in str(exc.value)


def test_reflection_without_a_belief_section_is_still_valid():
    parsed = parse_reflection("cause: 增强没关\nnext: 重跑\n")

    assert parsed["beliefs_added"] == [] and parsed["belief_changes"] == {}


def test_any_untouched_angle_bracket_placeholder_counts_as_blank():
    # batch 收口草稿的占位符与 run 级的不是同一句。信念段让「只填信念、
    # 不动 cause」变得更可能，所以占位符判定必须是通用规则而不是硬编码。
    with pytest.raises(ValueError):
        parse_reflection(build_batch_draft("b1") + "\n")


def test_untouched_next_placeholder_becomes_blank():
    assert parse_reflection("cause: 真的原因\nnext: <随便写点什么>\n")["next"] == ""


NOW = "2026-08-24T15:00:00+08:00"


def test_reflection_payload_carries_no_belief_keys():
    parsed = parse_reflection("cause: 增强没关\nbeliefs_added:\n  - 新信念\n")

    events = build_reflection_events(parsed, "b1", "model=large", {}, NOW)

    assert events[0].type == "reflection"
    assert set(events[0].payload) == {"scope", "cause", "next"}


def test_added_belief_becomes_its_own_event_with_provenance():
    parsed = parse_reflection("cause: 增强没关\nbeliefs_added:\n  - 大模型吃不下小 lr\n")

    events = build_reflection_events(parsed, "b1", "model=large", {}, NOW)

    added = [e for e in events if e.type == "belief_added"]
    assert len(added) == 1
    assert added[0].payload["text"] == "大模型吃不下小 lr"
    assert added[0].payload["id"].startswith("bel-")
    assert (added[0].batch, added[0].run) == ("b1", "model=large")
    assert added[0].ts == NOW


def test_belief_already_in_the_ledger_is_not_added_twice():
    ledger = _ledger("大模型吃不下小 lr")
    text = ledger["bel-0000"].text
    parsed = parse_reflection(f"cause: 增强没关\nbeliefs_added:\n  - {text}\n")
    # 账本里那条的 ID 是测试造的，重算一次才对得上
    ledger = {make_belief_id(text): ledger["bel-0000"]}

    events = build_reflection_events(parsed, "b1", "model=large", ledger, NOW)

    assert [e.type for e in events] == ["reflection"]


def test_the_same_belief_twice_in_one_draft_is_added_once():
    parsed = parse_reflection("cause: x\nbeliefs_added:\n  - 同一条\n  - 同一条\n")

    events = build_reflection_events(parsed, "b1", None, {}, NOW)

    assert len([e for e in events if e.type == "belief_added"]) == 1


def test_changes_become_belief_events():
    parsed = parse_reflection("cause: x\nbeliefs:\n  bel-0000: refuted\n")

    events = build_reflection_events(parsed, "b1", "model=large", _ledger("x"), NOW)

    assert [e.type for e in events] == ["reflection", "belief_refuted"]
    assert events[1].payload["id"] == "bel-0000"
    assert events[1].batch == "b1"
