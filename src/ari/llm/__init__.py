"""LLM 调用的唯一入口。见 spec §6、§8、§9。

整个项目里只有 llm/claude.py 与 llm/gpt.py 的 request() 会碰网络，其余
全是纯函数——这与 editor.py 只有一处碰 $EDITOR 是同一个结构。

所有失败都收敛成 LLMUnavailable：没装 SDK、没配 key、连不上、被限流、
返回的不是合法 JSON……对调用方而言这些没有区别，都是「这次没有 AI 那
一段」。spec §8 要求非 LLM 功能必须照常工作，只有把失败收敛成一种，
降级代码才写得干净。
"""

from __future__ import annotations

import json
import re


class LLMUnavailable(RuntimeError):
    """这次拿不到 AI 的判断。调用方应当降级，不应当中断。"""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
}


def parse_json_payload(text: str, schema: dict) -> dict:
    """把模型返回的文本解析成校验过的 dict。"""
    match = _FENCE_RE.match(text or "")
    if match:
        text = match.group("body")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMUnavailable(f"模型没有返回合法 JSON：{exc}") from exc

    errors = _validate(data, schema, path="")
    if errors:
        raise LLMUnavailable("模型的输出不符合约定结构：" + "；".join(errors))
    return data


def _validate(value, schema: dict, path: str) -> list[str]:
    """JSON Schema 的一个够用子集：type / properties / required /
    items / additionalProperties。我们自己写的 schema 只用到这些，
    为此引入 jsonschema 不划算——与 editor.py 拒绝为一个函数引入 click
    是同一笔账。
    """
    where = path or "顶层"
    expected = schema.get("type")
    if expected:
        if expected not in _TYPES:
            return [f"{where} 的 schema 用了不支持的 type {expected!r}"]
        # bool 是 int 的子类，别让 true 混过 number/integer 检查
        if isinstance(value, bool) != (expected == "boolean"):
            return [f"{where} 应该是 {expected}"]
        if not isinstance(value, _TYPES[expected]):
            return [f"{where} 应该是 {expected}"]

    errors: list[str] = []
    if expected == "object":
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{where} 缺少字段 {name}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{where} 多了字段 {name}")
        for name, sub in properties.items():
            if name in value:
                errors += _validate(value[name], sub, f"{path}.{name}" if path else name)

    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            errors += _validate(item, schema["items"], f"{path}[{index}]")

    return errors


def complete(ref, system: str, user: str, schema: dict) -> dict:
    """按 provider 分发，返回校验过的 dict。失败一律 LLMUnavailable。

    适配器在函数内导入：子模块要 import 本模块的 LLMUnavailable，
    在模块顶层互相导入会成环。
    """
    from . import claude, gpt

    adapters = {"anthropic": claude, "openai": gpt}
    adapter = adapters.get(ref.provider)
    if adapter is None:
        raise LLMUnavailable(f"不认识的 provider {ref.provider!r}")
    return parse_json_payload(adapter.request(ref, system, user, schema), schema)
