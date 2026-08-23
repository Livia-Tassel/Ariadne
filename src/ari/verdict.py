"""判定引擎。见 spec §3.8、§3.9。

判定的对象是「该配置的期望表现」，不是某一次抽签结果，因此多 seed 先
聚合成均值与标准差，再与预测比对。标准差同时充当噪声基线：噪声大于
判定分辨率时不给结论，报 NOISY。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    NO_RESULT = "NO_RESULT"
    UNVERIFIED = "UNVERIFIED"
    CONFIRMED = "CONFIRMED"
    SURPRISE = "SURPRISE"
    NOISY = "NOISY"


@dataclass(frozen=True)
class Aggregate:
    mean: float
    sd: float | None
    n: int


def aggregate(values) -> Aggregate:
    """把同一 run 多个 seed 的结果聚合。sd 为样本标准差，单样本时为 None。"""
    numbers = [float(v) for v in values]
    if not numbers:
        raise ValueError("聚合需要至少一个结果值")
    return Aggregate(
        mean=statistics.fmean(numbers),
        sd=statistics.stdev(numbers) if len(numbers) >= 2 else None,
        n=len(numbers),
    )


@dataclass(frozen=True)
class MetricJudgement:
    verdict: Verdict
    deviation: float | None  # 实测均值 - 预测点估计；区间预测时为 None
    threshold: float | None  # 点估计的容差
    resolution: float  # 判定分辨率：区间宽度或容差
    note: str = ""


def _noise_blocks(agg: Aggregate, resolution: float) -> str | None:
    """噪声守门：2σ 超过判定分辨率时，这个实验设计分辨不出要问的差异。"""
    if agg.sd is None:
        return None
    noise = 2 * agg.sd
    if noise > resolution:
        return (
            f"2σ={noise:.4g} 超过判定分辨率 {resolution:.4g}，"
            f"需要更多 seed 或更大的变量跨度"
        )
    return None


def judge_metric(prediction, agg: Aggregate, spec) -> MetricJudgement:
    """判定单个指标。区间预测看是否落入，点估计看偏差是否在容差内。

    噪声守门先于判定：守门通过即保证 2σ ≤ resolution，因此阈值就是
    容差本身，无需再取 max。
    """
    if isinstance(prediction, (list, tuple)):
        low, high = sorted((float(prediction[0]), float(prediction[1])))
        resolution = high - low
        blocked = _noise_blocks(agg, resolution)
        if blocked:
            return MetricJudgement(Verdict.NOISY, None, None, resolution, blocked)
        verdict = Verdict.CONFIRMED if low <= agg.mean <= high else Verdict.SURPRISE
        return MetricJudgement(verdict, None, None, resolution)

    point = float(prediction)
    tolerance = spec.tolerance if spec.compare == "absolute" else spec.tolerance * abs(point)
    blocked = _noise_blocks(agg, tolerance)
    if blocked:
        return MetricJudgement(Verdict.NOISY, agg.mean - point, tolerance, tolerance, blocked)
    verdict = Verdict.CONFIRMED if abs(agg.mean - point) <= tolerance else Verdict.SURPRISE
    return MetricJudgement(verdict, agg.mean - point, tolerance, tolerance)
