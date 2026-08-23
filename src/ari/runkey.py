"""Run key 的规范化、构造与反解。见 spec §3.3。

Run 由变量组合定义。同一组合的不同书写方式（1e-4 / 0.0001 / 1E-4）
必须映射到同一个 key，否则预测与结果无法对齐。
"""

from __future__ import annotations

import math
from urllib.parse import quote, unquote

# safe="" 让 quote 转义包括 , 和 = 在内的所有非字母数字字符，
# 保证 key 的分隔符不会与值内容冲突。
_SAFE = ""


def normalize_value(value: object) -> str:
    """把一个变量值规范化为字符串。

    数值统一为 .12g；布尔统一为 true/false；其余按 strip 后的字符串处理。
    nan / inf 虽然能被 float() 解析，但作为变量值几乎一定是字符串
    （例如模型名），因此原样保留。
    """
    # bool 是 int 的子类，必须先判
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return str(value)
        return format(number, ".12g")

    text = str(value).strip()
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered

    try:
        number = float(text)
    except ValueError:
        return text
    if math.isnan(number) or math.isinf(number):
        return text
    return format(number, ".12g")


def make_run_key(variables: dict) -> str:
    """由变量字典构造规范化的 run key。"""
    parts = [
        f"{quote(str(name).strip(), safe=_SAFE)}="
        f"{quote(normalize_value(variables[name]), safe=_SAFE)}"
        for name in sorted(variables)
    ]
    return ",".join(parts)


def parse_run_key(key: str) -> dict[str, str]:
    """把 run key 反解回变量字典。值保持规范化后的字符串形式。"""
    if not key:
        return {}
    variables = {}
    for part in key.split(","):
        name, _, value = part.partition("=")
        variables[unquote(name)] = unquote(value)
    return variables
