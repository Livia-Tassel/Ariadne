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
    "batch_meta_revised",
    "prediction",
    "prediction_revised",
    "run_result",
    "reflection",
    "belief_added",
    "belief_weakened",
    "belief_reinforced",
    "belief_refuted",
    "note",
    # 以下类型不属于批次投影，由 ideas.py / papers.py 单独投影。
    "idea_captured",
    "idea_discarded",
    "draft_opened",
    "section_saved",
    "draft_status_changed",
    # 调研跨批次存活，由 surveys.py 单独投影。
    "survey_opened",
    "survey_fetched",
    "paper_found",
    "paper_tiered",
    "paper_read",
    "paper_skipped",
    "survey_bottleneck",
    "survey_closed",
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
    idea: str = ""
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
                idea=(event.payload.get("idea") or "").strip(),
                dimensions=event.payload.get("dimensions", {}),
                metric_specs=event.payload.get("metric_specs", {}),
                expected_ranking=event.payload.get("expected_ranking"),
                result_path=event.payload.get("result_path"),
                opened_ts=event.ts,
            )
            continue

        if (
            event.type == "note"
            or event.type.startswith("belief_")
            or event.type.startswith("idea_")
            or event.type.startswith("draft_")
            or event.type.startswith("survey_")
            or event.type.startswith("paper_")
            or event.type == "section_saved"
        ):
            continue  # 信念/想法/草稿/调研跨批次存活，由各自模块单独投影

        batch = batches.get(event.batch)
        if batch is None:
            warnings.append(
                f"第 {event.line_no} 行：事件属于未开启的批次 {event.batch!r}，已跳过"
            )
            continue

        if event.type == "batch_meta_revised":
            # 只覆盖显式给出的字段：GUI 可能只补 result_path 而不动排序。
            if "result_path" in event.payload:
                batch.result_path = event.payload.get("result_path") or None
            if "expected_ranking" in event.payload:
                batch.expected_ranking = event.payload.get("expected_ranking") or None
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
            if run.samples:
                # 结果已经在库，预测才到。事件顺序本身就是证据，比
                # _check_integrity 的 mtime 比对更强：touch 一下文件绕不过去。
                _flag(run, "prediction_after_result")
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


def _flag(run: RunState, name: str) -> None:
    """记一条完整性标记。同一标记只记一次。"""
    if name not in run.integrity:
        run.integrity.append(name)


def _check_integrity(run: RunState, event: Event) -> None:
    """结果文件早于预测写入时间 → 先看结果再写预测的嫌疑。见 spec §2.1。"""
    mtime = _parse_ts((event.payload.get("source") or {}).get("mtime"))
    predicted_at = _parse_ts(run.prediction_ts)
    if mtime and predicted_at and mtime < predicted_at:
        _flag(run, "result_predates_prediction")


def _finalize(batch: BatchState) -> None:
    for run in batch.runs.values():
        run.aggregates = {
            name: aggregate(list(by_seed.values())) for name, by_seed in run.samples.items()
        }
        if run.aggregates and run.prediction is None:
            # 有实测值却没有预测。judge_run 会返回 NO_RESULT——那是纯内核的
            # 正确契约，但显示成「等待结果」是事实相反：这个 run 明明有数。
            # 用 UNVERIFIED（来源存疑待人工确认）：无法验证一个不存在的预测。
            _flag(run, "result_without_prediction")
            run.verdict = Verdict.UNVERIFIED
            continue
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

    UNVERIFIED 有两种来源，措辞必须分开：预测缺席是「结果先到」，其余才是
    笼统的「待确认」。渐进锁定让前者从罕见变成常见，说错会误导。
    """
    blockers = []
    if any(run.verdict is Verdict.NO_RESULT for run in batch.runs.values()):
        blockers.append("还有 run 尚无结果")
    unverified = [run for run in batch.runs.values() if run.verdict is Verdict.UNVERIFIED]
    if any("result_without_prediction" in run.integrity for run in unverified):
        blockers.append("还有 run 的结果先到、预测缺席")
    if any("result_without_prediction" not in run.integrity for run in unverified):
        blockers.append("还有结果待确认")
    if any(run.verdict is Verdict.NOISY for run in batch.runs.values()):
        blockers.append("还有 run 的噪声大于判定分辨率")
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
