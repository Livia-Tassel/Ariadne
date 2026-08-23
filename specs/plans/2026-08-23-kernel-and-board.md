# 判定内核与看板 实现计划（v1 第一阶段）

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 每个任务严格遵循 @superpowers:test-driven-development：先写失败的测试，跑一遍确认它失败，再写最小实现。

**Goal:** 实现 `runs.jsonl` 事件流到 run/batch 判定结果的完整内核，并通过 `ari init` 与 `ari board` 端到端可验证。

**Architecture:** 纯函数内核 + 薄 IO 层。`runkey` / `metrics` / `verdict` 是无副作用的纯函数模块，`events` 负责 jsonl 的容错读写，`project` 把事件流折叠成状态，`board` 渲染，`cli` 只做参数解析和文件读写。所有判定逻辑不碰文件系统，因此可以用纯数据做严格断言——这正是 spec §9 要求覆盖率最高的部分。

**Tech Stack:** Python ≥3.11、uv、typer（CLI）、rich（终端渲染）、PyYAML（后续任务用）、pytest。

**Spec:** `specs/2026-08-23-experiment-loop-design.md`（本计划实现其中的 §2、§3、§8、§9，以及 §4 的 `init` 与 `board`）

**本计划不含：** `ari plan`、`ari result`、`ari review`、LLM 层、信念账本。见文末「后续计划」。

---

## 交付定义

完成后应当能做到：手写（或用 fixture 脚本生成）一份 `runs.jsonl`，运行 `ari board`，看到正确的 run 级 / batch 级判定、未复盘 SURPRISE 置顶、噪声提示、损坏行报告，并生成 `board.md`。

## 文件结构

```
pyproject.toml
src/ari/
  __init__.py
  runkey.py      run key 的规范化、构造与反解（spec §3.3）
  events.py      Event 数据类、jsonl 容错读取、追加写（spec §3.1、§8）
  metrics.py     MetricSpec 与按指标名的默认规格表（spec §3.5）
  verdict.py     seed 聚合、单指标判定、run 聚合、排序判定（spec §3.8、§3.9）
  project.py     事件流 → BatchState / RunState 投影（spec §3.2、§3.7、§3.10）
  board.py       BatchState → markdown 渲染（spec §4）
  cli.py         typer 入口：init / board
tests/
  test_runkey.py
  test_events.py
  test_metrics.py
  test_verdict.py
  test_project.py
  test_board.py
  test_e2e.py
  fixtures/
```

拆分原则：按 spec 的章节边界拆，一个模块对应一个能独立讲清楚的概念。`verdict.py` 会是最大的一个（约 150 行），但四个判定函数共享 `Verdict` 枚举与噪声守门逻辑，拆开反而要来回跳。

---

## Task 1: 项目骨架与工具链

**Files:**
- Create: `pyproject.toml`
- Create: `src/ari/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.gitignore`

- [ ] **Step 1: 创建 `pyproject.toml`**

```toml
[project]
name = "ariadne-ra"
version = "0.1.0"
description = "实验预测、记录与复盘闭环"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "rich>=13.7",
    "PyYAML>=6.0",
]

[project.scripts]
ari = "ari.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ari"]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: 创建 `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
dist/
.DS_Store
```

- [ ] **Step 3: 创建 `src/ari/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: 写冒烟测试 `tests/test_smoke.py`**

```python
def test_package_imports():
    import ari

    assert ari.__version__ == "0.1.0"
```

- [ ] **Step 5: 安装依赖并跑测试**

Run: `uv sync && uv run pytest -v`
Expected: 1 passed

- [ ] **Step 6: 提交（含此前的 spec 与本计划）**

```bash
git add .gitignore pyproject.toml uv.lock src tests specs
git commit -m "$(cat <<'EOF'
chore: 项目骨架与 v1 设计文档

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: run key 规范化

对应 spec §3.3。这是整个系统的地基——规范化一旦有洞，`1e-4` 与 `0.0001` 会分裂成两个 run，预测和结果永远对不上，且错误会静默地污染全部历史数据。

**Files:**
- Create: `src/ari/runkey.py`
- Test: `tests/test_runkey.py`

- [ ] **Step 1: 写失败的测试**

```python
import pytest

from ari.runkey import make_run_key, normalize_value, parse_run_key


def test_keys_are_sorted_alphabetically():
    assert make_run_key({"model": "large", "lr": 0.0001}) == "lr=0.0001,model=large"


@pytest.mark.parametrize("value", ["1e-4", "1E-4", "0.0001", 0.0001, 1e-4])
def test_equivalent_numeric_spellings_collapse_to_one_key(value):
    assert make_run_key({"lr": value}) == "lr=0.0001"


def test_booleans_normalize_to_lowercase():
    assert make_run_key({"amp": True, "ema": "False"}) == "amp=true,ema=false"


def test_non_numeric_strings_pass_through_stripped():
    assert make_run_key({"model": "  resnet50  "}) == "model=resnet50"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "NaN"])
def test_nan_and_inf_stay_strings(value):
    # 模型名可能恰好叫 nan/inf；不能被 float() 吞掉变成非有限数
    assert normalize_value(value) == value


def test_special_characters_in_values_are_escaped():
    key = make_run_key({"tags": "a,b=c"})
    assert "," not in key.split("=", 1)[1]
    assert parse_run_key(key) == {"tags": "a,b=c"}


def test_round_trip():
    variables = {"lr": "1e-4", "model": "large", "amp": True}
    assert parse_run_key(make_run_key(variables)) == {
        "lr": "0.0001",
        "model": "large",
        "amp": "true",
    }


def test_empty_key_parses_to_empty_dict():
    assert parse_run_key("") == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_runkey.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.runkey'`

- [ ] **Step 3: 实现 `src/ari/runkey.py`**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_runkey.py -v`
Expected: 全部 PASS（含 parametrize 展开共 15 个）

- [ ] **Step 5: 提交**

```bash
git add src/ari/runkey.py tests/test_runkey.py
git commit -m "$(cat <<'EOF'
feat: run key 规范化

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 事件读写与容错解析

对应 spec §3.1、§8。核心要求：**一行损坏不能让整个项目不可用**，且未知类型 / 更高版本的行必须保留不丢。

**Files:**
- Create: `src/ari/events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: 写失败的测试**

```python
from ari.events import SCHEMA_VERSION, Event, append_event, read_events


def test_append_then_read_round_trip(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_event(path, Event(ts="2026-08-23T14:02:11+08:00", type="batch_opened",
                             batch="b3", payload={"hypothesis": "大模型更好"}))
    append_event(path, Event(ts="2026-08-23T14:05:00+08:00", type="prediction",
                             batch="b3", run="lr=0.0001", payload={"metrics": {"acc": 0.8}}))

    events, errors = read_events(path)

    assert errors == []
    assert [e.type for e in events] == ["batch_opened", "prediction"]
    assert events[1].run == "lr=0.0001"
    assert events[1].payload["metrics"]["acc"] == 0.8
    assert events[0].v == SCHEMA_VERSION
    assert [e.line_no for e in events] == [1, 2]


def test_corrupt_line_is_skipped_and_reported(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        '{"v":1,"ts":"t1","type":"note","payload":{}}\n'
        "{ this is not json\n"
        '{"v":1,"ts":"t3","type":"note","payload":{}}\n',
        encoding="utf-8",
    )

    events, errors = read_events(path)

    assert [e.ts for e in events] == ["t1", "t3"]
    assert len(errors) == 1
    assert errors[0].line_no == 2


def test_line_missing_required_field_is_reported(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"v":1,"type":"note","payload":{}}\n', encoding="utf-8")

    events, errors = read_events(path)

    assert events == []
    assert len(errors) == 1
    assert "ts" in errors[0].reason


def test_blank_lines_are_ignored_without_error(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('\n{"v":1,"ts":"t1","type":"note","payload":{}}\n\n', encoding="utf-8")

    events, errors = read_events(path)

    assert len(events) == 1
    assert errors == []


def test_higher_schema_version_is_preserved_not_dropped(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"v":99,"ts":"t1","type":"future_type","payload":{}}\n', encoding="utf-8")

    events, errors = read_events(path)

    assert errors == []
    assert events[0].v == 99
    assert events[0].type == "future_type"


def test_missing_file_reads_as_empty(tmp_path):
    events, errors = read_events(tmp_path / "nope.jsonl")

    assert events == []
    assert errors == []


def test_unicode_is_written_unescaped(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_event(path, Event(ts="t1", type="note", payload={"text": "过拟合"}))

    assert "过拟合" in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.events'`

- [ ] **Step 3: 实现 `src/ari/events.py`**

```python
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
                errors.append(ParseError(line_no, f"JSON 解析失败: {exc.msg}", line))
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_events.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/events.py tests/test_events.py
git commit -m "$(cat <<'EOF'
feat: 事件流读写与逐行容错解析

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 指标规格与默认表

对应 spec §3.5。要点：未声明且无法匹配默认规则的指标必须**报错**，不能猜——spec §8「指标名不存在时明确报告缺失，不静默填空」的同一条原则。

**Files:**
- Create: `src/ari/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: 写失败的测试**

```python
import pytest

from ari.metrics import MetricSpec, UnknownMetricError, spec_for


def test_declared_spec_wins_over_default():
    spec = spec_for("top1_acc", {"top1_acc": {"direction": "higher_better",
                                              "compare": "relative", "tolerance": 0.2}})
    assert spec == MetricSpec("higher_better", "relative", 0.2)


@pytest.mark.parametrize(
    "name,direction,compare",
    [
        ("top1_acc", "higher_better", "absolute"),
        ("val_accuracy", "higher_better", "absolute"),
        ("macro_f1", "higher_better", "absolute"),
        ("train_loss", "lower_better", "relative"),
        ("ppl", "lower_better", "relative"),
        ("test_perplexity", "lower_better", "relative"),
        ("word_err_rate", "lower_better", "absolute"),
    ],
)
def test_defaults_by_name_pattern(name, direction, compare):
    spec = spec_for(name, {})
    assert spec.direction == direction
    assert spec.compare == compare


def test_unmatched_metric_raises_instead_of_guessing():
    with pytest.raises(UnknownMetricError) as exc:
        spec_for("gpu_hours", {})
    assert "gpu_hours" in str(exc.value)


def test_partial_declaration_fills_remaining_fields_from_dataclass_defaults():
    spec = spec_for("gpu_hours", {"gpu_hours": {"direction": "lower_better"}})
    assert spec.direction == "lower_better"
    assert spec.compare == "relative"
    assert spec.tolerance == 0.10


def test_invalid_direction_is_rejected():
    with pytest.raises(ValueError):
        spec_for("acc", {"acc": {"direction": "bigger"}})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.metrics'`

- [ ] **Step 3: 实现 `src/ari/metrics.py`**

```python
"""指标规格。见 spec §3.5。

比较方式必须逐个指标声明：acc 从 0.80 到 0.84 只有 5% 相对偏差却可能
是重大提升，loss 从 0.31 到 0.34 是 10% 却可能无所谓。统一阈值在科研
语境下不成立。

默认表只覆盖高置信度的命名习惯；匹配不上就报错要求显式声明，不猜。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

DIRECTIONS = ("higher_better", "lower_better")
COMPARES = ("absolute", "relative")


class UnknownMetricError(ValueError):
    """指标既未声明规格，也匹配不上任何默认规则。"""


@dataclass(frozen=True)
class MetricSpec:
    direction: str = "higher_better"
    compare: str = "relative"
    tolerance: float = 0.10

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction 必须是 {DIRECTIONS} 之一，收到 {self.direction!r}")
        if self.compare not in COMPARES:
            raise ValueError(f"compare 必须是 {COMPARES} 之一，收到 {self.compare!r}")
        if self.tolerance < 0:
            raise ValueError(f"tolerance 不能为负，收到 {self.tolerance!r}")


# 顺序敏感：先匹配先生效。
_DEFAULT_PATTERNS: list[tuple[str, MetricSpec]] = [
    ("*acc*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*f1*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*auc*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*bleu*", MetricSpec("higher_better", "absolute", 0.005)),
    ("*err*", MetricSpec("lower_better", "absolute", 0.005)),
    ("*loss*", MetricSpec("lower_better", "relative", 0.10)),
    ("*perplexity*", MetricSpec("lower_better", "relative", 0.10)),
    ("*ppl*", MetricSpec("lower_better", "relative", 0.10)),
]


def default_spec(name: str) -> MetricSpec | None:
    lowered = name.lower()
    for pattern, spec in _DEFAULT_PATTERNS:
        if fnmatch.fnmatch(lowered, pattern):
            return spec
    return None


def spec_for(name: str, declared: dict) -> MetricSpec:
    """取某指标的规格：显式声明优先，其次默认表，都没有则报错。"""
    if name in declared:
        value = declared[name]
        return value if isinstance(value, MetricSpec) else MetricSpec(**value)
    spec = default_spec(name)
    if spec is None:
        raise UnknownMetricError(
            f"指标 {name!r} 没有默认规格，请在 batch_opened 的 metric_specs 中"
            f"声明 direction / compare / tolerance"
        )
    return spec
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: 全部 PASS（含 parametrize 展开共 11 个）

- [ ] **Step 5: 提交**

```bash
git add src/ari/metrics.py tests/test_metrics.py
git commit -m "$(cat <<'EOF'
feat: per-metric 指标规格与默认表

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: seed 聚合

对应 spec §3.4。seed 不进 run key，同一 run 的多次结果聚合为均值与样本标准差，`sd` 就是后续噪声守门的依据。

**Files:**
- Create: `src/ari/verdict.py`
- Test: `tests/test_verdict.py`

- [ ] **Step 1: 写失败的测试**

```python
import pytest

from ari.verdict import aggregate


def test_single_sample_has_no_standard_deviation():
    agg = aggregate([0.83])

    assert agg.mean == pytest.approx(0.83)
    assert agg.sd is None
    assert agg.n == 1


def test_multiple_samples_give_mean_and_sample_sd():
    agg = aggregate([0.80, 0.82, 0.84])

    assert agg.mean == pytest.approx(0.82)
    assert agg.sd == pytest.approx(0.02)
    assert agg.n == 3


def test_identical_samples_have_zero_sd():
    assert aggregate([0.5, 0.5, 0.5]).sd == pytest.approx(0.0)


def test_empty_sample_list_is_an_error():
    with pytest.raises(ValueError):
        aggregate([])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.verdict'`

- [ ] **Step 3: 实现 `src/ari/verdict.py` 的第一部分**

```python
"""判定引擎。见 spec §3.8、§3.9。

判定的对象是「该配置的期望表现」，不是某一次抽签结果，因此多 seed 先
聚合成均值与标准差，再与预测比对。标准差同时充当噪声基线：噪声大于
判定分辨率时不给结论，报 NOISY。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    NO_RESULT = "NO_RESULT"
    UNVERIFIED = "UNVERIFIED"
    CONFIRMED = "CONFIRMED"
    SURPRISE = "SURPRISE"
    NOISY = "NOISY"


@dataclass(frozen=True)
class Aggregate:
    mean: float
    sd: float | None
    n: int


def aggregate(values) -> Aggregate:
    """把同一 run 多个 seed 的结果聚合。sd 为样本标准差，单样本时为 None。"""
    numbers = [float(v) for v in values]
    if not numbers:
        raise ValueError("聚合需要至少一个结果值")
    return Aggregate(
        mean=statistics.fmean(numbers),
        sd=statistics.stdev(numbers) if len(numbers) >= 2 else None,
        n=len(numbers),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/verdict.py tests/test_verdict.py
git commit -m "$(cat <<'EOF'
feat: seed 结果聚合

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 单指标判定与噪声守门

对应 spec §3.8。这是整个工具最核心的一段逻辑，也是最容易出微妙错误的地方——务必逐条对照 spec 的判定表。

**Files:**
- Modify: `src/ari/verdict.py`
- Test: `tests/test_verdict.py`

- [ ] **Step 1: 追加失败的测试**

```python
from ari.metrics import MetricSpec
from ari.verdict import Verdict, judge_metric

ACC = MetricSpec("higher_better", "absolute", 0.005)
LOSS = MetricSpec("lower_better", "relative", 0.10)


def test_value_inside_predicted_interval_is_confirmed():
    assert judge_metric((0.80, 0.84), aggregate([0.82]), ACC).verdict is Verdict.CONFIRMED


def test_interval_boundary_counts_as_inside():
    assert judge_metric((0.80, 0.84), aggregate([0.84]), ACC).verdict is Verdict.CONFIRMED


def test_value_outside_interval_is_surprise():
    assert judge_metric((0.80, 0.84), aggregate([0.87]), ACC).verdict is Verdict.SURPRISE


def test_reversed_interval_is_accepted():
    assert judge_metric((0.84, 0.80), aggregate([0.82]), ACC).verdict is Verdict.CONFIRMED


def test_point_estimate_within_absolute_tolerance_is_confirmed():
    assert judge_metric(0.830, aggregate([0.834]), ACC).verdict is Verdict.CONFIRMED


def test_point_estimate_beyond_absolute_tolerance_is_surprise():
    assert judge_metric(0.830, aggregate([0.850]), ACC).verdict is Verdict.SURPRISE


def test_relative_tolerance_scales_with_prediction():
    # 0.31 的 10% 是 0.031
    assert judge_metric(0.31, aggregate([0.335]), LOSS).verdict is Verdict.CONFIRMED
    assert judge_metric(0.31, aggregate([0.350]), LOSS).verdict is Verdict.SURPRISE


def test_surprise_ignores_direction():
    # spec §3.5：超出阈值即 SURPRISE，无论方向
    better_than_expected = judge_metric(0.80, aggregate([0.90]), ACC)
    worse_than_expected = judge_metric(0.80, aggregate([0.70]), ACC)
    assert better_than_expected.verdict is Verdict.SURPRISE
    assert worse_than_expected.verdict is Verdict.SURPRISE


def test_noise_wider_than_tolerance_yields_noisy_not_confirmed():
    # sd≈0.0265 → 2σ≈0.053 远大于容差 0.005，判定无效
    judgement = judge_metric(0.830, aggregate([0.80, 0.83, 0.85]), ACC)
    assert judgement.verdict is Verdict.NOISY


def test_noise_wider_than_interval_yields_noisy():
    judgement = judge_metric((0.82, 0.84), aggregate([0.78, 0.83, 0.88]), ACC)
    assert judgement.verdict is Verdict.NOISY


def test_noise_within_tolerance_does_not_block_judgement():
    # sd=0.001 → 2σ=0.002 < 容差 0.005
    judgement = judge_metric(0.830, aggregate([0.830, 0.832]), ACC)
    assert judgement.verdict is Verdict.CONFIRMED


def test_single_seed_never_reports_noisy():
    assert judge_metric(0.830, aggregate([0.900]), ACC).verdict is Verdict.SURPRISE


def test_judgement_carries_deviation_for_display():
    judgement = judge_metric(0.800, aggregate([0.850]), ACC)
    assert judgement.deviation == pytest.approx(0.050)
    assert judgement.threshold == pytest.approx(0.005)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'judge_metric'`

- [ ] **Step 3: 在 `src/ari/verdict.py` 追加实现**

```python
@dataclass(frozen=True)
class MetricJudgement:
    verdict: Verdict
    deviation: float | None  # 实测均值 - 预测点估计；区间预测时为 None
    threshold: float | None  # 点估计的容差
    resolution: float  # 判定分辨率：区间宽度或容差
    note: str = ""


def _noise_blocks(agg: Aggregate, resolution: float) -> str | None:
    """噪声守门：2σ 超过判定分辨率时，这个实验设计分辨不出要问的差异。"""
    if agg.sd is None:
        return None
    noise = 2 * agg.sd
    if noise > resolution:
        return f"2σ={noise:.4g} 超过判定分辨率 {resolution:.4g}，需要更多 seed 或更大的变量跨度"
    return None


def judge_metric(prediction, agg: Aggregate, spec) -> MetricJudgement:
    """判定单个指标。区间预测看是否落入，点估计看偏差是否在容差内。

    噪声守门先于判定：守门通过即保证 2σ ≤ resolution，因此阈值就是
    容差本身，无需再取 max。
    """
    if isinstance(prediction, (list, tuple)):
        low, high = sorted((float(prediction[0]), float(prediction[1])))
        resolution = high - low
        blocked = _noise_blocks(agg, resolution)
        if blocked:
            return MetricJudgement(Verdict.NOISY, None, None, resolution, blocked)
        verdict = Verdict.CONFIRMED if low <= agg.mean <= high else Verdict.SURPRISE
        return MetricJudgement(verdict, None, None, resolution)

    point = float(prediction)
    tolerance = (
        spec.tolerance if spec.compare == "absolute" else spec.tolerance * abs(point)
    )
    blocked = _noise_blocks(agg, tolerance)
    if blocked:
        return MetricJudgement(Verdict.NOISY, agg.mean - point, tolerance, tolerance, blocked)
    verdict = (
        Verdict.CONFIRMED if abs(agg.mean - point) <= tolerance else Verdict.SURPRISE
    )
    return MetricJudgement(verdict, agg.mean - point, tolerance, tolerance)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: 全部 PASS（累计 18 个）

- [ ] **Step 5: 提交**

```bash
git add src/ari/verdict.py tests/test_verdict.py
git commit -m "$(cat <<'EOF'
feat: 单指标判定与噪声守门

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: run 级聚合

对应 spec §3.8 的优先级表：`SURPRISE` > `NOISY` > `UNVERIFIED` > `NO_RESULT` > `CONFIRMED`。

**Files:**
- Modify: `src/ari/verdict.py`
- Test: `tests/test_verdict.py`

- [ ] **Step 1: 追加失败的测试**

```python
from ari.verdict import judge_run, worst


def test_worst_of_picks_surprise_over_everything():
    assert worst({Verdict.CONFIRMED, Verdict.NOISY, Verdict.SURPRISE}) is Verdict.SURPRISE


def test_worst_of_prefers_noisy_over_no_result():
    assert worst({Verdict.CONFIRMED, Verdict.NO_RESULT, Verdict.NOISY}) is Verdict.NOISY


def test_all_confirmed_gives_confirmed():
    assert worst({Verdict.CONFIRMED}) is Verdict.CONFIRMED


def test_empty_set_is_confirmed():
    assert worst(set()) is Verdict.CONFIRMED


def test_run_is_surprise_if_any_metric_is():
    verdict, per_metric = judge_run(
        prediction_metrics={"top1_acc": 0.830, "train_loss": 0.31},
        results={"top1_acc": aggregate([0.831]), "train_loss": aggregate([0.60])},
        specs={"top1_acc": ACC, "train_loss": LOSS},
    )

    assert verdict is Verdict.SURPRISE
    assert per_metric["top1_acc"].verdict is Verdict.CONFIRMED
    assert per_metric["train_loss"].verdict is Verdict.SURPRISE


def test_metric_without_result_is_no_result_and_blocks_confirmed():
    verdict, per_metric = judge_run(
        prediction_metrics={"top1_acc": 0.830, "train_loss": 0.31},
        results={"top1_acc": aggregate([0.831])},
        specs={"top1_acc": ACC, "train_loss": LOSS},
    )

    assert verdict is Verdict.NO_RESULT
    assert per_metric["train_loss"].verdict is Verdict.NO_RESULT


def test_run_without_any_prediction_is_no_result():
    verdict, per_metric = judge_run({}, {}, {})

    assert verdict is Verdict.NO_RESULT
    assert per_metric == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'judge_run'`

- [ ] **Step 3: 在 `src/ari/verdict.py` 追加实现**

```python
# 从最坏到最好。run 级取最坏：只有全部指标 CONFIRMED，run 才 CONFIRMED。
_WORST_FIRST = (
    Verdict.SURPRISE,
    Verdict.NOISY,
    Verdict.UNVERIFIED,
    Verdict.NO_RESULT,
    Verdict.CONFIRMED,
)


def worst(verdicts) -> Verdict:
    for candidate in _WORST_FIRST:
        if candidate in verdicts:
            return candidate
    return Verdict.CONFIRMED


def judge_run(
    prediction_metrics: dict,
    results: dict[str, Aggregate],
    specs: dict,
) -> tuple[Verdict, dict[str, MetricJudgement]]:
    """判定一个 run 的所有指标并取最坏。

    返回 (run 级 verdict, 每个指标的判定明细)。明细必须保留——review 时
    要点名是哪个指标偏了多少，而不是笼统地说这个 run 不符预期。
    """
    if not prediction_metrics:
        return Verdict.NO_RESULT, {}

    per_metric: dict[str, MetricJudgement] = {}
    for name, prediction in prediction_metrics.items():
        agg = results.get(name)
        if agg is None:
            per_metric[name] = MetricJudgement(Verdict.NO_RESULT, None, None, 0.0, "尚无结果")
        else:
            per_metric[name] = judge_metric(prediction, agg, specs[name])

    return worst({j.verdict for j in per_metric.values()}), per_metric
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: 全部 PASS（累计 25 个）

- [ ] **Step 5: 提交**

```bash
git add src/ari/verdict.py tests/test_verdict.py
git commit -m "$(cat <<'EOF'
feat: run 级判定聚合

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: batch 级排序判定

对应 spec §3.9。全部 run 都 CONFIRMED 但排序翻了，是非常有价值的信号，不能被 run 级的全绿淹没。

**Files:**
- Modify: `src/ari/verdict.py`
- Test: `tests/test_verdict.py`

- [ ] **Step 1: 追加失败的测试**

```python
from ari.verdict import judge_ranking


def test_ranking_matching_expectation_is_confirmed():
    judgement = judge_ranking(
        expected_order=["model=large", "model=base"],
        aggregates={"model=large": aggregate([0.85]), "model=base": aggregate([0.80])},
        spec=ACC,
    )

    assert judgement.verdict is Verdict.CONFIRMED
    assert judgement.real_flips == []


def test_clear_flip_is_surprise_and_names_the_pair():
    judgement = judge_ranking(
        expected_order=["model=large", "model=base"],
        aggregates={"model=large": aggregate([0.75]), "model=base": aggregate([0.85])},
        spec=ACC,
    )

    assert judgement.verdict is Verdict.SURPRISE
    assert judgement.real_flips == [("model=large", "model=base")]


def test_lower_better_metric_inverts_the_comparison():
    judgement = judge_ranking(
        expected_order=["model=large", "model=base"],
        aggregates={"model=large": aggregate([0.20]), "model=base": aggregate([0.50])},
        spec=LOSS,
    )

    assert judgement.verdict is Verdict.CONFIRMED


def test_flip_inside_noise_is_noisy_not_surprise():
    judgement = judge_ranking(
        expected_order=["model=large", "model=base"],
        aggregates={
            "model=large": aggregate([0.820, 0.830, 0.840]),  # mean 0.830, 2σ≈0.020
            "model=base": aggregate([0.835]),
        },
        spec=ACC,
    )

    assert judgement.verdict is Verdict.NOISY
    assert judgement.noisy_flips == [("model=large", "model=base")]


def test_tie_counts_as_noisy_flip():
    judgement = judge_ranking(
        expected_order=["a", "b"],
        aggregates={"a": aggregate([0.80]), "b": aggregate([0.80])},
        spec=ACC,
    )

    assert judgement.verdict is Verdict.NOISY


def test_real_flip_outranks_noisy_flip():
    judgement = judge_ranking(
        expected_order=["a", "b", "c"],
        aggregates={"a": aggregate([0.80]), "b": aggregate([0.80]), "c": aggregate([0.95])},
        spec=ACC,
    )

    assert judgement.verdict is Verdict.SURPRISE
    assert ("a", "c") in judgement.real_flips
    assert ("a", "b") in judgement.noisy_flips


def test_missing_runs_are_dropped_and_too_few_gives_no_result():
    judgement = judge_ranking(
        expected_order=["a", "b"],
        aggregates={"a": aggregate([0.80])},
        spec=ACC,
    )

    assert judgement.verdict is Verdict.NO_RESULT
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'judge_ranking'`

- [ ] **Step 3: 在 `src/ari/verdict.py` 追加实现**

```python
@dataclass(frozen=True)
class RankingJudgement:
    verdict: Verdict
    real_flips: list[tuple[str, str]]
    noisy_flips: list[tuple[str, str]]


def judge_ranking(
    expected_order: list[str],
    aggregates: dict[str, Aggregate],
    spec,
) -> RankingJudgement:
    """判定 batch 级的相对排序预测。

    遍历 expected_order 中所有有序对 (a, b)——a 应优于 b。实测中 a 未优于
    b 即为一次翻转；差值落在噪声内记为 noisy 翻转，否则记为 real 翻转。
    """
    order = [run for run in expected_order if run in aggregates]
    if len(order) < 2:
        return RankingJudgement(Verdict.NO_RESULT, [], [])

    is_better = (
        (lambda x, y: x > y) if spec.direction == "higher_better" else (lambda x, y: x < y)
    )
    real_flips: list[tuple[str, str]] = []
    noisy_flips: list[tuple[str, str]] = []

    for i, better_run in enumerate(order):
        for worse_run in order[i + 1 :]:
            mean_a = aggregates[better_run].mean
            mean_b = aggregates[worse_run].mean
            if is_better(mean_a, mean_b):
                continue
            noise = 2 * max(
                aggregates[better_run].sd or 0.0, aggregates[worse_run].sd or 0.0
            )
            if abs(mean_a - mean_b) <= noise:
                noisy_flips.append((better_run, worse_run))
            else:
                real_flips.append((better_run, worse_run))

    if real_flips:
        return RankingJudgement(Verdict.SURPRISE, real_flips, noisy_flips)
    if noisy_flips:
        return RankingJudgement(Verdict.NOISY, [], noisy_flips)
    return RankingJudgement(Verdict.CONFIRMED, [], [])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: 全部 PASS（累计 32 个）

- [ ] **Step 5: 提交**

```bash
git add src/ari/verdict.py tests/test_verdict.py
git commit -m "$(cat <<'EOF'
feat: batch 级排序判定

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 事件流投影

对应 spec §3.2、§3.7、§3.10、§2.1。把事件序列折叠成可渲染的状态，是全部规则汇合的地方。

**Files:**
- Create: `src/ari/project.py`
- Test: `tests/test_project.py`

- [ ] **Step 1: 写失败的测试**

```python
from ari.events import Event
from ari.project import project
from ari.verdict import Verdict


def _batch_opened(**overrides):
    payload = {
        "hypothesis": "large 比 base 好",
        "dimensions": {"model": ["base", "large"]},
        "metric_specs": {},
    }
    payload.update(overrides)
    return Event(ts="2026-08-23T10:00:00+08:00", type="batch_opened", batch="b1", payload=payload)


def _prediction(run, metrics, ts="2026-08-23T10:05:00+08:00", **extra):
    payload = {"metrics": metrics, "rationale": "因为容量更大", "confidence": "medium"}
    payload.update(extra)
    return Event(ts=ts, type="prediction", batch="b1", run=run, payload=payload)


def _result(run, metrics, seed=0, mtime="2026-08-23T12:00:00+08:00"):
    return Event(
        ts="2026-08-23T12:30:00+08:00", type="run_result", batch="b1", run=run,
        payload={"seed": seed, "metrics": metrics,
                 "source": {"path": f"logs/{run}/s{seed}/results.json",
                            "kind": "structured", "mtime": mtime}},
    )


def test_hypothesis_is_snapshotted_on_the_batch():
    batches, _ = project([_batch_opened()])

    assert batches["b1"].hypothesis == "large 比 base 好"


def test_prediction_and_result_produce_a_verdict():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=large", {"top1_acc": 0.831}),
    ])

    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.CONFIRMED
    assert run.aggregates["top1_acc"].n == 1


def test_multiple_seeds_aggregate_into_one_run():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=large", {"top1_acc": 0.828}, seed=0),
        _result("model=large", {"top1_acc": 0.832}, seed=1),
    ])

    run = batches["b1"].runs["model=large"]
    assert run.aggregates["top1_acc"].n == 2


def test_duplicate_prediction_is_rejected_and_warned():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        _prediction("model=large", {"top1_acc": 0.900}),
    ])

    run = batches["b1"].runs["model=large"]
    assert run.prediction["metrics"]["top1_acc"] == 0.830
    assert any("重复" in w for w in run.warnings)


def test_revision_keeps_the_original_and_marks_revised():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        Event(ts="2026-08-23T10:30:00+08:00", type="prediction_revised", batch="b1",
              run="model=large",
              payload={"metrics": {"top1_acc": 83.0}, "rationale": "单位写错了"}),
    ])

    run = batches["b1"].runs["model=large"]
    assert run.revised is True
    assert run.prediction["metrics"]["top1_acc"] == 83.0
    assert run.original_prediction["metrics"]["top1_acc"] == 0.830


def test_result_older_than_prediction_is_flagged():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}, ts="2026-08-23T10:05:00+08:00"),
        _result("model=large", {"top1_acc": 0.831}, mtime="2026-08-23T09:00:00+08:00"),
    ])

    assert "result_predates_prediction" in batches["b1"].runs["model=large"].integrity


def test_surprise_run_needs_its_own_reflection_to_close():
    events = [
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=large", {"top1_acc": 0.950}),
        Event(ts="t", type="reflection", batch="b1",
              payload={"scope": "batch", "text": "整体收口"}),
    ]

    batches, _ = project(events)
    run = batches["b1"].runs["model=large"]
    assert run.verdict is Verdict.SURPRISE
    assert run.closed is False
    assert batches["b1"].closed is False

    events.append(Event(ts="t2", type="reflection", batch="b1", run="model=large",
                        payload={"scope": "run", "text": "数据增强没关"}))
    batches, _ = project(events)
    assert batches["b1"].runs["model=large"].closed is True
    assert batches["b1"].closed is True


def test_confirmed_run_closes_via_batch_reflection():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=large", {"top1_acc": 0.831}),
        Event(ts="t", type="reflection", batch="b1",
              payload={"scope": "batch", "text": "符合预期"}),
    ])

    assert batches["b1"].runs["model=large"].closed is True


def test_all_confirmed_batch_raises_the_low_information_signal():
    batches, _ = project([
        _batch_opened(),
        _prediction("model=base", {"top1_acc": 0.800}),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=base", {"top1_acc": 0.801}),
        _result("model=large", {"top1_acc": 0.831}),
    ])

    assert batches["b1"].info_signal is not None


def test_ranking_is_judged_at_batch_level():
    batches, _ = project([
        _batch_opened(expected_ranking={"metric": "top1_acc",
                                        "order": ["model=large", "model=base"]}),
        _prediction("model=base", {"top1_acc": 0.800}),
        _prediction("model=large", {"top1_acc": 0.830}),
        _result("model=base", {"top1_acc": 0.860}),
        _result("model=large", {"top1_acc": 0.801}),
    ])

    assert batches["b1"].ranking.verdict is Verdict.SURPRISE


def test_unknown_event_type_is_warned_not_fatal():
    batches, warnings = project([
        _batch_opened(),
        Event(ts="t", type="from_the_future", batch="b1", v=99, payload={}),
    ])

    assert "b1" in batches
    assert any("from_the_future" in w for w in warnings)


def test_event_for_unopened_batch_is_warned():
    batches, warnings = project([_prediction("model=large", {"top1_acc": 0.8})])

    assert batches == {}
    assert any("b1" in w for w in warnings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_project.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.project'`

- [ ] **Step 3: 实现 `src/ari/project.py`**

```python
"""事件流 → 状态投影。见 spec §3.2、§3.7、§3.10。

runs.jsonl 是唯一真相来源，所有展示用的状态都是这里折叠出来的派生物。
board.md 与 beliefs.md 都可以删掉重新生成，不丢数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .events import SCHEMA_VERSION, Event
from .metrics import UnknownMetricError, spec_for
from .verdict import (
    Aggregate,
    RankingJudgement,
    Verdict,
    aggregate,
    judge_ranking,
    judge_run,
)

_KNOWN_TYPES = {
    "batch_opened",
    "prediction",
    "prediction_revised",
    "run_result",
    "reflection",
    "belief_added",
    "belief_weakened",
    "belief_reinforced",
    "belief_refuted",
    "note",
}

LOW_INFORMATION_SIGNAL = "本批次全部命中预期，未产生新信息——变量取值范围可能过于保守"


@dataclass
class RunState:
    batch: str
    run: str
    prediction: dict | None = None
    original_prediction: dict | None = None
    prediction_ts: str | None = None
    revised: bool = False
    samples: dict[str, dict[int, float]] = field(default_factory=dict)
    aggregates: dict[str, Aggregate] = field(default_factory=dict)
    verdict: Verdict = Verdict.NO_RESULT
    metric_judgements: dict = field(default_factory=dict)
    closed: bool = False
    integrity: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchState:
    id: str
    hypothesis: str = ""
    dimensions: dict = field(default_factory=dict)
    metric_specs: dict = field(default_factory=dict)
    expected_ranking: dict | None = None
    result_path: str | None = None
    opened_ts: str = ""
    runs: dict[str, RunState] = field(default_factory=dict)
    ranking: RankingJudgement | None = None
    batch_reflection: bool = False
    closed: bool = False
    info_signal: str | None = None
    warnings: list[str] = field(default_factory=list)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def project(events: list[Event]) -> tuple[dict[str, BatchState], list[str]]:
    """把事件流折叠成 batch/run 状态。返回 (batches, 全局警告)。"""
    batches: dict[str, BatchState] = {}
    warnings: list[str] = []

    for event in events:
        if event.v > SCHEMA_VERSION or event.type not in _KNOWN_TYPES:
            warnings.append(
                f"第 {event.line_no} 行：未知事件类型 {event.type!r}（v={event.v}），已跳过。"
                f"可能需要升级 ari"
            )
            continue

        if event.type == "batch_opened":
            batches[event.batch] = BatchState(
                id=event.batch,
                hypothesis=event.payload.get("hypothesis", ""),
                dimensions=event.payload.get("dimensions", {}),
                metric_specs=event.payload.get("metric_specs", {}),
                expected_ranking=event.payload.get("expected_ranking"),
                result_path=event.payload.get("result_path"),
                opened_ts=event.ts,
            )
            continue

        if event.type in ("note",) or event.type.startswith("belief_"):
            continue  # 由后续计划的信念账本消费

        batch = batches.get(event.batch)
        if batch is None:
            warnings.append(
                f"第 {event.line_no} 行：事件属于未开启的批次 {event.batch!r}，已跳过"
            )
            continue

        if event.type == "reflection":
            scope = event.payload.get("scope", "run" if event.run else "batch")
            if scope == "batch" or not event.run:
                batch.batch_reflection = True
            else:
                _run_state(batch, event.run).closed = True
            continue

        if event.run is None:
            warnings.append(f"第 {event.line_no} 行：{event.type} 缺少 run 字段，已跳过")
            continue

        run = _run_state(batch, event.run)

        if event.type == "prediction":
            if run.prediction is not None:
                run.warnings.append(
                    f"第 {event.line_no} 行：重复的 prediction 已忽略；"
                    f"修订请使用 prediction_revised"
                )
                continue
            run.prediction = event.payload
            run.prediction_ts = event.ts

        elif event.type == "prediction_revised":
            if run.prediction is None:
                run.warnings.append(f"第 {event.line_no} 行：修订了不存在的预测，已忽略")
                continue
            if run.original_prediction is None:
                run.original_prediction = run.prediction
            run.prediction = event.payload
            run.revised = True

        elif event.type == "run_result":
            seed = event.payload.get("seed", 0)
            for name, value in (event.payload.get("metrics") or {}).items():
                run.samples.setdefault(name, {})[seed] = float(value)
            _check_integrity(run, event)

    for batch in batches.values():
        _finalize(batch)

    return batches, warnings


def _run_state(batch: BatchState, run_key: str) -> RunState:
    if run_key not in batch.runs:
        batch.runs[run_key] = RunState(batch=batch.id, run=run_key)
    return batch.runs[run_key]


def _check_integrity(run: RunState, event: Event) -> None:
    """结果文件早于预测写入时间 → 先看结果再写预测的嫌疑。见 spec §2.1。"""
    mtime = _parse_ts((event.payload.get("source") or {}).get("mtime"))
    predicted_at = _parse_ts(run.prediction_ts)
    if mtime and predicted_at and mtime < predicted_at:
        if "result_predates_prediction" not in run.integrity:
            run.integrity.append("result_predates_prediction")


def _finalize(batch: BatchState) -> None:
    for run in batch.runs.values():
        run.aggregates = {
            name: aggregate(list(by_seed.values())) for name, by_seed in run.samples.items()
        }
        prediction_metrics = (run.prediction or {}).get("metrics", {})
        try:
            specs = {name: spec_for(name, batch.metric_specs) for name in prediction_metrics}
        except UnknownMetricError as exc:
            run.warnings.append(str(exc))
            run.verdict = Verdict.UNVERIFIED
            continue
        run.verdict, run.metric_judgements = judge_run(prediction_metrics, run.aggregates, specs)

    _finalize_ranking(batch)

    surprises_open = [
        r for r in batch.runs.values() if r.verdict is Verdict.SURPRISE and not r.closed
    ]
    if batch.batch_reflection:
        for run in batch.runs.values():
            if run.verdict is Verdict.CONFIRMED:
                run.closed = True
    batch.closed = batch.batch_reflection and not surprises_open

    all_confirmed = bool(batch.runs) and all(
        r.verdict is Verdict.CONFIRMED for r in batch.runs.values()
    )
    ranking_ok = batch.ranking is None or batch.ranking.verdict in (
        Verdict.CONFIRMED,
        Verdict.NO_RESULT,
    )
    batch.info_signal = LOW_INFORMATION_SIGNAL if all_confirmed and ranking_ok else None


def _finalize_ranking(batch: BatchState) -> None:
    if not batch.expected_ranking:
        return
    metric = batch.expected_ranking.get("metric")
    order = batch.expected_ranking.get("order") or []
    if not metric:
        batch.warnings.append("expected_ranking 缺少 metric 字段，无法判定排序")
        return
    aggregates = {
        key: run.aggregates[metric] for key, run in batch.runs.items() if metric in run.aggregates
    }
    try:
        spec = spec_for(metric, batch.metric_specs)
    except UnknownMetricError as exc:
        batch.warnings.append(str(exc))
        return
    batch.ranking = judge_ranking(order, aggregates, spec)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_project.py -v`
Expected: 12 passed

- [ ] **Step 5: 跑全量测试**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/ari/project.py tests/test_project.py
git commit -m "$(cat <<'EOF'
feat: 事件流到 batch/run 状态的投影

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `ari init`

对应 spec §2、§4。

**Files:**
- Create: `src/ari/cli.py`
- Test: `tests/test_cli_init.py`

- [ ] **Step 1: 写失败的测试**

```python
from typer.testing import CliRunner

from ari.cli import app

runner = CliRunner()


def test_init_creates_the_skeleton(tmp_path):
    result = runner.invoke(app, ["init", str(tmp_path / "proj")])

    assert result.exit_code == 0
    project = tmp_path / "proj"
    assert (project / "runs.jsonl").exists()
    assert (project / "logs").is_dir()
    assert (project / "config.toml").exists()


def test_config_template_never_contains_a_key(tmp_path):
    runner.invoke(app, ["init", str(tmp_path / "proj")])
    config = (tmp_path / "proj" / "config.toml").read_text(encoding="utf-8")

    # config.toml 要进 git，只能引用环境变量名
    assert "api_key_env" in config
    assert "api_key =" not in config


def test_init_refuses_to_overwrite_an_existing_project(tmp_path):
    runner.invoke(app, ["init", str(tmp_path / "proj")])
    (tmp_path / "proj" / "runs.jsonl").write_text("existing\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path / "proj")])

    assert result.exit_code != 0
    assert (tmp_path / "proj" / "runs.jsonl").read_text(encoding="utf-8") == "existing\n"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_init.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.cli'`

- [ ] **Step 3: 实现 `src/ari/cli.py`**

```python
"""ari 命令行入口。见 spec §4。"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="实验预测、记录与复盘闭环")

CONFIG_TEMPLATE = """\
# 本文件会进 git —— 只放平台地址与环境变量名，绝不放密钥。

[providers.openai]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[providers.anthropic]
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"

[roles]
# 复盘追问与 plan 阶段的定性判断
reason = "anthropic:<strong-model>"
# 日志抽取，v1 暂未启用
extract = "openai:<fast-model>"
"""


@app.command()
def init(path: str = typer.Argument(..., help="项目目录")) -> None:
    """建立项目目录骨架。"""
    project = Path(path)
    runs = project / "runs.jsonl"
    if runs.exists():
        typer.echo(f"{runs} 已存在，拒绝覆盖。", err=True)
        raise typer.Exit(code=1)

    (project / "logs").mkdir(parents=True, exist_ok=True)
    runs.touch()
    (project / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")

    typer.echo(f"已初始化 {project}")
    typer.echo("下一步：ari plan 开启第一个批次（尚未实现，当前可手写 runs.jsonl 后 ari board）")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_cli_init.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/cli.py tests/test_cli_init.py
git commit -m "$(cat <<'EOF'
feat: ari init

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 看板渲染

对应 spec §3.10、§4。渲染层的两条硬要求：**未复盘的 SURPRISE 必须置顶**，**措辞不得暗示「失败」**。

**Files:**
- Create: `src/ari/board.py`
- Test: `tests/test_board.py`

- [ ] **Step 1: 写失败的测试**

复用 `tests/test_project.py` 里的事件构造辅助函数——把 `_batch_opened` / `_prediction` / `_result` 提到 `tests/conftest.py` 作为 fixture 工厂，两个测试文件共用（DRY）。

```python
from ari.board import render_markdown
from ari.project import project


def test_unreflected_surprise_is_pinned_above_the_batch_sections(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.950))

    output = render_markdown(batches, warnings, parse_errors=[])

    pinned = output.index("待复盘")
    assert pinned < output.index("## 批次")


def test_no_failure_language_anywhere(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.950))

    output = render_markdown(batches, warnings, parse_errors=[])

    for word in ("失败", "错误", "不及格", "糟糕"):
        assert word not in output


def test_confirmed_run_is_not_pinned(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831))

    assert "待复盘" not in render_markdown(batches, warnings, parse_errors=[])


def test_low_information_signal_is_surfaced(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831))

    assert "未产生新信息" in render_markdown(batches, warnings, parse_errors=[])


def test_parse_errors_are_reported_with_line_numbers(make_events):
    from ari.events import ParseError

    batches, warnings = project(make_events(prediction=0.830, actual=0.831))
    output = render_markdown(batches, warnings,
                             parse_errors=[ParseError(7, "JSON 解析失败", "{ bad")])

    assert "第 7 行" in output


def test_integrity_flag_is_shown(make_events):
    batches, warnings = project(
        make_events(prediction=0.830, actual=0.831, result_mtime="2026-08-23T09:00:00+08:00")
    )

    assert "预测晚于结果" in render_markdown(batches, warnings, parse_errors=[])


def test_revised_prediction_is_marked(make_events):
    batches, warnings = project(make_events(prediction=0.830, actual=0.831, revise_to=0.900))

    assert "已修订" in render_markdown(batches, warnings, parse_errors=[])


def test_noisy_run_explains_why_no_conclusion(make_events):
    batches, warnings = project(
        make_events(prediction=0.830, actual=[0.80, 0.83, 0.86])
    )

    output = render_markdown(batches, warnings, parse_errors=[])
    assert "NOISY" in output
    assert "seed" in output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_board.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ari.board'`

- [ ] **Step 3: 实现 `src/ari/board.py`**

渲染为 markdown 字符串（`board.md` 的内容），终端展示由 cli 用 rich 打印同一份 markdown。单一来源，避免两套渲染逻辑漂移。

```python
"""看板渲染。见 spec §4。

两条硬要求：
1. 未复盘的 SURPRISE 置顶——这是对抗「跳过思考」的具体机制；
2. 不使用任何暗示「失败」的措辞——负结果与正结果同等重要。
"""

from __future__ import annotations

from .project import BatchState
from .verdict import Verdict

_VERDICT_LABEL = {
    Verdict.CONFIRMED: "CONFIRMED  符合预期",
    Verdict.SURPRISE: "SURPRISE   超出预期区间",
    Verdict.NOISY: "NOISY      噪声大于判定分辨率",
    Verdict.NO_RESULT: "NO_RESULT  尚无结果",
    Verdict.UNVERIFIED: "UNVERIFIED 结果待人工确认",
}


def _format_actual(agg) -> str:
    if agg is None:
        return "—"
    if agg.sd is None:
        return f"{agg.mean:.4g}"
    return f"{agg.mean:.4g} ± {agg.sd:.3g} (n={agg.n})"


def _format_prediction(value) -> str:
    if isinstance(value, (list, tuple)):
        return f"[{float(value[0]):.4g}, {float(value[1]):.4g}]"
    return f"{float(value):.4g}"


def render_markdown(batches: dict[str, BatchState], warnings, parse_errors) -> str:
    lines: list[str] = ["# 看板", "", "> 由 runs.jsonl 派生，可随时用 `ari board` 重新生成。", ""]

    pinned = [
        run
        for batch in batches.values()
        for run in batch.runs.values()
        if run.verdict is Verdict.SURPRISE and not run.closed
    ]
    if pinned:
        lines += [f"## 待复盘（{len(pinned)}）", ""]
        for run in pinned:
            lines.append(f"- `{run.batch}` / `{run.run}`")
            for name, judgement in run.metric_judgements.items():
                if judgement.verdict is not Verdict.SURPRISE:
                    continue
                predicted = _format_prediction(run.prediction["metrics"][name])
                actual = _format_actual(run.aggregates.get(name))
                lines.append(f"  - **{name}** 预测 {predicted} → 实测 {actual}")
            rationale = (run.prediction or {}).get("rationale")
            if rationale:
                lines.append(f"  - 当初的理由：{rationale}")
        lines += ["", "运行 `ari review` 逐个处理。", ""]

    for batch in batches.values():
        lines += _render_batch(batch)

    if parse_errors:
        lines += ["## 数据问题", ""]
        for err in parse_errors:
            lines.append(f"- 第 {err.line_no} 行：{err.reason}（该行已跳过，其余数据不受影响）")
        lines.append("")

    if warnings:
        lines += ["## 提示", ""] + [f"- {w}" for w in warnings] + [""]

    return "\n".join(lines)


def _render_batch(batch: BatchState) -> list[str]:
    status = "已收口" if batch.closed else "进行中"
    lines = [f"## 批次 {batch.id}（{status}）", ""]
    if batch.hypothesis:
        lines += [f"**假设：**{batch.hypothesis}", ""]

    lines += ["| run | 指标 | 预测 | 实测 | 判定 | 复盘 |", "|---|---|---|---|---|---|"]
    for key, run in batch.runs.items():
        label = f"`{key}`" + ("（已修订）" if run.revised else "")
        metrics = (run.prediction or {}).get("metrics", {})
        if not metrics:
            lines.append(f"| {label} | — | — | — | {_VERDICT_LABEL[run.verdict]} | — |")
            continue
        for i, (name, predicted) in enumerate(metrics.items()):
            judgement = run.metric_judgements.get(name)
            verdict = judgement.verdict if judgement else run.verdict
            lines.append(
                f"| {label if i == 0 else ''} | {name} | {_format_prediction(predicted)} "
                f"| {_format_actual(run.aggregates.get(name))} | {_VERDICT_LABEL[verdict]} "
                f"| {'✓' if run.closed else '待复盘' if verdict is Verdict.SURPRISE else '—'} |"
            )
    lines.append("")

    for run in batch.runs.values():
        for judgement in run.metric_judgements.values():
            if judgement.verdict is Verdict.NOISY:
                lines += [f"- `{run.run}`：{judgement.note}", ""]
                break
        if "result_predates_prediction" in run.integrity:
            lines += [
                f"- ⚠ `{run.run}`：结果文件的修改时间早于预测写入时间（预测晚于结果），"
                f"请确认这不是补记的预测",
                "",
            ]
        for warning in run.warnings:
            lines += [f"- `{run.run}`：{warning}", ""]

    if batch.ranking is not None:
        lines += [f"**排序预测：**{_VERDICT_LABEL[batch.ranking.verdict]}", ""]
        for better, worse in batch.ranking.real_flips:
            lines.append(f"- 预期 `{better}` 优于 `{worse}`，实测相反")
        for better, worse in batch.ranking.noisy_flips:
            lines.append(f"- 预期 `{better}` 优于 `{worse}`，实测差异落在噪声内，无法判定")
        lines.append("")

    if batch.info_signal:
        lines += [f"> {batch.info_signal}", ""]
    for warning in batch.warnings:
        lines += [f"- {warning}", ""]

    return lines
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_board.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/board.py tests/test_board.py tests/conftest.py tests/test_project.py
git commit -m "$(cat <<'EOF'
feat: 看板渲染，未复盘 SURPRISE 置顶

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `ari board` 与端到端验证

**Files:**
- Modify: `src/ari/cli.py`
- Create: `tests/fixtures/sample_runs.jsonl`
- Test: `tests/test_e2e.py`

- [ ] **Step 1: 造一份真实感的 fixture `tests/fixtures/sample_runs.jsonl`**

覆盖：4 个 run（2×2）、多 seed、一个 CONFIRMED、一个 SURPRISE、一个 NOISY、一条排序预测、一条修订、一行故意损坏的 JSON。

```jsonl
{"v":1,"ts":"2026-08-20T09:00:00+08:00","type":"batch_opened","batch":"b1","payload":{"hypothesis":"large 模型容量翻倍会带来 3 个点以上的提升，但数据量没变，可能被过拟合抵消","dimensions":{"model":["base","large"],"lr":["1e-3","1e-4"]},"metric_specs":{},"expected_ranking":{"metric":"top1_acc","order":["lr=0.0001,model=large","lr=0.001,model=large","lr=0.0001,model=base","lr=0.001,model=base"]},"result_path":"logs/{model}_{lr}/s{seed}/results.json"}}
{"v":1,"ts":"2026-08-20T09:12:00+08:00","type":"prediction","batch":"b1","run":"lr=0.0001,model=base","payload":{"metrics":{"top1_acc":[0.78,0.81],"train_loss":0.42},"confidence":"high","rationale":"这是我们跑过很多次的基线配置"}}
{"v":1,"ts":"2026-08-20T09:14:00+08:00","type":"prediction","batch":"b1","run":"lr=0.0001,model=large","payload":{"metrics":{"top1_acc":[0.82,0.85],"train_loss":0.35},"confidence":"medium","rationale":"容量翻倍，但数据量没变，预期收益被过拟合抵消一部分"}}
{"v":1,"ts":"2026-08-20T09:16:00+08:00","type":"prediction","batch":"b1","run":"lr=0.001,model=base","payload":{"metrics":{"top1_acc":0.76},"confidence":"low","rationale":"lr 偏大，预计略差于 1e-4"}}
{"v":1,"ts":"2026-08-20T09:18:00+08:00","type":"prediction","batch":"b1","run":"lr=0.001,model=large","payload":{"metrics":{"top1_acc":0.80},"confidence":"low","rationale":"大 lr 对大模型伤害更大"}}
{"v":1,"ts":"2026-08-20T09:25:00+08:00","type":"prediction_revised","batch":"b1","run":"lr=0.001,model=base","payload":{"metrics":{"top1_acc":0.755},"rationale":"上一条把去年的数字记错了","revised_reason":"笔误"}}
{ 这一行是故意写坏的，用来验证容错
{"v":1,"ts":"2026-08-21T20:00:00+08:00","type":"run_result","batch":"b1","run":"lr=0.0001,model=base","payload":{"seed":0,"metrics":{"top1_acc":0.796,"train_loss":0.431},"source":{"path":"logs/base_1e-4/s0/results.json","kind":"structured","mtime":"2026-08-21T19:58:00+08:00"}}}
{"v":1,"ts":"2026-08-21T20:00:05+08:00","type":"run_result","batch":"b1","run":"lr=0.0001,model=base","payload":{"seed":1,"metrics":{"top1_acc":0.801,"train_loss":0.428},"source":{"path":"logs/base_1e-4/s1/results.json","kind":"structured","mtime":"2026-08-21T19:59:00+08:00"}}}
{"v":1,"ts":"2026-08-21T21:00:00+08:00","type":"run_result","batch":"b1","run":"lr=0.0001,model=large","payload":{"seed":0,"metrics":{"top1_acc":0.883,"train_loss":0.298},"source":{"path":"logs/large_1e-4/s0/results.json","kind":"structured","mtime":"2026-08-21T20:58:00+08:00"}}}
{"v":1,"ts":"2026-08-21T22:00:00+08:00","type":"run_result","batch":"b1","run":"lr=0.001,model=base","payload":{"seed":0,"metrics":{"top1_acc":0.731},"source":{"path":"logs/base_1e-3/s0/results.json","kind":"structured","mtime":"2026-08-21T21:58:00+08:00"}}}
{"v":1,"ts":"2026-08-21T22:30:00+08:00","type":"run_result","batch":"b1","run":"lr=0.001,model=base","payload":{"seed":1,"metrics":{"top1_acc":0.779},"source":{"path":"logs/base_1e-3/s1/results.json","kind":"structured","mtime":"2026-08-21T22:28:00+08:00"}}}
{"v":1,"ts":"2026-08-21T23:00:00+08:00","type":"run_result","batch":"b1","run":"lr=0.001,model=large","payload":{"seed":0,"metrics":{"top1_acc":0.802},"source":{"path":"logs/large_1e-3/s0/results.json","kind":"structured","mtime":"2026-08-21T22:58:00+08:00"}}}
```

预期判定：`lr=0.0001,model=base` CONFIRMED（0.7985 落在 [0.78,0.81]，loss 0.4295 在 0.42±10% 内）；`lr=0.0001,model=large` SURPRISE（0.883 超出 [0.82,0.85]）；`lr=0.001,model=base` NOISY（两个 seed 差 0.048，2σ≈0.034 > 容差 0.005）；`lr=0.001,model=large` CONFIRMED。

> 执行时若实际判定与上述不符，先手算核对，再决定是 fixture 数值需要调还是实现有 bug。**不要为了让测试通过而改判定逻辑。**

- [ ] **Step 2: 写失败的端到端测试 `tests/test_e2e.py`**

```python
import shutil
from pathlib import Path

from typer.testing import CliRunner

from ari.cli import app

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "sample_runs.jsonl"


def _project(tmp_path):
    runner.invoke(app, ["init", str(tmp_path / "proj")])
    shutil.copy(FIXTURE, tmp_path / "proj" / "runs.jsonl")
    return tmp_path / "proj"


def test_board_renders_and_writes_board_md(tmp_path):
    project = _project(tmp_path)

    result = runner.invoke(app, ["board", "--project", str(project)])

    assert result.exit_code == 0
    assert (project / "board.md").exists()


def test_board_pins_the_surprise_and_reports_the_corrupt_line(tmp_path):
    project = _project(tmp_path)
    runner.invoke(app, ["board", "--project", str(project)])

    board = (project / "board.md").read_text(encoding="utf-8")

    assert "待复盘" in board
    assert "lr=0.0001,model=large" in board
    assert "第 7 行" in board  # 损坏行被报告，其余数据照常渲染
    assert "lr=0.001,model=base" in board  # 损坏行之后的数据没有丢


def test_board_is_regenerable_and_idempotent(tmp_path):
    project = _project(tmp_path)
    runner.invoke(app, ["board", "--project", str(project)])
    first = (project / "board.md").read_text(encoding="utf-8")

    (project / "board.md").unlink()
    runner.invoke(app, ["board", "--project", str(project)])

    assert (project / "board.md").read_text(encoding="utf-8") == first


def test_board_works_on_a_fresh_empty_project(tmp_path):
    runner.invoke(app, ["init", str(tmp_path / "empty")])

    result = runner.invoke(app, ["board", "--project", str(tmp_path / "empty")])

    assert result.exit_code == 0
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: FAIL — `board` 命令不存在

- [ ] **Step 4: 在 `src/ari/cli.py` 追加 `board` 命令**

```python
from rich.console import Console
from rich.markdown import Markdown

from .board import render_markdown
from .events import read_events
from .project import project as project_events


@app.command()
def board(
    project_dir: str = typer.Option(".", "--project", "-p", help="项目目录"),
    write: bool = typer.Option(True, help="同时写出 board.md"),
) -> None:
    """渲染看板。board.md 是派生产物，可随时重新生成。"""
    root = Path(project_dir)
    events, parse_errors = read_events(root / "runs.jsonl")
    batches, warnings = project_events(events)
    markdown = render_markdown(batches, warnings, parse_errors)

    if write:
        (root / "board.md").write_text(markdown, encoding="utf-8")

    Console().print(Markdown(markdown))
```

- [ ] **Step 5: 跑全量测试**

Run: `uv run pytest -v`
Expected: 全部 PASS（约 70 个）

- [ ] **Step 6: 人工验收——真的看一眼看板**

```bash
rm -rf /tmp/ari-demo && uv run ari init /tmp/ari-demo
cp tests/fixtures/sample_runs.jsonl /tmp/ari-demo/runs.jsonl
uv run ari board --project /tmp/ari-demo
```

Expected: 终端渲染出看板；顶部是待复盘的 `lr=0.0001,model=large`（预测 [0.82,0.85] → 实测 0.883），批次表里 `lr=0.001,model=base` 显示 NOISY 并说明需要更多 seed，排序预测有判定结果，末尾报告第 7 行损坏。

**这一步是这份计划真正的验收点。** 如果看板读起来别扭、信息层次不对，或者措辞让人觉得像在被打分——记下来，那是 `ari plan` / `ari review` 设计前必须先解决的问题。

- [ ] **Step 7: 提交**

```bash
git add src/ari/cli.py tests/test_e2e.py tests/fixtures/sample_runs.jsonl
git commit -m "$(cat <<'EOF'
feat: ari board 与端到端验证

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 完成检查

- [ ] `uv run pytest -v` 全绿
- [ ] Task 12 Step 6 的人工验收做过，看板读起来是顺的
- [ ] spec §9 要求「覆盖率最高」的四块——run key 规范化、单指标判定、run 聚合、排序判定——每一条规则都有对应的断言
- [ ] `runs.jsonl` 中途损坏一行不影响其余数据（已由 e2e 覆盖）
- [ ] 看板中不含任何暗示「失败」的措辞（已由 test_board 覆盖）

## 后续计划

本计划完成后再写，不要提前动手：

- **计划二：`ari plan` 与 `ari result`** —— YAML 草稿生成、`$EDITOR` 交互、填写校验与锁定、结构化结果解析与 `result_path` 模板反解、录入前确认。这是摩擦最大、最需要真实使用反馈的一环，应当在看板已经可用、能立刻看到填写成果之后再设计。
- **计划三：`ari review`、信念账本与 LLM 层** —— provider 适配器、角色配置、历史 SURPRISE 检索与针对性追问、`belief_*` 事件与 `beliefs.md` 渲染。
