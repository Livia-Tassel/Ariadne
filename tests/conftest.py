"""共享的事件构造辅助。

test_project 与 test_board 都需要造事件序列；构造逻辑放这里，
两边共用一套，避免两份会各自漂移的副本。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.events import Event

BATCH = "b1"
RUN = "model=large"


@pytest.fixture(autouse=True)
def _no_real_api_keys(monkeypatch, tmp_path):
    """把 provider 的 API key 环境变量从所有测试里摘掉。

    spec §9：CI 不打真实 API。config.toml 模板里是真实的模型名，只要开发
    机上恰好导出了 ANTHROPIC_API_KEY，`ari plan` 的测试就会真的发一次请求
    ——花钱、变慢、结果不确定，而且没有任何一条断言会因此变红，你根本不会
    发现。需要 key 的测试自己 setenv，晚于本 fixture 生效。
    """
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    # GUI 能把 key / 模型写进用户级 credentials.toml。测试若读到开发机的
    # 真实文件，会在本应离线的 plan/review 测试里发起真实请求。显式传入路径
    # 的 credentials 单测仍使用自己的文件；默认路径一律隔离到 tmp_path。
    from ari import credentials

    monkeypatch.setattr(
        credentials,
        "credentials_path",
        lambda path=None: Path(path) if path is not None else tmp_path / "credentials.toml",
    )


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
