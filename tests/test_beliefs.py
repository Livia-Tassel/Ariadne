"""信念账本。见 spec §3.2、§7.1。"""

from __future__ import annotations

import pytest

from ari.beliefs import make_belief_id, normalize_text


def test_same_text_gets_the_same_id():
    assert make_belief_id("lr 调低对大模型没用") == make_belief_id("lr 调低对大模型没用")


def test_id_looks_like_bel_plus_four_hex():
    belief_id = make_belief_id("lr 调低对大模型没用")

    assert belief_id.startswith("bel-")
    assert len(belief_id) == len("bel-") + 4
    int(belief_id.removeprefix("bel-"), 16)  # 是合法的十六进制


def test_different_text_gets_a_different_id():
    assert make_belief_id("A 比 B 好") != make_belief_id("B 比 A 好")


def test_reformatting_does_not_mint_a_new_id():
    # 换行位置变了、缩进变了，还是同一句话
    assert make_belief_id("lr 调低\n对大模型没用") == make_belief_id("lr 调低 对大模型没用")


def test_collision_with_different_text_extends_the_id():
    text = "lr 调低对大模型没用"
    short = make_belief_id(text)
    # 假装这个 ID 已经被另一条内容占了
    extended = make_belief_id(text, {short: "完全不同的另一条信念"})

    assert extended != short
    assert extended.startswith(short)


def test_collision_with_the_same_text_reuses_the_id():
    text = "lr 调低对大模型没用"
    short = make_belief_id(text)

    assert make_belief_id(text, {short: text}) == short


def test_empty_text_is_rejected():
    with pytest.raises(ValueError):
        make_belief_id("   \n  ")


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  a\n\n  b  ") == "a b"
