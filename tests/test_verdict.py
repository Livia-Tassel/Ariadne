import pytest

from ari.verdict import aggregate


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
