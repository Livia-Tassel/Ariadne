"""AI 的定性预测。见 spec §4.2。

断言的是「结构合法 + 引用的 run 真实存在」，不断言模型说了什么——
spec §9 的要求。
"""

from __future__ import annotations

import pytest

from ari.advising import ADVICE_SCHEMA, SYSTEM, build_prompt, check_advice
from ari.llm import LLMUnavailable

RUNS = ["model=base", "model=large"]
GOOD = {
    "ranking": ["model=large", "model=base"],
    "directions": [
        {"variable": "model", "effect": "容量更大通常带来更高准确率，但收益递减"}
    ],
    "confounders": ["两组的数据增强是否一致", "batch size 是否随模型一起变了"],
}


def _types_in(node):
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            yield node["type"]
        for value in node.values():
            yield from _types_in(value)
    elif isinstance(node, list):
        for item in node:
            yield from _types_in(item)


def test_schema_has_no_numeric_field():
    # 结构保证，不是 prompt 里的一句请求
    types = set(_types_in(ADVICE_SCHEMA))

    assert "number" not in types
    assert "integer" not in types


def test_schema_forbids_extra_fields():
    # 否则模型可以自己加一个 "expected_acc": 0.87 绕过上面那条
    assert ADVICE_SCHEMA["additionalProperties"] is False


def test_prompt_carries_the_hypothesis_and_every_run():
    prompt = build_prompt("large 比 base 好", {"model": ["base", "large"]}, RUNS, ["top1_acc"])

    assert "large 比 base 好" in prompt
    for run in RUNS:
        assert run in prompt
    assert "top1_acc" in prompt


def test_prompt_and_system_both_forbid_numbers():
    prompt = build_prompt("h", {"model": ["base"]}, ["model=base"], ["top1_acc"])

    # schema 之外再说一遍，双保险
    assert "数值" in prompt
    assert "数值" in SYSTEM


def test_good_advice_passes():
    assert check_advice(GOOD, RUNS) == GOOD


def test_ranking_naming_a_nonexistent_run_is_rejected():
    bad = {**GOOD, "ranking": ["model=huge", "model=base"]}

    with pytest.raises(LLMUnavailable) as exc:
        check_advice(bad, RUNS)

    assert "model=huge" in str(exc.value)


def test_ranking_missing_a_run_is_rejected():
    with pytest.raises(LLMUnavailable) as exc:
        check_advice({**GOOD, "ranking": ["model=large"]}, RUNS)

    assert "model=base" in str(exc.value)


def test_duplicate_run_in_ranking_is_rejected():
    with pytest.raises(LLMUnavailable):
        check_advice({**GOOD, "ranking": ["model=large", "model=large"]}, RUNS)


def test_empty_ranking_is_rejected():
    with pytest.raises(LLMUnavailable):
        check_advice({**GOOD, "ranking": []}, RUNS)


def test_single_run_batch_is_fine():
    advice = {**GOOD, "ranking": ["model=base"]}

    assert check_advice(advice, ["model=base"]) == advice
