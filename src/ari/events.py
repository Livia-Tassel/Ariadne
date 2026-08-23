"""runs.jsonl 的读写。见 spec §3.1、§8。

事件流是唯一真相来源，只追加不修改。读取时逐行独立解析：
一行损坏只跳过该行并报告位置，不影响其余数据；未知类型或更高
schema 版本的行原样保留，由上层决定如何处理，绝不重写文件。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Event:
    ts: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    batch: str | None = None
    run: str | None = None
    v: int = SCHEMA_VERSION
    line_no: int = -1


@dataclass(frozen=True)
class ParseError:
    line_no: int
    reason: str
    raw: str


def read_events(path: str | os.PathLike) -> tuple[list[Event], list[ParseError]]:
    """读取事件流。返回 (成功解析的事件, 坏行报告)。"""
    path = Path(path)
    events: list[Event] = []
    errors: list[ParseError] = []
    if not path.exists():
        return events, errors

    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(ParseError(line_no, f"JSON 格式不合法: {exc.msg}", line))
                continue
            if not isinstance(obj, dict):
                errors.append(ParseError(line_no, "顶层不是对象", line))
                continue
            missing = [f for f in ("ts", "type") if f not in obj]
            if missing:
                errors.append(ParseError(line_no, f"缺少必填字段: {', '.join(missing)}", line))
                continue
            events.append(
                Event(
                    ts=obj["ts"],
                    type=obj["type"],
                    payload=obj.get("payload") or {},
                    batch=obj.get("batch"),
                    run=obj.get("run"),
                    v=obj.get("v", SCHEMA_VERSION),
                    line_no=line_no,
                )
            )
    return events, errors


def append_event(path: str | os.PathLike, event: Event) -> None:
    """追加一个事件。字段顺序固定，便于 diff。"""
    record: dict[str, Any] = {"v": event.v, "ts": event.ts, "type": event.type}
    if event.batch is not None:
        record["batch"] = event.batch
    if event.run is not None:
        record["run"] = event.run
    record["payload"] = event.payload

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
