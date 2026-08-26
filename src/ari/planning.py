"""ari plan：批次设计与预测表。见 spec §4.1。

分两段编辑而不是一次填完：第一段决定这轮扫什么（假设、变量维度、指标），
第二段才是逐个 run 的预测。这与人实际的思考顺序一致——先定 sweep，再
对每一格给判断——而且第一段填完才知道有哪些 run，预测表没法凭空生成。

批量编辑而非逐项问答：填第 3 行预测时人会回头参考前两行，这个横向比较
既降低摩擦又提高预测质量，逐项问答恰好把它关掉了。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import yaml

from .drafts import parse_prediction
from .events import Event
from .metrics import MetricSpec, UnknownMetricError, spec_for
from .runkey import make_run_key

CONFIDENCE_LEVELS = ("low", "medium", "high")


class ValidationFailed(Exception):
    """草稿有问题。errors 会被回填到草稿顶部让用户在原地改。"""

    def __init__(self, errors: list[str]):
        super().__init__("；".join(errors))
        self.errors = errors


@dataclass
class Design:
    hypothesis: str
    dimensions: dict[str, list]
    metrics: list[str]
    metric_specs: dict[str, MetricSpec] = field(default_factory=dict)
    result_path: str | None = None
    expected_ranking: dict | None = None
    research_direction: str = ""
    idea: str = ""


def next_batch_id(batches: dict) -> str:
    """b1 / b2 / ...。认不出的 id 直接忽略，不因手写过的怪 id 卡住。"""
    used = []
    for key in batches:
        if isinstance(key, str) and key.startswith("b") and key[1:].isdigit():
            used.append(int(key[1:]))
    return f"b{max(used, default=0) + 1}"


DESIGN_DRAFT = """\
# ── 批次 {batch_id} 的设计 ──────────────────────────────────────────
# 填完保存退出，下一步会根据变量维度生成预测表。
# 想放弃就清空整个文件再保存。

# 这一轮到底要验证什么？写给三个月后的自己看。
hypothesis: |
  {hypothesis_placeholder}

# 变量维度。笛卡尔积决定这一批有哪些 run。
# 例：model: [base, large] 与 lr: [1e-3, 1e-4] 会展开成 4 个 run。
dimensions:
  model: [base, large]

# 关心哪些指标。留空则用按指标名推断的默认规格：
#   名字含 acc / f1 / auc / bleu → 越大越好，绝对容差 0.005
#   名字含 loss / ppl            → 越小越好，相对容差 10%
# 推断不出来的指标必须自己写清楚，例如：
#   gpu_hours: {{direction: lower_better, compare: relative, tolerance: 0.2}}
metrics:
  top1_acc:

# 结果文件在哪。ari result 靠这个模板反解出 (run, seed)，确定性对齐。
# {{变量名}} 对应上面 dimensions 的键，{{seed}} 是重复实验的编号。
# 不填的话 ari result 会退回手工填写。
result_path: "logs/{{model}}/s{{seed}}/results.json"

# 相对排序的预测（可选）。排序通常比绝对值更容易预测准，也更有信息量。
# 按你预期的从好到差排列 run，run 名就是下一步预测表里的那些。
expected_ranking:
#   metric: top1_acc
#   order: [model=large, model=base]
"""

_HYPOTHESIS_PLACEHOLDER = "<在这里写这一轮要验证什么>"


def build_design_draft(batch_id: str) -> str:
    return DESIGN_DRAFT.format(
        batch_id=batch_id, hypothesis_placeholder=_HYPOTHESIS_PLACEHOLDER
    )


def _load_yaml(text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValidationFailed([f"YAML 格式有问题：{exc}"]) from exc
    if data is None:
        raise ValidationFailed(["草稿是空的"])
    if not isinstance(data, dict):
        raise ValidationFailed(["草稿的顶层应该是一组字段"])
    return data


def parse_design(text: str) -> Design:
    data = _load_yaml(text)
    errors: list[str] = []

    hypothesis = (data.get("hypothesis") or "").strip()
    if not hypothesis or _HYPOTHESIS_PLACEHOLDER in hypothesis:
        errors.append("hypothesis 不能为空——事后要靠它才知道当初在验证什么")

    dimensions = data.get("dimensions") or {}
    if not isinstance(dimensions, dict) or not dimensions:
        errors.append("dimensions 至少要有一个变量维度")
        dimensions = {}
    else:
        for name, values in dimensions.items():
            if not isinstance(values, (list, tuple)) or not values:
                errors.append(f"dimensions.{name} 需要一个非空的取值列表")

    raw_metrics = data.get("metrics") or {}
    if not isinstance(raw_metrics, dict) or not raw_metrics:
        errors.append("metrics 至少要有一个指标")
        raw_metrics = {}

    metric_specs: dict[str, MetricSpec] = {}
    declared = {k: v for k, v in raw_metrics.items() if isinstance(v, dict)}
    for name in raw_metrics:
        try:
            metric_specs[name] = spec_for(name, declared)
        except UnknownMetricError as exc:
            errors.append(str(exc))
        except (TypeError, ValueError) as exc:
            errors.append(f"指标 {name} 的规格有问题：{exc}")

    ranking = data.get("expected_ranking") or None
    if ranking is not None:
        if not isinstance(ranking, dict):
            errors.append("expected_ranking 应该有 metric 与 order 两个字段")
            ranking = None
        else:
            if not ranking.get("metric"):
                errors.append("expected_ranking 缺少 metric——多指标时无法判定排序")
            if not ranking.get("order"):
                errors.append("expected_ranking 缺少 order")

    if errors:
        raise ValidationFailed(errors)

    return Design(
        hypothesis=hypothesis,
        dimensions=dimensions,
        metrics=list(raw_metrics),
        metric_specs=metric_specs,
        result_path=(data.get("result_path") or None),
        expected_ranking=ranking,
    )


def expand_runs(dimensions: dict[str, list]) -> list[str]:
    """笛卡尔积展开成规范化的 run key 列表。顺序稳定。"""
    if not dimensions:
        return []
    names = list(dimensions)
    return [
        make_run_key(dict(zip(names, combo)))
        for combo in itertools.product(*(dimensions[n] for n in names))
    ]


_PREDICTION_HEADER = """\
# ── {title} ────────────────────────────────────────────────────────
# 实验开跑之前填完。保存退出即锁定；之后要改只能走 prediction_revised，
# 原值会永久保留并在看板上标「已修订」。
# 想放弃就清空整个文件再保存。
#
# 假设：{hypothesis}
#
# 预测值可以写点估计（0.83）或区间（[0.80, 0.84]）。
# 区间通常更诚实，也让「符合预期 / 超出预期」的判定更有意义。
#
# rationale 必填。缺了它，事后只知道猜错了，无法定位错的是哪个假设——
# 而定位到那个假设，正是这整套流程唯一的产出。
#
# 建议横着填：填第三行时回头看看前两行，预测会更一致也更准。

runs:
"""


def build_prediction_draft(design: Design, runs: list[str], batch_id: str = "") -> str:
    title = f"批次 {batch_id} 的预测表" if batch_id else "预测表"
    lines = [
        _PREDICTION_HEADER.format(
            title=title, hypothesis=design.hypothesis.strip().replace("\n", " ")
        )
    ]
    for run in runs:
        lines.append(f"  - run: {run}")
        for metric in design.metrics:
            lines.append(f"    {metric}:")
        lines.append("    confidence:   # low / medium / high")
        lines.append("    rationale:    # 必填：你为什么这么预期")
        lines.append("")
    return "\n".join(lines)


def parse_predictions(text: str, design: Design, runs: list[str]) -> dict[str, dict]:
    data = _load_yaml(text)
    errors: list[str] = []

    entries = data.get("runs")
    if not isinstance(entries, list) or not entries:
        raise ValidationFailed(["runs 是空的——预测表还没填"])

    by_run: dict[str, dict] = {}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"第 {index} 条不是一组字段")
            continue
        run = entry.get("run")
        if not run:
            errors.append(f"第 {index} 条缺少 run")
            continue
        if run not in runs:
            errors.append(f"run {run!r} 不在这个批次的变量组合里")
            continue

        metrics = {}
        for metric in design.metrics:
            raw = entry.get(metric)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                errors.append(f"{run} 的 {metric} 还没填")
                continue
            try:
                metrics[metric] = parse_prediction(raw)
            except ValueError as exc:
                errors.append(f"{run} 的 {metric}：{exc}")

        rationale = (entry.get("rationale") or "")
        rationale = rationale.strip() if isinstance(rationale, str) else str(rationale)
        if not rationale:
            errors.append(f"{run} 的 rationale 还没填——它是这套流程唯一的产出")

        confidence = entry.get("confidence")
        confidence = confidence.strip() if isinstance(confidence, str) else confidence
        if confidence not in CONFIDENCE_LEVELS:
            errors.append(
                f"{run} 的 confidence 应该是 {'/'.join(CONFIDENCE_LEVELS)} 之一，"
                f"收到 {confidence!r}"
            )

        by_run[run] = {
            "metrics": metrics,
            "confidence": confidence,
            "rationale": rationale,
        }

    for run in runs:
        if run not in by_run:
            errors.append(f"run {run} 还没有预测")

    if design.expected_ranking:
        for run in design.expected_ranking.get("order") or []:
            if run not in runs:
                errors.append(f"expected_ranking 里的 {run!r} 不是这个批次的 run")

    if errors:
        raise ValidationFailed(errors)
    return by_run


def _jsonable(value):
    """tuple 进不了 jsonl，区间统一转成 list。"""
    return list(value) if isinstance(value, tuple) else value


def build_events(
    batch_id: str, design: Design, predictions: dict[str, dict], now: str
) -> list[Event]:
    """把设计与预测转成事件。ts 由调用方注入，保证可测。"""
    opened = Event(
        ts=now,
        type="batch_opened",
        batch=batch_id,
        payload={
            "hypothesis": design.hypothesis,
            "research_direction": design.research_direction,
            "idea": (design.idea or "").strip(),
            "dimensions": design.dimensions,
            "metric_specs": {
                name: {
                    "direction": spec.direction,
                    "compare": spec.compare,
                    "tolerance": spec.tolerance,
                }
                for name, spec in design.metric_specs.items()
            },
            "result_path": design.result_path,
            "expected_ranking": design.expected_ranking,
        },
    )

    events = [opened]
    for run, payload in predictions.items():
        events.append(
            Event(
                ts=now,
                type="prediction",
                batch=batch_id,
                run=run,
                payload={
                    "metrics": {k: _jsonable(v) for k, v in payload["metrics"].items()},
                    "confidence": payload["confidence"],
                    "rationale": payload["rationale"],
                },
            )
        )
    return events
