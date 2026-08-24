import pytest
from conftest import make_batch_opened, make_prediction, make_result

from ari.events import Event
from ari.project import project
from ari.reviewing import (
    build_reflection_draft,
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
