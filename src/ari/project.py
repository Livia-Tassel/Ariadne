"""事件流 → 状态投影。见 spec §3.2、§3.7、§3.10。

runs.jsonl 是唯一真相来源，所有展示用的状态都是这里折叠出来的派生物。
board.md 与 beliefs.md 都可以删掉重新生成，不丢数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .events import SCHEMA_VERSION, Event
from .metrics import UnknownMetricError, spec_for
from .verdict import (
    Aggregate,
    RankingJudgement,
    Verdict,
    aggregate,
    judge_ranking,
    judge_run,
)

_KNOWN_TYPES = {
    "batch_opened",
    "prediction",
    "prediction_revised",
    "run_result",
    "reflection",
    "belief_added",
    "belief_weakened",
    "belief_reinforced",
    "belief_refuted",
    "note",
}

LOW_INFORMATION_SIGNAL = "本批次全部命中预期，未产生新信息——变量取值范围可能过于保守"


@dataclass
class RunState:
    batch: str
    run: str
    prediction: dict | None = None
    original_prediction: dict | None = None
    prediction_ts: str | None = None
    revised: bool = False
    samples: dict[str, dict[int, float]] = field(default_factory=dict)
    aggregates: dict[str, Aggregate] = field(default_factory=dict)
    verdict: Verdict = Verdict.NO_RESULT
    metric_judgements: dict = field(default_factory=dict)
    closed: bool = False
    reflection: dict | None = None
    integrity: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchState:
    id: str
    research_direction: str = ""
    hypothesis: str = ""
    dimensions: dict = field(default_factory=dict)
    metric_specs: dict = field(default_factory=dict)
    expected_ranking: dict | None = None
    result_path: str | None = None
    opened_ts: str = ""
    runs: dict[str, RunState] = field(default_factory=dict)
    ranking: RankingJudgement | None = None
    batch_reflection: bool = False
    closed: bool = False
    info_signal: str | None = None
    warnings: list[str] = field(default_factory=list)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def project(events: list[Event]) -> tuple[dict[str, BatchState], list[str]]:
    """把事件流折叠成 batch/run 状态。返回 (batches, 全局警告)。"""
    batches: dict[str, BatchState] = {}
    warnings: list[str] = []

    for event in events:
        if event.v > SCHEMA_VERSION or event.type not in _KNOWN_TYPES:
            warnings.append(
                f"第 {event.line_no} 行：未知事件类型 {event.type!r}（v={event.v}），"
                f"已跳过。可能需要升级 ari"
            )
            continue

        if event.type == "batch_opened":
            batches[event.batch] = BatchState(
                id=event.batch,
                research_direction=event.payload.get("research_direction", ""),
                hypothesis=event.payload.get("hypothesis", ""),
                dimensions=event.payload.get("dimensions", {}),
                metric_specs=event.payload.get("metric_specs", {}),
                expected_ranking=event.payload.get("expected_ranking"),
                result_path=event.payload.get("result_path"),
                opened_ts=event.ts,
            )
            continue

        if event.type == "note" or event.type.startswith("belief_"):
            continue  # 信念跨批次存活，由 beliefs.py 单独投影

        batch = batches.get(event.batch)
        if batch is None:
            warnings.append(
                f"第 {event.line_no} 行：事件属于未开启的批次 {event.batch!r}，已跳过"
            )
            continue

        if event.type == "reflection":
            scope = event.payload.get("scope", "run" if event.run else "batch")
            if scope == "batch" or not event.run:
                batch.batch_reflection = True
            else:
                run = _run_state(batch, event.run)
                run.closed = True
                # payload 留着：recall.py 要用 cause 的原文去做历史检索，
                # 只留一个 closed 布尔值就得再遍历一遍事件流。
                run.reflection = event.payload
            continue

        if event.run is None:
            warnings.append(f"第 {event.line_no} 行：{event.type} 缺少 run 字段，已跳过")
            continue

        run = _run_state(batch, event.run)

        if event.type == "prediction":
            if run.prediction is not None:
                run.warnings.append(
                    f"第 {event.line_no} 行：重复的 prediction 已忽略；"
                    f"修订请使用 prediction_revised"
                )
                continue
            run.prediction = event.payload
            run.prediction_ts = event.ts

        elif event.type == "prediction_revised":
            if run.prediction is None:
                run.warnings.append(f"第 {event.line_no} 行：修订了不存在的预测，已忽略")
                continue
            if run.original_prediction is None:
                run.original_prediction = run.prediction
            run.prediction = event.payload
            run.revised = True

        elif event.type == "run_result":
            seed = event.payload.get("seed", 0)
            for name, value in (event.payload.get("metrics") or {}).items():
                run.samples.setdefault(name, {})[seed] = float(value)
            _check_integrity(run, event)

    for batch in batches.values():
        _finalize(batch)

    return batches, warnings


def _run_state(batch: BatchState, run_key: str) -> RunState:
    if run_key not in batch.runs:
        batch.runs[run_key] = RunState(batch=batch.id, run=run_key)
    return batch.runs[run_key]


def _check_integrity(run: RunState, event: Event) -> None:
    """结果文件早于预测写入时间 → 先看结果再写预测的嫌疑。见 spec §2.1。"""
    mtime = _parse_ts((event.payload.get("source") or {}).get("mtime"))
    predicted_at = _parse_ts(run.prediction_ts)
    if mtime and predicted_at and mtime < predicted_at:
        if "result_predates_prediction" not in run.integrity:
            run.integrity.append("result_predates_prediction")


def _finalize(batch: BatchState) -> None:
    for run in batch.runs.values():
        run.aggregates = {
            name: aggregate(list(by_seed.values())) for name, by_seed in run.samples.items()
        }
        prediction_metrics = (run.prediction or {}).get("metrics", {})
        try:
            specs = {name: spec_for(name, batch.metric_specs) for name in prediction_metrics}
        except UnknownMetricError as exc:
            run.warnings.append(str(exc))
            run.verdict = Verdict.UNVERIFIED
            continue
        run.verdict, run.metric_judgements = judge_run(
            prediction_metrics, run.aggregates, specs
        )

    _finalize_ranking(batch)

    if batch.batch_reflection:
        for run in batch.runs.values():
            if run.verdict is Verdict.CONFIRMED:
                run.closed = True
    batch.closed = batch.batch_reflection and not closure_blockers(batch)

    all_confirmed = bool(batch.runs) and all(
        r.verdict is Verdict.CONFIRMED for r in batch.runs.values()
    )
    ranking_ok = batch.ranking is None or batch.ranking.verdict in (
        Verdict.CONFIRMED,
        Verdict.NO_RESULT,
    )
    batch.info_signal = LOW_INFORMATION_SIGNAL if all_confirmed and ranking_ok else None


def closure_blockers(batch: BatchState) -> list[str]:
    """返回阻止批次收口的原因。

    原设计只检查未复盘 SURPRISE，导致完全没有结果或明显 NOISY 的批次也能
    被标成「已收口」。GUI 把这个漏洞暴露得很明显，因此领域层统一修正。
    """
    groups = {
        Verdict.NO_RESULT: "还有 run 尚无结果",
        Verdict.UNVERIFIED: "还有结果待确认",
        Verdict.NOISY: "还有 run 的噪声大于判定分辨率",
    }
    blockers = [
        message
        for verdict, message in groups.items()
        if any(run.verdict is verdict for run in batch.runs.values())
    ]
    if any(run.verdict is Verdict.SURPRISE and not run.closed for run in batch.runs.values()):
        blockers.append("还有 SURPRISE 未复盘")
    return blockers


def _finalize_ranking(batch: BatchState) -> None:
    if not batch.expected_ranking:
        return
    metric = batch.expected_ranking.get("metric")
    order = batch.expected_ranking.get("order") or []
    if not metric:
        batch.warnings.append("expected_ranking 缺少 metric 字段，无法判定排序")
        return
    aggregates = {
        key: run.aggregates[metric]
        for key, run in batch.runs.items()
        if metric in run.aggregates
    }
    try:
        spec = spec_for(metric, batch.metric_specs)
    except UnknownMetricError as exc:
        batch.warnings.append(str(exc))
        return
    batch.ranking = judge_ranking(order, aggregates, spec)
