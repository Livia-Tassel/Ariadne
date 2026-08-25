"""复盘追问。见 spec §7 第 2 步。

追问的价值全在「有针对性」上：草稿里必须出现具体的偏差数字、当初写下的
理由、以及历史上类似的那几次。
"""

from __future__ import annotations

import pytest

from ari.llm import LLMUnavailable
from ari.probing import PROBE_SCHEMA, SYSTEM, build_prompt, check_probe
from ari.recall import Recalled

HISTORY = [
    Recalled(
        batch="b2",
        run="lr=0.001,model=base",
        cause="数据增强忘了关",
        next_step="关掉重跑",
        rationale="调低 lr 应该会涨",
        metrics=("top1_acc",),
        score=5,
    )
]


def test_schema_only_asks_for_questions_and_hypotheses():
    assert set(PROBE_SCHEMA["properties"]) == {"questions", "hypotheses"}
    assert PROBE_SCHEMA["additionalProperties"] is False


def test_prompt_carries_the_deviation_the_rationale_and_the_history():
    prompt = build_prompt(
        batch="b3",
        run="lr=0.0001,model=large",
        hypothesis="调低 lr 对大模型有帮助",
        deviations=["top1_acc：预测 0.83 → 实测 0.95（偏差 +0.12）"],
        rationale="容量更大，lr 调低应该更稳",
        history=HISTORY,
    )

    assert "lr=0.0001,model=large" in prompt
    assert "+0.12" in prompt  # 具体的偏差数字
    assert "容量更大" in prompt  # 当初写下的理由
    assert "数据增强忘了关" in prompt  # 历史上那次的结论
    assert "b2" in prompt


def test_prompt_without_history_says_so_rather_than_leaving_a_hole():
    prompt = build_prompt(
        batch="b1", run="model=large", hypothesis="h",
        deviations=["top1_acc 偏了"], rationale="理由", history=[],
    )

    assert "没有" in prompt  # 明确告诉模型这是第一次，不要编造历史


def test_system_forbids_generic_questions():
    assert "具体" in SYSTEM


def test_good_probe_passes():
    probe = {"questions": ["增强关了吗？"], "hypotheses": ["和 b2 是同一个原因"]}

    assert check_probe(probe) == probe


def test_empty_questions_is_rejected():
    # 一个问题都提不出来，不如不显示这一段
    with pytest.raises(LLMUnavailable):
        check_probe({"questions": [], "hypotheses": ["也许吧"]})


def test_blank_questions_are_dropped():
    probe = check_probe({"questions": ["真问题", "   ", ""], "hypotheses": []})

    assert probe["questions"] == ["真问题"]


def test_all_blank_questions_is_rejected():
    with pytest.raises(LLMUnavailable):
        check_probe({"questions": ["  ", ""], "hypotheses": []})
