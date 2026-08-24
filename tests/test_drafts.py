import pytest

from ari.drafts import (
    parse_number,
    parse_prediction,
    strip_error_header,
    with_errors,
)


@pytest.mark.parametrize(
    "text,expected",
    [("0.83", 0.83), ("1e-4", 0.0001), (".5", 0.5), ("  0.8  ", 0.8), ("83%", 0.83)],
)
def test_parse_number_accepts_common_spellings(text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "0.8.1", None])
def test_parse_number_rejects_junk(text):
    with pytest.raises(ValueError):
        parse_number(text)


def test_parse_prediction_point_estimate():
    assert parse_prediction("0.83") == pytest.approx(0.83)


@pytest.mark.parametrize("text", ["[0.80, 0.84]", "0.80~0.84", "0.80 ~ 0.84"])
def test_parse_prediction_interval_spellings(text):
    low, high = parse_prediction(text)
    assert (low, high) == (pytest.approx(0.80), pytest.approx(0.84))


def test_parse_prediction_accepts_a_yaml_list():
    low, high = parse_prediction([0.80, 0.84])
    assert (low, high) == (pytest.approx(0.80), pytest.approx(0.84))


def test_parse_prediction_normalizes_reversed_interval():
    assert parse_prediction("0.84~0.80") == (pytest.approx(0.80), pytest.approx(0.84))


def test_parse_prediction_rejects_a_three_element_interval():
    with pytest.raises(ValueError):
        parse_prediction([0.1, 0.2, 0.3])


DRAFT = "hypothesis: 测试\nruns:\n  - run: a\n"


def test_with_errors_prepends_a_comment_block_and_keeps_the_text():
    out = with_errors(DRAFT, ["hypothesis 不能为空", "run a 缺少 rationale"])

    assert DRAFT in out
    assert "hypothesis 不能为空" in out
    assert "run a 缺少 rationale" in out
    assert out.index("hypothesis 不能为空") < out.index("hypothesis: 测试")


def test_error_header_lines_are_all_comments():
    out = with_errors(DRAFT, ["有个问题"])
    header = out[: out.index(DRAFT)]

    assert all(line.startswith("#") or not line.strip() for line in header.splitlines())


def test_errors_do_not_accumulate_across_rounds():
    once = with_errors(DRAFT, ["第一轮的问题"])
    twice = with_errors(once, ["第二轮的问题"])

    assert "第一轮的问题" not in twice
    assert "第二轮的问题" in twice
    assert DRAFT in twice


def test_strip_error_header_restores_the_original():
    assert strip_error_header(with_errors(DRAFT, ["问题"])) == DRAFT


def test_strip_is_a_noop_without_a_header():
    assert strip_error_header(DRAFT) == DRAFT


def test_user_comments_are_not_mistaken_for_the_error_header():
    draft = "# 我自己写的注释\nhypothesis: 测试\n"

    assert strip_error_header(draft) == draft
