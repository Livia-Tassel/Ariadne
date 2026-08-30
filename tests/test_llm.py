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


# ── 适配器：纯函数部分用 fixture 回放，request() 不在测试里被调用 ──────
#
# 两份 fixture 是照官方 SDK 的响应形状手写的，不是真实录制的。spec §9
# 要的是录制——拿到 API key 后应当用一次真实调用的输出覆盖它们。

import json
from pathlib import Path

from ari.llm import complete
from ari.llm.claude import extract_text as claude_text
from ari.llm.gpt import _status_detail as gpt_status_detail
from ari.llm.gpt import build_request as build_gpt_request
from ari.llm.gpt import extract_text as gpt_text

FIXTURES = Path(__file__).parent / "fixtures" / "llm"

ADVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {"type": "array", "items": {"type": "string"}},
        "directions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "variable": {"type": "string"},
                    "effect": {"type": "string"},
                },
                "required": ["variable", "effect"],
                "additionalProperties": False,
            },
        },
        "confounders": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ranking", "directions", "confounders"],
    "additionalProperties": False,
}


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _AnthropicResponse:
    def __init__(self, text):
        self.content = [_Block(text)]


class _OpenAIResponse:
    def __init__(self, text):
        message = type("Message", (), {"content": text})()
        self.choices = [type("Choice", (), {"message": message})()]


def test_claude_extracts_the_text_block():
    payload = (FIXTURES / "anthropic_advice.json").read_text(encoding="utf-8")

    assert claude_text(_AnthropicResponse(payload)) == payload


def test_claude_response_without_a_text_block_is_unavailable():
    empty = type("Response", (), {"content": []})()

    with pytest.raises(LLMUnavailable):
        claude_text(empty)


def test_claude_skips_leading_thinking_blocks():
    # adaptive thinking 打开时，content 的第一块可能是 thinking
    thinking = type("Block", (), {"type": "thinking", "thinking": "..."})()
    response = type("Response", (), {"content": [thinking, _Block('{"a": 1}')]})()

    assert claude_text(response) == '{"a": 1}'


def test_gpt_extracts_the_message_content():
    payload = (FIXTURES / "openai_advice.json").read_text(encoding="utf-8")

    assert gpt_text(_OpenAIResponse(payload)) == payload


def test_gpt_response_with_null_content_is_unavailable():
    with pytest.raises(LLMUnavailable):
        gpt_text(_OpenAIResponse(None))


def test_gpt_response_without_choices_is_unavailable():
    with pytest.raises(LLMUnavailable):
        gpt_text(type("Response", (), {"choices": []})())


def test_official_openai_uses_developer_and_strict_json_schema():
    from ari.config import ModelRef

    request = build_gpt_request(
        ModelRef("openai", "gpt-test", "https://api.openai.com/v1", "sk-test"),
        "system",
        "user",
        SCHEMA,
    )

    assert request["messages"][0]["role"] == "developer"
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True


def test_compatible_endpoint_uses_system_and_json_object():
    from ari.config import ModelRef

    request = build_gpt_request(
        ModelRef("openai", "deepseek-v4-pro", "https://api.deepseek.com", "sk-test"),
        "system",
        "user",
        SCHEMA,
    )

    assert request["messages"][0]["role"] == "system"
    assert "JSON Schema" in request["messages"][0]["content"]
    assert request["response_format"] == {"type": "json_object"}


def test_gpt_status_detail_handles_openai_and_compatible_error_shapes():
    compatible = type("Error", (), {"body": {"message": "unknown role developer"}})()
    official = type("Error", (), {"body": {"error": {"message": "schema invalid"}}})()

    assert gpt_status_detail(compatible) == "unknown role developer"
    assert gpt_status_detail(official) == "schema invalid"


def test_both_fixtures_survive_the_full_parse():
    for name in ("anthropic_advice.json", "openai_advice.json"):
        text = (FIXTURES / name).read_text(encoding="utf-8")

        data = parse_json_payload(text, ADVICE_SCHEMA)

        assert set(data) == {"ranking", "directions", "confounders"}
        assert data["ranking"]  # 排序不能是空的


def test_fixtures_contain_no_numeric_prediction():
    # spec §4.2：AI 不给数值。fixture 自己也必须守这条，否则测试在给
    # 一个违规的样例背书。
    for name in ("anthropic_advice.json", "openai_advice.json"):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))

        def leaves(node):
            if isinstance(node, dict):
                for value in node.values():
                    yield from leaves(value)
            elif isinstance(node, list):
                for item in node:
                    yield from leaves(item)
            else:
                yield node

        assert all(isinstance(leaf, str) for leaf in leaves(data))


def test_complete_dispatches_on_provider(monkeypatch):
    from ari.config import ModelRef
    from ari.llm import claude

    seen = {}

    def fake_request(ref, system, user, schema):
        seen["ref"] = ref
        return '{"ranking": ["a"]}'

    monkeypatch.setattr(claude, "request", fake_request)
    ref = ModelRef("anthropic", "claude-opus-5", None, "sk-test")

    assert complete(ref, "s", "u", SCHEMA) == {"ranking": ["a"]}
    assert seen["ref"] is ref


def test_complete_on_an_unknown_provider_is_unavailable():
    from ari.config import ModelRef

    with pytest.raises(LLMUnavailable):
        complete(ModelRef("grok", "x", None, "k"), "s", "u", SCHEMA)
