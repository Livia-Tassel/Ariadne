import pytest

from ari.runkey import make_run_key, normalize_value, parse_run_key


def test_keys_are_sorted_alphabetically():
    assert make_run_key({"model": "large", "lr": 0.0001}) == "lr=0.0001,model=large"


@pytest.mark.parametrize("value", ["1e-4", "1E-4", "0.0001", 0.0001, 1e-4])
def test_equivalent_numeric_spellings_collapse_to_one_key(value):
    assert make_run_key({"lr": value}) == "lr=0.0001"


def test_booleans_normalize_to_lowercase():
    assert make_run_key({"amp": True, "ema": "False"}) == "amp=true,ema=false"


def test_non_numeric_strings_pass_through_stripped():
    assert make_run_key({"model": "  resnet50  "}) == "model=resnet50"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "NaN"])
def test_nan_and_inf_stay_strings(value):
    # 模型名可能恰好叫 nan/inf；不能被 float() 吞掉变成非有限数
    assert normalize_value(value) == value


def test_special_characters_in_values_are_escaped():
    key = make_run_key({"tags": "a,b=c"})
    assert "," not in key.split("=", 1)[1]
    assert parse_run_key(key) == {"tags": "a,b=c"}


def test_round_trip():
    variables = {"lr": "1e-4", "model": "large", "amp": True}
    assert parse_run_key(make_run_key(variables)) == {
        "lr": "0.0001",
        "model": "large",
        "amp": "true",
    }


def test_empty_key_parses_to_empty_dict():
    assert parse_run_key("") == {}
