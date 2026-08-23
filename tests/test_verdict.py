import pytest

from ari.metrics import MetricSpec
from ari.verdict import Verdict, aggregate, judge_metric

ACC = MetricSpec("higher_better", "absolute", 0.005)
LOSS = MetricSpec("lower_better", "relative", 0.10)


def test_single_sample_has_no_standard_deviation():
    agg = aggregate([0.83])

    assert agg.mean == pytest.approx(0.83)
    assert agg.sd is None
    assert agg.n == 1


def test_multiple_samples_give_mean_and_sample_sd():
    agg = aggregate([0.80, 0.82, 0.84])

    assert agg.mean == pytest.approx(0.82)
    assert agg.sd == pytest.approx(0.02)
    assert agg.n == 3


def test_identical_samples_have_zero_sd():
    assert aggregate([0.5, 0.5, 0.5]).sd == pytest.approx(0.0)


def test_empty_sample_list_is_an_error():
    with pytest.raises(ValueError):
        aggregate([])


def test_value_inside_predicted_interval_is_confirmed():
    assert judge_metric((0.80, 0.84), aggregate([0.82]), ACC).verdict is Verdict.CONFIRMED


def test_interval_boundary_counts_as_inside():
    assert judge_metric((0.80, 0.84), aggregate([0.84]), ACC).verdict is Verdict.CONFIRMED


def test_value_outside_interval_is_surprise():
    assert judge_metric((0.80, 0.84), aggregate([0.87]), ACC).verdict is Verdict.SURPRISE


def test_reversed_interval_is_accepted():
    assert judge_metric((0.84, 0.80), aggregate([0.82]), ACC).verdict is Verdict.CONFIRMED


def test_point_estimate_within_absolute_tolerance_is_confirmed():
    assert judge_metric(0.830, aggregate([0.834]), ACC).verdict is Verdict.CONFIRMED


def test_point_estimate_beyond_absolute_tolerance_is_surprise():
    assert judge_metric(0.830, aggregate([0.850]), ACC).verdict is Verdict.SURPRISE


def test_relative_tolerance_scales_with_prediction():
    # 0.31 的 10% 是 0.031
    assert judge_metric(0.31, aggregate([0.335]), LOSS).verdict is Verdict.CONFIRMED
    assert judge_metric(0.31, aggregate([0.350]), LOSS).verdict is Verdict.SURPRISE


def test_surprise_ignores_direction():
    # spec §3.5：超出阈值即 SURPRISE，无论方向
    better_than_expected = judge_metric(0.80, aggregate([0.90]), ACC)
    worse_than_expected = judge_metric(0.80, aggregate([0.70]), ACC)
    assert better_than_expected.verdict is Verdict.SURPRISE
    assert worse_than_expected.verdict is Verdict.SURPRISE


def test_noise_wider_than_tolerance_yields_noisy_not_confirmed():
    # sd≈0.0252 → 2σ≈0.050 远大于容差 0.005，判定无效
    judgement = judge_metric(0.830, aggregate([0.80, 0.83, 0.85]), ACC)
    assert judgement.verdict is Verdict.NOISY


def test_noise_wider_than_interval_yields_noisy():
    judgement = judge_metric((0.82, 0.84), aggregate([0.78, 0.83, 0.88]), ACC)
    assert judgement.verdict is Verdict.NOISY


def test_noise_within_tolerance_does_not_block_judgement():
    # sd≈0.0014 → 2σ≈0.0028 < 容差 0.005
    judgement = judge_metric(0.830, aggregate([0.830, 0.832]), ACC)
    assert judgement.verdict is Verdict.CONFIRMED


def test_single_seed_never_reports_noisy():
    assert judge_metric(0.830, aggregate([0.900]), ACC).verdict is Verdict.SURPRISE


def test_judgement_carries_deviation_for_display():
    judgement = judge_metric(0.800, aggregate([0.850]), ACC)
    assert judgement.deviation == pytest.approx(0.050)
    assert judgement.threshold == pytest.approx(0.005)
