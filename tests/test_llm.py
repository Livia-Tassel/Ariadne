"""LLM 统一入口的纯逻辑。见 spec §8、§9。

这个文件里没有一行会碰网络。适配器的 request 是唯一碰 SDK 的地方，
测试不调它；能测的部分——分发、异常收敛、响应校验——全是纯函数。
"""

from __future__ import annotations

import pytest

from ari.llm import LLMUnavailable, parse_json_payload

SCHEMA = {
    "type": "object",
    "properties": {"ranking": {"type": "array", "items": {"type": "string"}}},
    "required": ["ranking"],
    "additionalProperties": False,
}


def test_parses_a_well_formed_payload():
    assert parse_json_payload('{"ranking": ["a", "b"]}', SCHEMA) == {"ranking": ["a", "b"]}


def test_payload_wrapped_in_a_code_fence_still_parses():
    # 结构化输出理论上不会带围栏，但模型偶尔会——为这一种情况崩掉不值得
    text = '```json\n{"ranking": ["a"]}\n```'

    assert parse_json_payload(text, SCHEMA) == {"ranking": ["a"]}


def test_non_json_is_unavailable_not_a_crash():
    with pytest.raises(LLMUnavailable):
        parse_json_payload("模型今天不想输出 JSON", SCHEMA)


def test_missing_required_field_is_rejected():
    with pytest.raises(LLMUnavailable) as exc:
        parse_json_payload('{"other": 1}', SCHEMA)

    assert "ranking" in str(exc.value)


def test_wrong_type_is_rejected():
    with pytest.raises(LLMUnavailable):
        parse_json_payload('{"ranking": "不是数组"}', SCHEMA)


def test_extra_field_is_rejected_when_schema_forbids_it():
    with pytest.raises(LLMUnavailable):
        parse_json_payload('{"ranking": [], "extra": 1}', SCHEMA)


def test_top_level_non_object_is_rejected():
    with pytest.raises(LLMUnavailable):
        parse_json_payload('["a"]', SCHEMA)


def test_boolean_does_not_pass_as_a_string():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }

    with pytest.raises(LLMUnavailable):
        parse_json_payload('{"name": true}', schema)


def test_nested_object_errors_name_the_path():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"variable": {"type": "string"}},
                    "required": ["variable"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    with pytest.raises(LLMUnavailable) as exc:
        parse_json_payload('{"items": [{"wrong": "x"}]}', schema)

    assert "items[0]" in str(exc.value)


def test_an_unknown_type_keyword_is_reported_not_a_keyerror():
    with pytest.raises(LLMUnavailable):
        parse_json_payload('{"x": 1}', {"type": "object", "properties": {"x": {"type": "date"}}})
