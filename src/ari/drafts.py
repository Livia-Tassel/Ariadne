"""YAML 草稿的公共件：数值解析与校验错误回填。

`plan` / `result` / `review` 三个命令共用同一套交互形态——生成带注释的
YAML → 编辑器 → 校验 → 写事件。校验不过时**必须**把用户已经敲进去的
内容原样送回编辑器，只在顶部加一段错误注释。丢掉用户输入是不可原谅的。
"""

from __future__ import annotations

import re

_ERROR_BEGIN = "# ┌─ 这份草稿还有问题，改完再保存 ─────────────────────────"
_ERROR_END = "# └────────────────────────────────────────────────────────"


def parse_number(value) -> float:
    """解析一个数值。接受 1e-4 / 0.0001 / .5 / 83% 这些写法。"""
    if isinstance(value, bool):
        raise ValueError(f"需要一个数值，收到 {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"需要一个数值，收到 {value!r}")

    text = value.strip()
    if not text:
        raise ValueError("值是空的")

    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()

    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{value!r} 不是一个数值") from exc

    return number / 100 if percent else number


_INTERVAL_RE = re.compile(r"^\s*(?P<low>[^~]+?)\s*~\s*(?P<high>.+?)\s*$")
_BRACKET_RE = re.compile(r"^\s*[\[(](?P<body>.+)[\])]\s*$")


def parse_prediction(value):
    """解析一条预测。返回 float（点估计）或 (low, high)（区间）。

    接受 0.83 / [0.80, 0.84] / "0.80~0.84" 三种写法。裸写的 [a, b] 会被
    YAML 解析成列表，加了引号的则是字符串——两种都要认。
    """
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f"区间需要正好两个数，收到 {len(value)} 个：{value!r}")
        low, high = (parse_number(v) for v in value)
        return (min(low, high), max(low, high))

    if isinstance(value, str):
        bracket = _BRACKET_RE.match(value)
        if bracket:
            return parse_prediction([p for p in bracket.group("body").split(",")])
        interval = _INTERVAL_RE.match(value)
        if interval:
            low = parse_number(interval.group("low"))
            high = parse_number(interval.group("high"))
            return (min(low, high), max(low, high))

    return parse_number(value)


def with_errors(text: str, errors: list[str]) -> str:
    """在草稿顶部插入错误注释块。原文一个字都不动。

    先剥掉上一轮的错误块，否则反复校验会越堆越多。
    """
    body = strip_error_header(text)
    if not errors:
        return body

    header = [_ERROR_BEGIN, "#"]
    header += [f"#   • {line}" for line in errors]
    header += ["#", _ERROR_END, ""]
    return "\n".join(header) + "\n" + body


def strip_error_header(text: str) -> str:
    """剥掉 with_errors 加的错误块。没有就原样返回。

    只认自己加的那对标记，用户自己写的 # 注释不受影响。
    """
    if not text.startswith(_ERROR_BEGIN):
        return text
    marker = _ERROR_END + "\n"
    end = text.find(marker)
    if end == -1:
        return text
    rest = text[end + len(marker) :]
    # with_errors 在结束标记后加了一个空行，这里对称地去掉
    return rest[1:] if rest.startswith("\n") else rest
