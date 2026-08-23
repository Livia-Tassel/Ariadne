from ari.events import Event
from ari.project import project
from ari.verdict import Verdict


def _batch_opened(**overrides):
    payload = {
        "hypothesis": "large 比 base 好",
        "dimensions": {"model": ["base", "large"]},
        "metric_specs": {},
    }
    payload.update(overrides)
    return Event(
        ts="2026-08-23T10:00:00+08:00", type="batch_opened", batch="b1", payload=payload
    )


def _prediction(run, metrics, ts="2026-08-23T10:05:00+08:00", **extra):
    payload = {"metrics": metrics, "rationale": "因为容量更大", "confidence": "medium"}
    payload.update(extra)
    return Event(ts=ts, type="prediction", batch="b1", run=run, payload=payload)


def _result(run, metrics, seed=0, mtime="2026-08-23T12:00:00+08:00"):
    return Event(
        ts="2026-08-23T12:30:00+08:00",
        type="run_result",
        batch="b1",
        run=run,
        payload={
            "seed": seed,
            "metrics": metrics,
            "source": {
                "path": f"logs/{run}/s{seed}/results.json",
                "kind": "structured",
                "mtime": mtime,
            },
        },
    )


def test_hypothesis_is_snapshotted_on_the_batch():
    batches, _ = project([_batch_opened()])

    assert batches["b1"].hypothesis == "large 比 base 好"


def test_prediction_and_result_produce_a_verdict():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=large", {"top1_acc": 0.830}),
            _result("model=large", {"top1_acc": 0.831}),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.CONFIRMED
    assert run.aggregates["top1_acc"].n == 1


def test_multiple_seeds_aggregate_into_one_run():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=large", {"top1_acc": 0.830}),
            _result("model=large", {"top1_acc": 0.828}, seed=0),
            _result("model=large", {"top1_acc": 0.832}, seed=1),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.aggregates["top1_acc"].n == 2


def test_duplicate_prediction_is_rejected_and_warned():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=large", {"top1_acc": 0.830}),
            _prediction("model=large", {"top1_acc": 0.900}),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.prediction["metrics"]["top1_acc"] == 0.830
    assert any("重复" in w for w in run.warnings)


def test_revision_keeps_the_original_and_marks_revised():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=large", {"top1_acc": 0.830}),
            Event(
                ts="2026-08-23T10:30:00+08:00",
                type="prediction_revised",
                batch="b1",
                run="model=large",
                payload={"metrics": {"top1_acc": 83.0}, "rationale": "单位写错了"},
            ),
        ]
    )

    run = batches["b1"].runs["model=large"]
    assert run.revised is True
    assert run.prediction["metrics"]["top1_acc"] == 83.0
    assert run.original_prediction["metrics"]["top1_acc"] == 0.830


def test_result_older_than_prediction_is_flagged():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=large", {"top1_acc": 0.830}, ts="2026-08-23T10:05:00+08:00"),
            _result("model=large", {"top1_acc": 0.831}, mtime="2026-08-23T09:00:00+08:00"),
        ]
    )

    assert "result_predates_prediction" in batches["b1"].runs["model=large"].integrity


def test_surprise_run_needs_its_own_reflection_to_close():
    events = [
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=large", {"top1_acc": 0.950}),
        Event(
            ts="2026-08-23T13:00:00+08:00",
            type="reflection",
            batch="b1",
            payload={"scope": "batch", "text": "整体收口"},
        ),
    ]

    batches, _ = project(events)
    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.SURPRISE
    assert run.closed is False
    assert batches["b1"].closed is False

    events.append(
        Event(
            ts="2026-08-23T13:10:00+08:00",
            type="reflection",
            batch="b1",
            run="model=large",
            payload={"scope": "run", "text": "数据增强没关"},
        )
    )
    batches, _ = project(events)
    assert batches["b1"].runs["model=large"].closed is True
    assert batches["b1"].closed is True


def test_confirmed_run_closes_via_batch_reflection():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=large", {"top1_acc": 0.830}),
            _result("model=large", {"top1_acc": 0.831}),
            Event(
                ts="2026-08-23T13:00:00+08:00",
                type="reflection",
                batch="b1",
                payload={"scope": "batch", "text": "符合预期"},
            ),
        ]
    )

    assert batches["b1"].runs["model=large"].closed is True


def test_all_confirmed_batch_raises_the_low_information_signal():
    batches, _ = project(
        [
            _batch_opened(),
            _prediction("model=base", {"top1_acc": 0.800}),
            _prediction("model=large", {"top1_acc": 0.830}),
            _result("model=base", {"top1_acc": 0.801}),
            _result("model=large", {"top1_acc": 0.831}),
        ]
    )

    assert batches["b1"].info_signal is not None


def test_ranking_is_judged_at_batch_level():
    batches, _ = project(
        [
            _batch_opened(
                expected_ranking={
                    "metric": "top1_acc",
                    "order": ["model=large", "model=base"],
                }
            ),
            _prediction("model=base", {"top1_acc": 0.800}),
            _prediction("model=large", {"top1_acc": 0.830}),
            _result("model=base", {"top1_acc": 0.860}),
            _result("model=large", {"top1_acc": 0.801}),
        ]
    )

    assert batches["b1"].ranking.verdict is Verdict.SURPRISE


def test_unknown_event_type_is_warned_not_fatal():
    batches, warnings = project(
        [
            _batch_opened(),
            Event(ts="2026-08-23T14:00:00+08:00", type="from_the_future", batch="b1",
                  v=99, payload={}),
        ]
    )

    assert "b1" in batches
    assert any("from_the_future" in w for w in warnings)


def test_event_for_unopened_batch_is_warned():
    batches, warnings = project([_prediction("model=large", {"top1_acc": 0.8})])

    assert batches == {}
    assert any("b1" in w for w in warnings)
