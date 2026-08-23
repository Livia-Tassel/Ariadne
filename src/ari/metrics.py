"""指标规格。见 spec §3.5。

比较方式必须逐个指标声明：acc 从 0.80 到 0.84 只有 5% 相对偏差却可能
是重大提升，loss 从 0.31 到 0.34 是 10% 却可能无所谓。统一阈值在科研
语境下不成立。

默认表只覆盖高置信度的命名习惯；匹配不上就报错要求显式声明，不猜。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

DIRECTIONS = ("higher_better", "lower_better")
COMPARES = ("absolute", "relative")


class UnknownMetricError(ValueError):
    """指标既未声明规格，也匹配不上任何默认规则。"""


@dataclass(frozen=True)
class MetricSpec:
    direction: str = "higher_better"
    compare: str = "relative"
    tolerance: float = 0.10

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction 必须是 {DIRECTIONS} 之一，收到 {self.direction!r}")
        if self.compare not in COMPARES:
            raise ValueError(f"compare 必须是 {COMPARES} 之一，收到 {self.compare!r}")
        if self.tolerance < 0:
            raise ValueError(f"tolerance 不能为负，收到 {self.tolerance!r}")


# 顺序敏感：先匹配先生效。
_DEFAULT_PATTERNS: list[tuple[str, MetricSpec]] = [
    ("*acc*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*f1*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*auc*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*bleu*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*err*", MetricSpec("lower_better", "absolute", 0.005)),
    ("*loss*", MetricSpec("lower_better", "relative", 0.10)),
    ("*perplexity*", MetricSpec("lower_better", "relative", 0.10)),
    ("*ppl*", MetricSpec("lower_better", "relative", 0.10)),
]


def default_spec(name: str) -> MetricSpec | None:
    lowered = name.lower()
    for pattern, spec in _DEFAULT_PATTERNS:
        if fnmatch.fnmatch(lowered, pattern):
            return spec
    return None


def spec_for(name: str, declared: dict) -> MetricSpec:
    """取某指标的规格：显式声明优先，其次默认表，都没有则报错。"""
    if name in declared:
        value = declared[name]
        return value if isinstance(value, MetricSpec) else MetricSpec(**value)
    spec = default_spec(name)
    if spec is None:
        raise UnknownMetricError(
            f"指标 {name!r} 没有默认规格，请在 batch_opened 的 metric_specs 中"
            f"声明 direction / compare / tolerance"
        )
    return spec
