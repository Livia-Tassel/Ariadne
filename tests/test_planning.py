import pytest
import yaml

from ari.planning import (
    ValidationFailed,
    build_design_draft,
    build_events,
    build_prediction_draft,
    expand_runs,
    next_batch_id,
    parse_design,
    parse_predictions,
)

DESIGN_TEXT = """
hypothesis: |
  large 比 base 好 3 个点以上
dimensions:
  model: [base, large]
metrics:
  top1_acc:
  train_loss:
result_path: "logs/{model}/s{seed}/results.json"
expected_ranking:
  metric: top1_acc
  order: [model=large, model=base]
"""


def test_next_batch_id_starts_at_b1():
    assert next_batch_id({}) == "b1"


def test_next_batch_id_continues_after_the_highest():
    assert next_batch_id({"b1": None, "b2": None}) == "b3"


def test_next_batch_id_ignores_unparseable_ids():
    assert next_batch_id({"b1": None, "手写的": None}) == "b2"


def test_design_draft_round_trips_through_the_parser():
    draft = build_design_draft("b1")
    # 草稿本身是合法 YAML（字段留空），只是校验不过
    assert isinstance(yaml.safe_load(draft), dict)


def test_design_draft_explains_every_field():
    draft = build_design_draft("b1")

    for field in ("hypothesis", "dimensions", "metrics", "result_path"):
        assert field in draft
    assert "#" in draft  # 有注释


def test_parse_design_reads_all_fields():
    design = parse_design(DESIGN_TEXT)

    assert "3 个点" in design.hypothesis
    assert design.dimensions == {"model": ["base", "large"]}
    assert list(design.metrics) == ["top1_acc", "train_loss"]
    assert design.result_path == "logs/{model}/s{seed}/results.json"
    assert design.expected_ranking["metric"] == "top1_acc"


def test_empty_hypothesis_is_rejected():
    with pytest.raises(ValidationFailed) as exc:
        parse_design("hypothesis: ''\ndimensions:\n  model: [base]\nmetrics:\n  acc:\n")

    assert any("hypothesis" in e for e in exc.value.errors)


def test_missing_dimensions_is_rejected():
    with pytest.raises(ValidationFailed) as exc:
        parse_design("hypothesis: 有\ndimensions: {}\nmetrics:\n  acc:\n")

    assert any("dimensions" in e for e in exc.value.errors)


def test_metric_without_a_known_spec_is_rejected_by_name():
    with pytest.raises(ValidationFailed) as exc:
        parse_design("hypothesis: 有\ndimensions:\n  model: [base]\nmetrics:\n  gpu_hours:\n")

    assert any("gpu_hours" in e for e in exc.value.errors)


def test_explicitly_declared_spec_makes_an_unknown_metric_acceptable():
    design = parse_design(
        "hypothesis: 有\ndimensions:\n  model: [base]\n"
        "metrics:\n  gpu_hours: {direction: lower_better, compare: relative, tolerance: 0.2}\n"
    )

    assert design.metric_specs["gpu_hours"].direction == "lower_better"


def test_malformed_yaml_is_reported_not_raised_raw():
    with pytest.raises(ValidationFailed) as exc:
        parse_design("hypothesis: [unclosed\n")

    assert exc.value.errors


def test_expand_runs_is_a_cartesian_product_in_stable_order():
    runs = expand_runs({"model": ["base", "large"], "lr": ["1e-3", "1e-4"]})

    # 后声明的维度变化最快：按 model 分组，组内比 lr。
    # 读预测表时这个顺序才顺——同一个模型的两个 lr 挨着。
    assert runs == [
        "lr=0.001,model=base",
        "lr=0.0001,model=base",
        "lr=0.001,model=large",
        "lr=0.0001,model=large",
    ]


def test_expand_runs_normalizes_numeric_spellings():
    assert expand_runs({"lr": ["1e-4"]}) == expand_runs({"lr": ["0.0001"]})


def test_prediction_draft_lists_every_run_and_metric():
    design = parse_design(DESIGN_TEXT)
    draft = build_prediction_draft(design, expand_runs(design.dimensions))

    for run in ("model=base", "model=large"):
        assert run in draft
    assert "top1_acc" in draft and "train_loss" in draft
    assert "rationale" in draft


def test_prediction_draft_says_why_rationale_matters():
    design = parse_design(DESIGN_TEXT)
    draft = build_prediction_draft(design, expand_runs(design.dimensions))

    assert "必填" in draft


FILLED = """
runs:
  - run: model=base
    top1_acc: [0.78, 0.81]
    train_loss: 0.42
    confidence: high
    rationale: 跑过很多次的基线
  - run: model=large
    top1_acc: [0.82, 0.85]
    train_loss: 0.35
    confidence: medium
    rationale: 容量翻倍但数据量没变
"""


def test_parse_predictions_reads_intervals_and_points():
    design = parse_design(DESIGN_TEXT)
    predictions = parse_predictions(FILLED, design, expand_runs(design.dimensions))

    assert predictions["model=base"]["metrics"]["top1_acc"] == (0.78, 0.81)
    assert predictions["model=base"]["metrics"]["train_loss"] == 0.42
    assert predictions["model=large"]["confidence"] == "medium"


def test_missing_metric_value_names_the_run_and_the_metric():
    design = parse_design(DESIGN_TEXT)
    text = FILLED.replace("    train_loss: 0.42\n", "    train_loss:\n")

    with pytest.raises(ValidationFailed) as exc:
        parse_predictions(text, design, expand_runs(design.dimensions))

    joined = " ".join(exc.value.errors)
    assert "model=base" in joined and "train_loss" in joined


def test_blank_rationale_is_rejected():
    design = parse_design(DESIGN_TEXT)
    text = FILLED.replace("    rationale: 跑过很多次的基线\n", "    rationale:\n")

    with pytest.raises(ValidationFailed) as exc:
        parse_predictions(text, design, expand_runs(design.dimensions))

    assert any("rationale" in e for e in exc.value.errors)


def test_bad_confidence_is_rejected():
    design = parse_design(DESIGN_TEXT)
    text = FILLED.replace("confidence: high", "confidence: 非常有把握")

    with pytest.raises(ValidationFailed) as exc:
        parse_predictions(text, design, expand_runs(design.dimensions))

    assert any("confidence" in e for e in exc.value.errors)


def test_a_missing_run_is_rejected():
    design = parse_design(DESIGN_TEXT)
    text = FILLED[: FILLED.index("  - run: model=large")]

    with pytest.raises(ValidationFailed) as exc:
        parse_predictions(text, design, expand_runs(design.dimensions))

    assert any("model=large" in e for e in exc.value.errors)


def test_ranking_referring_to_an_unknown_run_is_rejected():
    text = DESIGN_TEXT.replace("order: [model=large, model=base]", "order: [model=huge]")

    design = parse_design(text)
    with pytest.raises(ValidationFailed) as exc:
        parse_predictions(FILLED, design, expand_runs(design.dimensions))

    assert any("model=huge" in e for e in exc.value.errors)


def test_build_events_emits_batch_opened_then_one_prediction_per_run():
    design = parse_design(DESIGN_TEXT)
    runs = expand_runs(design.dimensions)
    predictions = parse_predictions(FILLED, design, runs)

    events = build_events("b1", design, predictions, now="2026-08-24T10:00:00+08:00")

    assert [e.type for e in events] == ["batch_opened", "prediction", "prediction"]
    assert events[0].payload["hypothesis"].startswith("large")
    assert events[0].payload["expected_ranking"]["metric"] == "top1_acc"
    assert all(e.ts == "2026-08-24T10:00:00+08:00" for e in events)


def test_intervals_are_serialized_as_lists_not_tuples():
    import json

    design = parse_design(DESIGN_TEXT)
    runs = expand_runs(design.dimensions)
    events = build_events(
        "b1", design, parse_predictions(FILLED, design, runs), now="2026-08-24T10:00:00+08:00"
    )

    # tuple 进不了 jsonl，必须先转成 list
    dumped = json.dumps(events[1].payload)
    assert '"top1_acc": [0.78, 0.81]' in dumped


def test_metric_specs_are_snapshotted_onto_the_batch():
    design = parse_design(
        "hypothesis: 有\ndimensions:\n  model: [base]\n"
        "metrics:\n  gpu_hours: {direction: lower_better, compare: relative, tolerance: 0.2}\n"
    )
    events = build_events("b1", design, {}, now="t")

    assert events[0].payload["metric_specs"]["gpu_hours"]["tolerance"] == 0.2
