"""历史检索。见 spec §7 第 2 步。

追问必须有针对性。「你觉得是为什么呢」这种问题不如不问——它只会让人
写下「不知道」。有针对性的前提是检索：本项目历史上有没有类似的意外，
当时的结论是什么。

检索是纯函数，不碰 LLM，所以可以严格断言。
"""

from __future__ import annotations

from ari.events import Event
from ari.project import project
from ari.recall import similar


def _batch(batch_id, run, predicted, actual, cause=None, dimensions=None):
    """造一个单 run 的批次。cause 为 None 表示还没复盘。"""
    events = [
        Event(
            ts=f"2026-08-{int(batch_id[1:]):02d}T09:00:00+08:00",
            type="batch_opened",
            batch=batch_id,
            payload={
                "hypothesis": f"{batch_id} 的假设",
                "dimensions": dimensions or {},
                "metric_specs": {},
            },
        ),
        Event(
            ts=f"2026-08-{int(batch_id[1:]):02d}T09:05:00+08:00",
            type="prediction",
            batch=batch_id,
            run=run,
            payload={
                "metrics": {"top1_acc": predicted},
                "rationale": f"{batch_id} 当初的理由",
                "confidence": "medium",
            },
        ),
        Event(
            ts=f"2026-08-{int(batch_id[1:]):02d}T12:00:00+08:00",
            type="run_result",
            batch=batch_id,
            run=run,
            payload={"seed": 0, "metrics": {"top1_acc": actual}},
        ),
    ]
    if cause is not None:
        events.append(
            Event(
                ts=f"2026-08-{int(batch_id[1:]):02d}T13:00:00+08:00",
                type="reflection",
                batch=batch_id,
                run=run,
                payload={"scope": "run", "cause": cause, "next": "下一步"},
            )
        )
    return events


LR_MODEL = {"lr": ["0.001", "0.0001"], "model": ["base", "large"]}


def _project(*event_lists):
    events = [e for group in event_lists for e in group]
    batches, _ = project(events)
    return batches


def test_no_history_returns_nothing():
    batches = _project(_batch("b1", "lr=0.0001,model=large", 0.83, 0.95, dimensions=LR_MODEL))
    target = batches["b1"].runs["lr=0.0001,model=large"]

    assert similar(batches, target) == []


def test_a_shared_dimension_and_the_same_direction_ranks_first():
    batches = _project(
        # 完全不沾边：没有共享的维度名
        _batch("b1", "opt=adam", 0.83, 0.95, cause="优化器的问题", dimensions={"opt": ["adam"]}),
        # 共享 lr 与 model，且同样是「预期低了、实测高了」
        _batch("b2", "lr=0.001,model=base", 0.83, 0.95, cause="增强没关", dimensions=LR_MODEL),
        _batch("b3", "lr=0.0001,model=large", 0.83, 0.95, dimensions=LR_MODEL),
    )
    target = batches["b3"].runs["lr=0.0001,model=large"]

    found = similar(batches, target)

    assert found[0].batch == "b2"
    assert found[0].cause == "增强没关"
    assert found[0].rationale == "b2 当初的理由"
    assert "top1_acc" in found[0].metrics


def test_only_reflected_surprises_are_recalled():
    # b1 是 SURPRISE 但没复盘——没有 cause 就提不出有信息量的追问
    batches = _project(
        _batch("b1", "lr=0.001,model=base", 0.83, 0.95, dimensions=LR_MODEL),
        _batch("b2", "lr=0.0001,model=large", 0.83, 0.95, dimensions=LR_MODEL),
    )
    target = batches["b2"].runs["lr=0.0001,model=large"]

    assert similar(batches, target) == []


def test_confirmed_history_is_not_recalled():
    batches = _project(
        _batch("b1", "lr=0.001,model=base", 0.83, 0.831, cause="符合预期", dimensions=LR_MODEL),
        _batch("b2", "lr=0.0001,model=large", 0.83, 0.95, dimensions=LR_MODEL),
    )
    target = batches["b2"].runs["lr=0.0001,model=large"]

    assert similar(batches, target) == []


def test_the_target_run_itself_is_excluded():
    batches = _project(
        _batch("b1", "lr=0.0001,model=large", 0.83, 0.95, cause="已经复盘过了",
               dimensions=LR_MODEL)
    )
    target = batches["b1"].runs["lr=0.0001,model=large"]

    assert [r.batch for r in similar(batches, target)] == []


def test_opposite_direction_scores_lower_than_the_same_direction():
    batches = _project(
        # 反方向：预期高了、实测低了
        _batch("b1", "lr=0.001,model=base", 0.83, 0.70, cause="反方向", dimensions=LR_MODEL),
        _batch("b2", "lr=0.001,model=large", 0.83, 0.95, cause="同方向", dimensions=LR_MODEL),
        _batch("b3", "lr=0.0001,model=large", 0.83, 0.95, dimensions=LR_MODEL),
    )
    target = batches["b3"].runs["lr=0.0001,model=large"]

    found = similar(batches, target)

    assert [r.cause for r in found] == ["同方向", "反方向"]


def test_limit_is_respected_and_ties_break_by_batch_order():
    batches = _project(
        _batch("b1", "lr=0.001,model=base", 0.83, 0.95, cause="第一条", dimensions=LR_MODEL),
        _batch("b2", "lr=0.01,model=base", 0.83, 0.95, cause="第二条", dimensions=LR_MODEL),
        _batch("b3", "lr=0.1,model=base", 0.83, 0.95, cause="第三条", dimensions=LR_MODEL),
        _batch("b4", "lr=0.0001,model=large", 0.83, 0.95, dimensions=LR_MODEL),
    )
    target = batches["b4"].runs["lr=0.0001,model=large"]

    assert [r.cause for r in similar(batches, target, limit=2)] == ["第一条", "第二条"]
    assert len(similar(batches, target, limit=99)) == 3


def test_reflection_payload_survives_the_projection():
    # recall 需要 cause 的原文，投影层必须把 reflection 的 payload 留下来
    batches = _project(
        _batch("b1", "lr=0.001,model=base", 0.83, 0.95, cause="留住我", dimensions=LR_MODEL)
    )

    run = batches["b1"].runs["lr=0.001,model=base"]

    assert run.closed
    assert run.reflection["cause"] == "留住我"
