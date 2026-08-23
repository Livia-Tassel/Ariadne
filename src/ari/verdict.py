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
