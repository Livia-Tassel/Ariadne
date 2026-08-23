import pytest

from ari.metrics import MetricSpec, UnknownMetricError, spec_for


def test_declared_spec_wins_over_default():
    spec = spec_for(
        "top1_acc",
        {"top1_acc": {"direction": "higher_better", "compare": "relative", "tolerance": 0.2}},
    )
    assert spec == MetricSpec("higher_better", "relative", 0.2)


@pytest.mark.parametrize(
    "name,direction,compare",
    [
        ("top1_acc", "higher_better", "absolute"),
        ("val_accuracy", "higher_better", "absolute"),
        ("macro_f1", "higher_better", "absolute"),
        ("train_loss", "lower_better", "relative"),
        ("ppl", "lower_better", "relative"),
        ("test_perplexity", "lower_better", "relative"),
        ("word_err_rate", "lower_better", "absolute"),
    ],
)
def test_defaults_by_name_pattern(name, direction, compare):
    spec = spec_for(name, {})
    assert spec.direction == direction
    assert spec.compare == compare


def test_unmatched_metric_raises_instead_of_guessing():
    with pytest.raises(UnknownMetricError) as exc:
        spec_for("gpu_hours", {})
    assert "gpu_hours" in str(exc.value)


def test_partial_declaration_fills_remaining_fields_from_dataclass_defaults():
    spec = spec_for("gpu_hours", {"gpu_hours": {"direction": "lower_better"}})
    assert spec.direction == "lower_better"
    assert spec.compare == "relative"
    assert spec.tolerance == 0.10


def test_invalid_direction_is_rejected():
    with pytest.raises(ValueError):
        spec_for("acc", {"acc": {"direction": "bigger"}})
