"""共享的事件构造辅助。

test_project 与 test_board 都需要造事件序列；构造逻辑放这里，
两边共用一套，避免两份会各自漂移的副本。
"""

from __future__ import annotations

import pytest

from ari.events import Event

BATCH = "b1"
RUN = "model=large"


def make_batch_opened(**overrides) -> Event:
    payload = {
        "hypothesis": "large 比 base 好",
        "dimensions": {"model": ["base", "large"]},
        "metric_specs": {},
    }
    payload.update(overrides)
    return Event(
        ts="2026-08-23T10:00:00+08:00", type="batch_opened", batch=BATCH, payload=payload
    )


def make_prediction(run, metrics, ts="2026-08-23T10:05:00+08:00", **extra) -> Event:
    payload = {"metrics": metrics, "rationale": "因为容量更大", "confidence": "medium"}
    payload.update(extra)
    return Event(ts=ts, type="prediction", batch=BATCH, run=run, payload=payload)


def make_result(run, metrics, seed=0, mtime="2026-08-23T12:00:00+08:00") -> Event:
    return Event(
        ts="2026-08-23T12:30:00+08:00",
        type="run_result",
        batch=BATCH,
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


@pytest.fixture
def make_events():
    """造一个单 run 的最小批次。

    prediction: 预测值（点估计或区间）
    actual: 实测值，标量或多 seed 列表
    result_mtime: 结果文件 mtime，用于触发时序校验
    revise_to: 若给出，追加一条 prediction_revised
    """

    def _make(prediction, actual, result_mtime="2026-08-23T12:00:00+08:00", revise_to=None):
        events = [make_batch_opened(), make_prediction(RUN, {"top1_acc": prediction})]
        if revise_to is not None:
            events.append(
                Event(
                    ts="2026-08-23T10:30:00+08:00",
                    type="prediction_revised",
                    batch=BATCH,
                    run=RUN,
                    payload={"metrics": {"top1_acc": revise_to}, "rationale": "改了"},
                )
            )
        values = actual if isinstance(actual, list) else [actual]
        for seed, value in enumerate(values):
            events.append(make_result(RUN, {"top1_acc": value}, seed=seed, mtime=result_mtime))
        return events

    return _make
