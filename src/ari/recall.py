"""历史检索。见 spec §7 第 2 步。

追问必须有针对性。「你觉得是为什么呢」这种问题不如不问——它只会让人
写下「不知道」。有针对性的前提是检索：本项目历史上有没有类似的意外，
当时写下的结论是什么。

这里没有 LLM，全是纯函数。检索本身可以严格断言，追问的质量才有地基。
相似度只用三个可解释的信号，不搞词向量：科研项目的批次数是几十条的
量级，可解释比精巧重要——你得能说出「为什么给我看这一条」。
"""

from __future__ import annotations

from dataclasses import dataclass

from .runkey import parse_run_key
from .verdict import Verdict

_SHARED_VARIABLE = 2
_SHARED_METRIC = 2
_SAME_DIRECTION = 1


@dataclass(frozen=True)
class Recalled:
    batch: str
    run: str
    cause: str
    next_step: str
    rationale: str
    metrics: tuple[str, ...]
    score: int


def _surprised_metrics(run) -> set[str]:
    return {
        name
        for name, judgement in run.metric_judgements.items()
        if judgement.verdict is Verdict.SURPRISE
    }


def _direction(run, metric: str) -> int:
    """实测偏高返回 +1，偏低返回 -1，说不清返回 0。

    点估计直接看 deviation 的符号；区间预测的 deviation 是 None，
    落在区间外哪一侧就得自己比一次。
    """
    judgement = run.metric_judgements.get(metric)
    if judgement is not None and judgement.deviation is not None:
        if judgement.deviation > 0:
            return 1
        if judgement.deviation < 0:
            return -1
        return 0

    agg = run.aggregates.get(metric)
    predicted = (run.prediction or {}).get("metrics", {}).get(metric)
    if agg is None or predicted is None:
        return 0
    if isinstance(predicted, (list, tuple)):
        low, high = sorted(float(v) for v in predicted)
        if agg.mean > high:
            return 1
        if agg.mean < low:
            return -1
        return 0
    return 0


def similar(batches: dict, target, limit: int = 3) -> list[Recalled]:
    """找出与 target 相似、且已经复盘过的历史 SURPRISE。

    只要已复盘的：没有 cause 的历史提不出有信息量的追问。
    """
    target_variables = set(parse_run_key(target.run))
    target_metrics = _surprised_metrics(target)
    target_directions = {name: _direction(target, name) for name in target_metrics}

    found: list[Recalled] = []
    for batch in batches.values():
        for run in batch.runs.values():
            if run is target or (batch.id == target.batch and run.run == target.run):
                continue
            if run.verdict is not Verdict.SURPRISE:
                continue
            cause = (run.reflection or {}).get("cause")
            if not cause:
                continue

            metrics = _surprised_metrics(run)
            shared_variables = target_variables & set(parse_run_key(run.run))
            shared_metrics = target_metrics & metrics
            same_direction = any(
                _direction(run, name) == target_directions[name] != 0
                for name in shared_metrics
            )

            score = (
                _SHARED_VARIABLE * len(shared_variables)
                + _SHARED_METRIC * len(shared_metrics)
                + (_SAME_DIRECTION if same_direction else 0)
            )
            if score <= 0:
                continue

            found.append(
                Recalled(
                    batch=batch.id,
                    run=run.run,
                    cause=cause,
                    next_step=(run.reflection or {}).get("next", ""),
                    rationale=(run.prediction or {}).get("rationale", ""),
                    metrics=tuple(sorted(metrics)),
                    score=score,
                )
            )

    # 同分时保持事件流顺序（sorted 是稳定的），取舍才是确定性的
    found.sort(key=lambda item: -item.score)
    return found[:limit]
