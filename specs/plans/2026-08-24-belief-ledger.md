# 信念账本 实现计划（v1 第三阶段）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 @superpowers:executing-plans 逐个任务执行本计划。每个任务内部遵循 @superpowers:test-driven-development：先写失败的测试，跑一遍确认它失败，再写最小实现，跑绿，提交。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 让复盘的产物从「一段感想」变成「一条下次预测时用得上的判断」——`belief_*` 事件落地为账本，`beliefs.md` 由 `ari board` 派生渲染，`ari review` 在同一份草稿里顺手记下信念的增减。

**Architecture:** 新增 `beliefs.py`，与 `board.py` 同构：一个纯函数把事件折叠成状态（`project_beliefs`），一个纯函数把状态渲染成 markdown（`render_markdown`）。信念的增减是**独立事件**，不塞进 `reflection` 的 payload。`reviewing.py` 只多长出一段草稿与一个事件构造函数，`cli.py` 只做接线。`project.py` 不改行为（它继续跳过 `belief_*`，账本单独投影）。

**Tech Stack:** Python ≥3.11、PyYAML、typer、rich、pytest。不新增任何依赖。

**Spec:** `specs/2026-08-23-experiment-loop-design.md` §3.1、§3.2、§4、§7.1
**前置:** `specs/plans/2026-08-23-kernel-and-board.md`、`specs/plans/2026-08-24-interactive-loop.md`（均已完成）

**本计划不含：** LLM 层（provider 适配器、AI 的那份定性预测、复盘时的针对性追问）。那是计划四。spec §8 要求「LLM 不可用时所有非 LLM 功能必须能离线工作」——本计划交付的账本就是纯离线的，计划四只是在它之上加检索与追问。

---

## 交付定义

```bash
ari review -p ~/exp/lr-sweep   # 写复盘时，同一份草稿里顺手记下「我现在相信什么」
ari board  -p ~/exp/lr-sweep   # beliefs.md 随看板一并重新生成
```

- 一条信念被哪个批次加强、被哪个批次推翻，在 `beliefs.md` 上一眼看得到。
- 删掉 `beliefs.md` 可用 `ari board` 完整重建，不丢数据。
- 记信念是复盘的**副产品**，不是额外一步——不新增命令，不多开一次编辑器。

## 文件结构

```
src/ari/
  beliefs.py             新增。ID 生成 + 事件折叠 + beliefs.md 渲染
  reviewing.py           改。草稿多一段信念、解析多两个字段、新增 build_reflection_events
  cli.py                 改。review 接线信念；board 写 beliefs.md
  project.py             改。仅更新一处注释（行为不变）
tests/
  test_beliefs.py        新增。ID / 投影 / 渲染
  test_cli_board.py      新增。board 写出并可重建 beliefs.md
  test_reviewing.py      改。草稿的信念段、解析、事件构造
  test_cli_review.py     改。信念事件落盘
  test_e2e_loop.py       改。闭环里跑一次「加信念 → 看板 → 推翻它」
README.md                改。beliefs.md 的说明
```

## 三条贯穿全局的约束

1. **引用只用不可变短 ID。** `bel-7a3c` = 内容 hash 前 4 位。`beliefs.md` 里的 `1.` `2.` 只是渲染层给人看的编号（spec §3.2）。用序号做引用，插入或删除一条就会让历史上所有引用静默指向别的东西。
2. **信念是独立事件，不进 reflection 的 payload。** 同一条信念会被多次复盘引用；塞进 payload 就得翻遍所有 reflection 才能拼出账本。事件自带的 `batch` / `run` 已经记下了它出自哪次复盘。
3. **摩擦不能涨。** 信念段挂在已有的复盘草稿末尾，整段可以删掉不填。多一次编辑器往返就会退化成没人填——这是 spec §11 的头号风险。

> **跑测试：** 项目约定是 `uv run pytest`。若本机 `uv` 起不来（沙箱环境下 uv 缓存目录不可写），等价命令是 `PYTHONPATH=src .venv/bin/python -m pytest`。下文统一写 `uv run pytest`。

---

## Task 1: `beliefs.py` — 不可变短 ID

**Files:**
- Create: `src/ari/beliefs.py`
- Test: `tests/test_beliefs.py`

- [ ] **Step 1: 写失败的测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_beliefs.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ari.beliefs'`

- [ ] **Step 3: 写最小实现**

Create `src/ari/beliefs.py`：

```python
"""信念账本。见 spec §3.2、§7.1。

信念是这套流程真正沉淀下来的东西：批次会过去，run key 会失效，但
「lr 调低对大模型没用」这类判断会一直被下一次预测引用。账本记录它们
被哪次实验加强、被哪次实验推翻——既是自学习的载体，也是将来写
discussion 的原材料。

引用一律用不可变短 ID（bel-7a3c，内容 hash 前 4 位），不用序号：序号
引用只要插入或删除一条，历史上所有引用就会静默指向别的东西，那是会
污染全部历史数据的缺陷。beliefs.md 里的 1. 2. 只是渲染层给人看的编号。
"""

from __future__ import annotations

import hashlib

_ID_PREFIX = "bel-"
_MIN_ID_CHARS = 4
_MAX_ID_CHARS = 16


def normalize_text(text: str) -> str:
    """折叠空白。同一句话换个换行位置不该变成另一条信念。"""
    return " ".join(text.split())


def make_belief_id(text: str, existing: dict[str, str] | None = None) -> str:
    """内容 hash 前 4 位。同文本必得同 ID，所以重复添加是幂等的。

    existing 是已占用的 {id: text}。只在撞上同 ID 但不同文本时加长——
    加长是给真实 hash 碰撞留的后路，不是常态。
    """
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("信念内容不能为空")

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    taken = existing or {}
    for length in range(_MIN_ID_CHARS, _MAX_ID_CHARS + 1):
        candidate = _ID_PREFIX + digest[:length]
        held = taken.get(candidate)
        if held is None or normalize_text(held) == normalized:
            return candidate
    raise ValueError(f"信念 ID 冲突无法解决：{text!r}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_beliefs.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/beliefs.py tests/test_beliefs.py
git commit -m "feat: 信念的不可变短 ID"
```

---

## Task 2: `beliefs.py` — 事件折叠成账本

**Files:**
- Modify: `src/ari/beliefs.py`
- Test: `tests/test_beliefs.py`

`project.py` 继续跳过 `belief_*`（它投影的是 batch/run），账本单独折叠一遍同一份事件流。信念不属于任何批次——它跨批次存活，硬塞进 `BatchState` 只会把两件事搅在一起。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_beliefs.py`：

```python
from ari.beliefs import project_beliefs
from ari.events import Event


def _added(belief_id, text, ts="2026-08-24T10:00:00+08:00", batch="b1", run="model=large"):
    return Event(
        ts=ts, type="belief_added", batch=batch, run=run,
        payload={"id": belief_id, "text": text},
    )


def _changed(kind, belief_id, ts="2026-08-25T10:00:00+08:00", batch="b2", note=""):
    return Event(
        ts=ts, type=kind, batch=batch, run=None,
        payload={"id": belief_id, "note": note},
    )


def test_added_belief_lands_in_the_ledger():
    ledger, warnings = project_beliefs([_added("bel-aaaa", "大模型吃不下小 lr")])

    assert warnings == []
    assert ledger["bel-aaaa"].text == "大模型吃不下小 lr"
    assert ledger["bel-aaaa"].added_ts == "2026-08-24T10:00:00+08:00"
    assert ledger["bel-aaaa"].batch == "b1"
    assert ledger["bel-aaaa"].run == "model=large"
    assert ledger["bel-aaaa"].status == "在册"


def test_refuted_belief_is_marked_and_keeps_its_text():
    ledger, _ = project_beliefs([
        _added("bel-aaaa", "大模型吃不下小 lr"),
        _changed("belief_refuted", "bel-aaaa", note="换了调度器就不成立了"),
    ])

    belief = ledger["bel-aaaa"]
    assert belief.refuted
    assert belief.status == "已推翻"
    assert belief.text == "大模型吃不下小 lr"  # 推翻不是删除，历史必须留着
    assert belief.changes[0].note == "换了调度器就不成立了"
    assert belief.changes[0].batch == "b2"


def test_reinforced_and_weakened_shape_the_status():
    reinforced, _ = project_beliefs([
        _added("bel-aaaa", "x"), _changed("belief_reinforced", "bel-aaaa"),
    ])
    weakened, _ = project_beliefs([
        _added("bel-aaaa", "x"), _changed("belief_weakened", "bel-aaaa"),
    ])

    assert reinforced["bel-aaaa"].status == "已加强"
    assert weakened["bel-aaaa"].status == "动摇中"


def test_change_to_an_unknown_id_warns_instead_of_crashing():
    ledger, warnings = project_beliefs([_changed("belief_refuted", "bel-zzzz")])

    assert ledger == {}
    assert len(warnings) == 1
    assert "bel-zzzz" in warnings[0]


def test_duplicate_add_keeps_the_first_one():
    ledger, warnings = project_beliefs([
        _added("bel-aaaa", "x", ts="2026-08-24T10:00:00+08:00"),
        _added("bel-aaaa", "x", ts="2026-08-26T10:00:00+08:00"),
    ])

    assert len(ledger) == 1
    assert ledger["bel-aaaa"].added_ts == "2026-08-24T10:00:00+08:00"
    assert warnings == []


def test_malformed_add_is_reported_not_silently_dropped():
    ledger, warnings = project_beliefs([
        Event(ts="2026-08-24T10:00:00+08:00", type="belief_added", payload={"text": "没有 id"}),
    ])

    assert ledger == {}
    assert len(warnings) == 1


def test_ledger_order_follows_the_event_stream():
    ledger, _ = project_beliefs([
        _added("bel-bbbb", "第二个先写不行"),
        _added("bel-aaaa", "第一个"),
    ])

    assert list(ledger) == ["bel-bbbb", "bel-aaaa"]


def test_unrelated_events_are_ignored():
    ledger, warnings = project_beliefs([
        Event(ts="2026-08-24T10:00:00+08:00", type="run_result", batch="b1",
              run="model=large", payload={"seed": 0, "metrics": {"top1_acc": 0.9}}),
    ])

    assert ledger == {} and warnings == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_beliefs.py -v`
Expected: FAIL，`ImportError: cannot import name 'project_beliefs'`

- [ ] **Step 3: 写最小实现**

在 `src/ari/beliefs.py` 顶部的 import 段加 `from dataclasses import dataclass, field`，并在 `normalize_text` 之前加常量、在文件末尾追加实现：

```python
# 状态变更事件 → 给人看的动词。
CHANGE_TYPES = {
    "belief_weakened": "动摇",
    "belief_reinforced": "加强",
    "belief_refuted": "推翻",
}
```

```python
@dataclass(frozen=True)
class BeliefChange:
    kind: str
    ts: str
    note: str = ""
    batch: str | None = None
    run: str | None = None


@dataclass
class Belief:
    id: str
    text: str
    added_ts: str = ""
    batch: str | None = None
    run: str | None = None
    changes: list[BeliefChange] = field(default_factory=list)

    @property
    def refuted(self) -> bool:
        return any(c.kind == "belief_refuted" for c in self.changes)

    @property
    def status(self) -> str:
        """在册 / 已加强 / 动摇中 / 已推翻。

        只数次数，不做加权：加权需要一张说不清来源的权重表，而这里的
        用途只是排序和提示，撑不起那个复杂度。
        """
        if self.refuted:
            return "已推翻"
        weakened = sum(1 for c in self.changes if c.kind == "belief_weakened")
        reinforced = sum(1 for c in self.changes if c.kind == "belief_reinforced")
        if weakened > reinforced:
            return "动摇中"
        if reinforced:
            return "已加强"
        return "在册"


def project_beliefs(events) -> tuple[dict[str, Belief], list[str]]:
    """把 belief_* 事件折叠成账本。返回 (ledger, 警告)。

    引用不存在的 ID 只报警告不抛错：事件流可能被手动编辑过，一条悬空
    引用不该让整个账本不可用——这与 events.py 逐行容错是同一条原则。
    """
    ledger: dict[str, Belief] = {}
    warnings: list[str] = []

    for event in events:
        if event.type == "belief_added":
            belief_id = event.payload.get("id")
            text = (event.payload.get("text") or "").strip()
            if not belief_id or not text:
                warnings.append(
                    f"第 {event.line_no} 行：belief_added 缺少 id 或 text，已跳过"
                )
                continue
            if belief_id in ledger:
                continue  # 同一条信念重复添加，保留最早那次
            ledger[belief_id] = Belief(
                id=belief_id,
                text=text,
                added_ts=event.ts,
                batch=event.batch,
                run=event.run,
            )

        elif event.type in CHANGE_TYPES:
            belief_id = event.payload.get("id")
            belief = ledger.get(belief_id)
            if belief is None:
                warnings.append(
                    f"第 {event.line_no} 行：{event.type} 引用了不存在的信念 "
                    f"{belief_id!r}，已跳过"
                )
                continue
            belief.changes.append(
                BeliefChange(
                    kind=event.type,
                    ts=event.ts,
                    note=(event.payload.get("note") or "").strip(),
                    batch=event.batch,
                    run=event.run,
                )
            )

    return ledger, warnings
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_beliefs.py -v`
Expected: 16 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/beliefs.py tests/test_beliefs.py
git commit -m "feat: belief_* 事件折叠成信念账本"
```

---

## Task 3: `beliefs.py` — `beliefs.md` 渲染

**Files:**
- Modify: `src/ari/beliefs.py`
- Test: `tests/test_beliefs.py`

与 `board.py` 同一条约定：渲染只产出 markdown 字符串，写文件和打印终端都用它，避免两套渲染各自漂移。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_beliefs.py`：

```python
from ari.beliefs import render_markdown


def test_render_shows_human_numbering_and_the_immutable_id():
    ledger, _ = project_beliefs([_added("bel-aaaa", "大模型吃不下小 lr")])

    text = render_markdown(ledger)

    assert "1." in text
    assert "bel-aaaa" in text
    assert "大模型吃不下小 lr" in text
    assert "编号" in text  # 明确说明编号只是渲染层的产物


def test_render_separates_refuted_beliefs_and_keeps_them_visible():
    ledger, _ = project_beliefs([
        _added("bel-aaaa", "还成立的"),
        _added("bel-bbbb", "被推翻的"),
        _changed("belief_refuted", "bel-bbbb", note="换了调度器"),
    ])

    text = render_markdown(ledger)

    assert "在册" in text and "已推翻" in text
    assert text.index("还成立的") < text.index("被推翻的")  # 已推翻的排在后面
    assert "换了调度器" in text


def test_render_shows_where_a_belief_came_from_and_what_touched_it():
    ledger, _ = project_beliefs([
        _added("bel-aaaa", "x", batch="b1", run="model=large"),
        _changed("belief_reinforced", "bel-aaaa", batch="b3"),
    ])

    text = render_markdown(ledger)

    assert "b1" in text and "model=large" in text
    assert "b3" in text and "加强" in text


def test_render_on_an_empty_ledger_explains_how_to_get_one():
    text = render_markdown({})

    assert "review" in text  # 告诉用户信念从哪来，而不是丢一张空表
    assert "还没有" in text


def test_render_reports_dangling_references():
    ledger, warnings = project_beliefs([_changed("belief_refuted", "bel-zzzz")])

    text = render_markdown(ledger, warnings)

    assert "bel-zzzz" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_beliefs.py -v`
Expected: FAIL，`ImportError: cannot import name 'render_markdown'`

- [ ] **Step 3: 写最小实现**

追加到 `src/ari/beliefs.py`：

```python
def render_markdown(ledger: dict[str, Belief], warnings=()) -> str:
    """渲染 beliefs.md。已推翻的信念留在页面上，只是挪到后面。

    推翻不是删除：一条被证伪的信念连同证伪它的那次实验，正是 discussion
    里最有价值的段落。
    """
    lines = [
        "# 信念账本",
        "",
        "> 由 runs.jsonl 派生，可随时用 `ari board` 重新生成。",
        "> 下面的编号只是给人看的，事件流里引用的始终是 `bel-` 开头的 ID。",
        "",
    ]

    if not ledger:
        lines += [
            "还没有信念。`ari review` 复盘时会问你「现在相信什么」，写下的判断落在这里。",
            "",
        ]
    else:
        active = [b for b in ledger.values() if not b.refuted]
        retired = [b for b in ledger.values() if b.refuted]

        if active:
            lines += [f"## 在册（{len(active)}）", ""]
            for number, belief in enumerate(active, start=1):
                lines += _render_belief(number, belief)
        if retired:
            lines += [f"## 已推翻（{len(retired)}）", ""]
            for number, belief in enumerate(retired, start=1):
                lines += _render_belief(number, belief)

    if warnings:
        lines += ["## 提示", ""] + [f"- {w}" for w in warnings] + [""]

    return "\n".join(lines)


def _render_belief(number: int, belief: Belief) -> list[str]:
    lines = [f"### {number}. {belief.text}", "", f"- `{belief.id}` · {belief.status}"]
    if belief.batch:
        origin = f"- 来自 `{belief.batch}`"
        if belief.run:
            origin += f" / `{belief.run}`"
        lines.append(origin)
    for change in belief.changes:
        where = f"`{change.batch}`" if change.batch else "—"
        if change.run:
            where += f" / `{change.run}`"
        entry = f"- {CHANGE_TYPES[change.kind]} ← {where}"
        if change.note:
            entry += f"：{change.note}"
        lines.append(entry)
    lines.append("")
    return lines
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_beliefs.py -v`
Expected: 21 passed

- [ ] **Step 5: 提交**

```bash
git add src/ari/beliefs.py tests/test_beliefs.py
git commit -m "feat: beliefs.md 渲染，已推翻的信念留在页面上"
```

---

## Task 4: `ari board` 一并重新生成 `beliefs.md`

**Files:**
- Modify: `src/ari/cli.py:84-98`（`board` 命令）
- Modify: `src/ari/project.py:107-108`（仅注释）
- Test: `tests/test_cli_board.py`

spec §4 要求 `ari board` 含 `beliefs.md` 重新生成。悬空引用的警告并进看板的「提示」段——数据有问题就该在最常看的那一页上看到。

- [ ] **Step 1: 写失败的测试**

Create `tests/test_cli_board.py`：

```python
"""ari board 对 beliefs.md 的职责。见 spec §4、§7.1。

board.md 与 beliefs.md 都是 runs.jsonl 的派生产物：删掉能重建，
重建的结果必须与上一次逐字节相同。
"""

from __future__ import annotations

from typer.testing import CliRunner

from ari.cli import app

runner = CliRunner()

BELIEF_EVENTS = (
    '{"v":1,"ts":"2026-08-24T09:00:00+08:00","type":"batch_opened","batch":"b1",'
    '"payload":{"hypothesis":"large 更好","dimensions":{"model":["base","large"]},'
    '"metric_specs":{}}}\n'
    '{"v":1,"ts":"2026-08-24T13:00:00+08:00","type":"belief_added","batch":"b1",'
    '"run":"model=large","payload":{"id":"bel-aaaa","text":"大模型吃不下小 lr"}}\n'
)


def _project(tmp_path, contents):
    project = tmp_path / "p"
    runner.invoke(app, ["init", str(project)])
    (project / "runs.jsonl").write_text(contents, encoding="utf-8")
    return project


def test_board_writes_beliefs_md(tmp_path):
    project = _project(tmp_path, BELIEF_EVENTS)

    result = runner.invoke(app, ["board", "-p", str(project)])

    assert result.exit_code == 0
    beliefs = (project / "beliefs.md").read_text(encoding="utf-8")
    assert "大模型吃不下小 lr" in beliefs
    assert "bel-aaaa" in beliefs


def test_beliefs_md_is_regenerable_and_idempotent(tmp_path):
    project = _project(tmp_path, BELIEF_EVENTS)
    runner.invoke(app, ["board", "-p", str(project)])
    first = (project / "beliefs.md").read_text(encoding="utf-8")

    (project / "beliefs.md").unlink()
    runner.invoke(app, ["board", "-p", str(project)])

    assert (project / "beliefs.md").read_text(encoding="utf-8") == first


def test_no_write_flag_leaves_no_files(tmp_path):
    project = _project(tmp_path, BELIEF_EVENTS)

    runner.invoke(app, ["board", "-p", str(project), "--no-write"])

    assert not (project / "beliefs.md").exists()
    assert not (project / "board.md").exists()


def test_dangling_belief_reference_shows_up_on_the_board(tmp_path):
    project = _project(
        tmp_path,
        BELIEF_EVENTS
        + '{"v":1,"ts":"2026-08-25T09:00:00+08:00","type":"belief_refuted","batch":"b1",'
        '"payload":{"id":"bel-zzzz"}}\n',
    )

    runner.invoke(app, ["board", "-p", str(project)])

    assert "bel-zzzz" in (project / "board.md").read_text(encoding="utf-8")


def test_board_on_an_empty_project_still_writes_a_beliefs_md(tmp_path):
    project = _project(tmp_path, "")

    result = runner.invoke(app, ["board", "-p", str(project)])

    assert result.exit_code == 0
    assert "还没有" in (project / "beliefs.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_board.py -v`
Expected: 5 failed（`beliefs.md` 不存在）

- [ ] **Step 3: 写最小实现**

`src/ari/cli.py` 的 import 段加：

```python
from .beliefs import project_beliefs
from .beliefs import render_markdown as render_beliefs
```

把 `board` 命令替换为：

```python
@app.command()
def board(
    project_dir: str = typer.Option(".", "--project", "-p", help="项目目录"),
    write: bool = typer.Option(True, help="同时写出 board.md 与 beliefs.md"),
) -> None:
    """渲染看板。board.md 与 beliefs.md 都是派生产物，可随时重新生成。"""
    root = Path(project_dir)
    events, parse_errors = read_events(root / "runs.jsonl")
    batches, warnings = project_events(events)
    ledger, belief_warnings = project_beliefs(events)
    markdown = render_markdown(batches, warnings + belief_warnings, parse_errors)
    beliefs_markdown = render_beliefs(ledger)

    if write:
        (root / "board.md").write_text(markdown, encoding="utf-8")
        (root / "beliefs.md").write_text(beliefs_markdown, encoding="utf-8")

    console = Console()
    console.print(Markdown(markdown))
    if ledger:
        console.print(Markdown(beliefs_markdown))
```

`src/ari/project.py:107-108` 的注释改成实况（行为不变）：

```python
        if event.type == "note" or event.type.startswith("belief_"):
            continue  # 信念跨批次存活，由 beliefs.py 单独投影
```

- [ ] **Step 4: 跑全量测试**

Run: `uv run pytest -q`
Expected: 全绿（原有 203 + 本任务新增）

- [ ] **Step 5: 提交**

```bash
git add src/ari/cli.py src/ari/project.py tests/test_cli_board.py
git commit -m "feat: ari board 一并重新生成 beliefs.md"
```

---

## Task 5: 复盘草稿的信念段

**Files:**
- Modify: `src/ari/reviewing.py`
- Test: `tests/test_reviewing.py`

关键取舍：信念段挂在**已有草稿的末尾**，不另开一次编辑器。整段可以删掉不填。`parse_reflection` 的返回值保持 dict 且原有三个键不动，只增加两个键——已有调用方与测试不受影响。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_reviewing.py`（顶部 import 加 `build_batch_draft`）：

```python
from ari.beliefs import project_beliefs
from ari.reviewing import build_batch_draft


def _ledger(*texts):
    events = [
        Event(
            ts="2026-08-20T10:00:00+08:00", type="belief_added", batch="b0",
            payload={"id": f"bel-{i:04d}", "text": text},
        )
        for i, text in enumerate(texts)
    ]
    ledger, _ = project_beliefs(events)
    return ledger


def test_draft_asks_what_you_now_believe():
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0])

    assert "beliefs_added" in draft


def test_draft_lists_existing_beliefs_with_their_ids():
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0], _ledger("大模型吃不下小 lr"))

    assert "bel-0000" in draft
    assert "大模型吃不下小 lr" in draft  # 光有 ID 认不出是哪条
    assert "unchanged" in draft


def test_draft_hides_refuted_beliefs():
    ledger = _ledger("还成立的", "被推翻的")
    ledger["bel-0001"].changes.append(
        BeliefChange(kind="belief_refuted", ts="2026-08-21T10:00:00+08:00")
    )
    batches, _ = project(_batch_with(0.830, 0.950))

    draft = build_reflection_draft(pending(batches)[0], ledger)

    assert "bel-0000" in draft
    assert "bel-0001" not in draft  # 已经推翻的不再问


def test_batch_draft_also_carries_the_belief_section():
    # 全 CONFIRMED 的批次没有 run 级复盘，收口是记信念的唯一入口
    assert "beliefs_added" in build_batch_draft("b1", _ledger("x"))


def test_parse_reads_added_beliefs():
    parsed = parse_reflection(
        "cause: 增强没关\nbeliefs_added:\n  - 大模型吃不下小 lr\n  - 增强对小数据集有害\n"
    )

    assert parsed["beliefs_added"] == ["大模型吃不下小 lr", "增强对小数据集有害"]


def test_parse_skips_the_untouched_placeholder():
    draft = build_reflection_draft(
        pending(project(_batch_with(0.830, 0.950))[0])[0]
    ).replace("<为什么会这样？>", "增强没关")

    parsed = parse_reflection(draft)

    assert parsed["beliefs_added"] == []
    assert parsed["belief_changes"] == {}


def test_parse_reads_belief_changes_and_drops_unchanged():
    parsed = parse_reflection(
        "cause: 增强没关\nbeliefs:\n  bel-0000: refuted\n  bel-0001: unchanged\n"
        "  bel-0002: reinforced\n"
    )

    assert parsed["belief_changes"] == {
        "bel-0000": "belief_refuted",
        "bel-0002": "belief_reinforced",
    }


def test_parse_rejects_an_unknown_belief_status():
    with pytest.raises(ValueError) as exc:
        parse_reflection("cause: 增强没关\nbeliefs:\n  bel-0000: 大概吧\n")

    assert "bel-0000" in str(exc.value)


def test_reflection_without_a_belief_section_is_still_valid():
    parsed = parse_reflection("cause: 增强没关\nnext: 重跑\n")

    assert parsed["beliefs_added"] == [] and parsed["belief_changes"] == {}


def test_any_untouched_angle_bracket_placeholder_counts_as_blank():
    # batch 收口草稿的占位符与 run 级的不是同一句。信念段让「只填信念、
    # 不动 cause」变得更可能，所以占位符判定必须是通用规则而不是硬编码。
    with pytest.raises(ValueError):
        parse_reflection(build_batch_draft("b1") + "\n")


def test_untouched_next_placeholder_becomes_blank():
    assert parse_reflection("cause: 真的原因\nnext: <随便写点什么>\n")["next"] == ""
```

`tests/test_reviewing.py` 顶部的 import 加上 `from ari.beliefs import BeliefChange`。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_reviewing.py -v`
Expected: 新增的 9 个失败（`beliefs_added` 不在草稿里 / `build_reflection_draft` 不接第二个参数 / `KeyError: 'beliefs_added'`）

- [ ] **Step 3: 写最小实现**

`src/ari/reviewing.py`：把模块 docstring 里那句「本模块不含 LLM 追问（留给计划三）」改成「留给计划四」，加 `import re`，然后加常量：

```python
_ADDED_PLACEHOLDER = "<这次之后你新相信了什么？没有就把这一行删掉>"

# 未动过的占位符按形状识别，不硬编码原文：草稿不止一份（run 级与 batch
# 级的提示语不同），硬编码就必然漏掉其中一份。
_PLACEHOLDER_RE = re.compile(r"^<.*>$", re.DOTALL)

# 草稿里写给人的词 → 事件类型。unchanged 映射到 None，解析时丢弃。
_BELIEF_KINDS = {
    "unchanged": None,
    "reinforced": "belief_reinforced",
    "weakened": "belief_weakened",
    "refuted": "belief_refuted",
}
```

加信念段的构造：

```python
def _belief_section(ledger: dict | None) -> list[str]:
    """挂在复盘草稿末尾的信念段。

    刻意不另开一次编辑器：多一次往返，这一段就没人填了。整段可以删掉。
    """
    lines = [
        "",
        "# ── 信念 ────────────────────────────────────────────────────",
        "# 复盘的产物不该是一段感想，而是一条下次预测时用得上的判断。",
        "# 整段都可以删掉。",
        "",
        "# 一行一条。",
        "beliefs_added:",
        f"  - {_ADDED_PLACEHOLDER}",
    ]

    active = [b for b in (ledger or {}).values() if not b.refuted]
    if active:
        lines += [
            "",
            "# 这次结果动了哪些已有的信念？把 unchanged 改成",
            "# reinforced / weakened / refuted，没被动到的不用管。",
            "beliefs:",
        ]
        lines += [f"  {b.id}: unchanged   # {b.text}" for b in active]
    return lines
```

`build_reflection_draft` 改签名并在末尾拼上信念段——把原来结尾的

```python
        f"cause: {_CAUSE_PLACEHOLDER}",
        f"next:  {_NEXT_PLACEHOLDER}",
        "",
    ]
    return "\n".join(lines)
```

替换为

```python
        f"cause: {_CAUSE_PLACEHOLDER}",
        f"next:  {_NEXT_PLACEHOLDER}",
    ]
    lines += _belief_section(ledger)
    lines.append("")
    return "\n".join(lines)
```

签名同时改成 `def build_reflection_draft(run, ledger: dict | None = None) -> str:`。

`parse_reflection` 里 cause / next 的取值改成走同一个 `_filled`——原来的

```python
    cause = (data.get("cause") or "")
    cause = cause.strip() if isinstance(cause, str) else str(cause)
    if not cause or cause == _CAUSE_PLACEHOLDER:
        raise ValueError("cause 不能为空——写不出原因，就写下「还不知道」和你打算怎么查")

    nxt = (data.get("next") or "")
    nxt = nxt.strip() if isinstance(nxt, str) else str(nxt)
    if nxt == _NEXT_PLACEHOLDER:
        nxt = ""
```

替换为

```python
    cause = _filled(data.get("cause"))
    if not cause:
        raise ValueError("cause 不能为空——写不出原因，就写下「还不知道」和你打算怎么查")

    nxt = _filled(data.get("next"))
```

并新增 `_filled`：

```python
def _filled(value) -> str:
    """取一个字段的值，没动过的 <占位符> 一律算没填。"""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    text = text.strip()
    return "" if _PLACEHOLDER_RE.match(text) else text
```

`parse_reflection` 的 `return` 换成：

```python
    return {
        "scope": scope,
        "cause": cause,
        "next": nxt,
        "beliefs_added": _parse_added(data.get("beliefs_added")),
        "belief_changes": _parse_changes(data.get("beliefs")),
    }


def _parse_added(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("beliefs_added 应该是一个列表，一行一条")
    return [text for text in (_filled(item) for item in raw) if text]


def _parse_changes(raw) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("beliefs 应该是「信念 ID: 状态」的映射")
    changes = {}
    for belief_id, kind in raw.items():
        key = str(kind).strip().lower()
        if key not in _BELIEF_KINDS:
            raise ValueError(
                f"{belief_id} 的状态应该是 {'/'.join(_BELIEF_KINDS)} 之一，收到 {kind!r}"
            )
        if _BELIEF_KINDS[key]:
            changes[str(belief_id)] = _BELIEF_KINDS[key]
    return changes
```

（原来的 `return {"scope": scope, "cause": cause, "next": nxt}` 整行删掉。`_CAUSE_PLACEHOLDER` / `_NEXT_PLACEHOLDER` 两个常量保留，它们仍被草稿构造用到。）

`build_batch_draft` 与 `BATCH_DRAFT` 改成：

```python
BATCH_DRAFT = """\
# ── 收口 {batch_id} ──────────────────────────────────────────────────
# 所有 SURPRISE 都复盘完了。写一句这个批次整体的结论，批次即收口。
# 想跳过就清空整个文件再保存。

cause: <这一批整体学到了什么？>
next:  <下一批打算验证什么？可以留空>\
"""


def build_batch_draft(batch_id: str, ledger: dict | None = None) -> str:
    return BATCH_DRAFT.format(batch_id=batch_id) + "\n".join(_belief_section(ledger)) + "\n"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_reviewing.py -v`
Expected: 全绿（原有 13 + 新增 9）

- [ ] **Step 5: 提交**

```bash
git add src/ari/reviewing.py tests/test_reviewing.py
git commit -m "feat: 复盘草稿里顺手记下信念的增减"
```

---

## Task 6: 复盘 → 信念事件

**Files:**
- Modify: `src/ari/reviewing.py`、`src/ari/cli.py:346-399`（`review` 命令）
- Test: `tests/test_reviewing.py`、`tests/test_cli_review.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_reviewing.py`：

```python
from ari.reviewing import build_reflection_events

NOW = "2026-08-24T15:00:00+08:00"


def test_reflection_payload_carries_no_belief_keys():
    parsed = parse_reflection("cause: 增强没关\nbeliefs_added:\n  - 新信念\n")

    events = build_reflection_events(parsed, "b1", "model=large", {}, NOW)

    assert events[0].type == "reflection"
    assert set(events[0].payload) == {"scope", "cause", "next"}


def test_added_belief_becomes_its_own_event_with_provenance():
    parsed = parse_reflection("cause: 增强没关\nbeliefs_added:\n  - 大模型吃不下小 lr\n")

    events = build_reflection_events(parsed, "b1", "model=large", {}, NOW)

    added = [e for e in events if e.type == "belief_added"]
    assert len(added) == 1
    assert added[0].payload["text"] == "大模型吃不下小 lr"
    assert added[0].payload["id"].startswith("bel-")
    assert (added[0].batch, added[0].run) == ("b1", "model=large")
    assert added[0].ts == NOW


def test_belief_already_in_the_ledger_is_not_added_twice():
    ledger = _ledger("大模型吃不下小 lr")
    text = ledger["bel-0000"].text
    parsed = parse_reflection(f"cause: 增强没关\nbeliefs_added:\n  - {text}\n")
    # 账本里那条的 ID 是测试造的，重算一次才对得上
    ledger = {make_belief_id(text): ledger["bel-0000"]}

    events = build_reflection_events(parsed, "b1", "model=large", ledger, NOW)

    assert [e.type for e in events] == ["reflection"]


def test_the_same_belief_twice_in_one_draft_is_added_once():
    parsed = parse_reflection("cause: x\nbeliefs_added:\n  - 同一条\n  - 同一条\n")

    events = build_reflection_events(parsed, "b1", None, {}, NOW)

    assert len([e for e in events if e.type == "belief_added"]) == 1


def test_changes_become_belief_events():
    parsed = parse_reflection("cause: x\nbeliefs:\n  bel-0000: refuted\n")

    events = build_reflection_events(parsed, "b1", "model=large", _ledger("x"), NOW)

    assert [e.type for e in events] == ["reflection", "belief_refuted"]
    assert events[1].payload["id"] == "bel-0000"
    assert events[1].batch == "b1"
```

`tests/test_reviewing.py` 顶部 import 加 `from ari.beliefs import make_belief_id`。

追加到 `tests/test_cli_review.py`：

```python
REFLECTION_WITH_BELIEF = (
    "cause: 数据增强没关\nnext: 关掉重跑\nbeliefs_added:\n  - 增强对小数据集有害\n"
)


def test_review_writes_belief_events(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION_WITH_BELIEF))

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    added = [e for e in events if e.type == "belief_added"]
    assert len(added) == 1
    assert added[0].payload["text"] == "增强对小数据集有害"
    assert added[0].run == "model=large"
    reflection = [e for e in events if e.type == "reflection"][0]
    assert "beliefs_added" not in reflection.payload


def test_second_run_sees_the_belief_written_while_reviewing_the_first(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path, second_run=True)
    editor = FakeEditor(REFLECTION_WITH_BELIEF, REFLECTION)
    monkeypatch.setattr(cli, "edit_text", editor)

    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    # 第二个 run 的草稿里应当已经列出刚写下的那条信念
    assert "增强对小数据集有害" in editor.seen[1]


def test_reviewing_the_same_belief_twice_does_not_duplicate_it(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path, second_run=True)
    monkeypatch.setattr(
        cli, "edit_text", FakeEditor(REFLECTION_WITH_BELIEF, REFLECTION_WITH_BELIEF)
    )

    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    events, _ = read_events(project / "runs.jsonl")
    assert len([e for e in events if e.type == "belief_added"]) == 1


def test_batch_closure_can_also_record_a_belief(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    monkeypatch.setattr(
        cli, "edit_text", FakeEditor(REFLECTION, "cause: 整体结论\nbeliefs_added:\n  - 批次级信念\n")
    )

    runner.invoke(cli.app, ["review", "-p", str(project)], input="y\n")

    events, _ = read_events(project / "runs.jsonl")
    added = [e for e in events if e.type == "belief_added"]
    assert [e.payload["text"] for e in added] == ["批次级信念"]
    assert added[0].run is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_reviewing.py tests/test_cli_review.py -v`
Expected: FAIL，`ImportError: cannot import name 'build_reflection_events'`

- [ ] **Step 3: 写最小实现**

`src/ari/reviewing.py` 的 import 段加 `from .beliefs import make_belief_id, normalize_text`、`from .events import Event`，并在文件末尾追加：

```python
def build_reflection_events(
    parsed: dict, batch: str, run: str | None, ledger: dict | None, now: str
) -> list[Event]:
    """一份复盘草稿 → reflection + 若干 belief_* 事件。ts 由调用方注入。

    信念的增减是独立事件（spec §3.1），不塞进 reflection 的 payload：同一条
    信念会被多次复盘引用，塞进 payload 就得翻遍所有 reflection 才能拼出账本。
    事件自带的 batch / run 已经记下了它出自哪次复盘。
    """
    payload = {key: parsed[key] for key in ("scope", "cause", "next")}
    events = [Event(ts=now, type="reflection", batch=batch, run=run, payload=payload)]

    known = {bid: belief.text for bid, belief in (ledger or {}).items()}
    for text in parsed.get("beliefs_added") or []:
        belief_id = make_belief_id(text, known)
        held = known.get(belief_id)
        if held is not None and normalize_text(held) == normalize_text(text):
            continue  # 账本里已经有这一条，不重复记
        known[belief_id] = text
        events.append(
            Event(
                ts=now,
                type="belief_added",
                batch=batch,
                run=run,
                payload={"id": belief_id, "text": text},
            )
        )

    for belief_id, kind in (parsed.get("belief_changes") or {}).items():
        events.append(
            Event(ts=now, type=kind, batch=batch, run=run, payload={"id": belief_id})
        )

    return events
```

`src/ari/cli.py` 的 `from .reviewing import (...)` 里加 `build_reflection_events`，并把 `review` 命令的函数体替换为：

```python
    root = Path(project_dir)
    runs_path = root / "runs.jsonl"
    events, _ = read_events(runs_path)
    batches, _ = project_events(events)

    if not batches:
        typer.echo("这个项目还没有批次。先运行 ari plan 开一个。", err=True)
        raise typer.Exit(code=1)

    ledger, _ = project_beliefs(events)
    queue = pending(batches)
    if queue:
        typer.echo(f"有 {len(queue)} 个 SURPRISE 待复盘。")
    else:
        typer.echo("没有待复盘的 SURPRISE——这一批要么全部符合预期，要么属于噪声，先补 seed。")

    def _write(parsed, batch_id: str, run_key: str | None) -> None:
        """写事件并把刚写下的信念并进账本，让后续草稿看得到。"""
        nonlocal events, ledger
        new = build_reflection_events(parsed, batch_id, run_key, ledger, _now())
        for event in new:
            append_event(runs_path, event)
        events = events + new
        ledger, _ = project_beliefs(events)

    try:
        for run in queue:
            parsed = _edit_reflection(
                build_reflection_draft(run, ledger), scope="run", name=f"review-{run.run}"
            )
            if parsed is None:
                typer.echo(f"跳过 {run.run}。")
                continue
            _write(parsed, run.batch, run.run)
            typer.echo(f"已记录 {run.run} 的复盘。")
    except EditorUnavailable as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    batch = list(batches.values())[-1]
    if not typer.confirm(f"给批次 {batch.id} 写一句整体收口？", default=False):
        return

    parsed = _edit_reflection(
        build_batch_draft(batch.id, ledger), scope="batch", name=f"review-{batch.id}-close"
    )
    if parsed is None:
        typer.echo("没有写收口，批次保持进行中。")
        return
    _write(parsed, batch.id, None)
    typer.echo(f"批次 {batch.id} 已收口。")
```

- [ ] **Step 4: 跑全量测试**

Run: `uv run pytest -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add src/ari/reviewing.py src/ari/cli.py tests/test_reviewing.py tests/test_cli_review.py
git commit -m "feat: 复盘写出 belief_* 事件，账本随复盘增长"
```

---

## Task 7: 端到端、文档与收尾

**Files:**
- Modify: `tests/test_e2e_loop.py`、`README.md`、`src/ari/cli.py:81`

顺手修掉一处过时提示：`cli.py:81` 的 `init` 还在说「ari plan 尚未实现，当前可手写 runs.jsonl」——第二阶段已经实现了。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_e2e_loop.py`（沿用该文件已有的 `DESIGN` / `PREDICTIONS` / `_write_result` / `FakeEditor`）：

```python
def test_belief_survives_the_loop_and_can_be_refuted_later(tmp_path, monkeypatch):
    project = tmp_path / "exp"
    runner.invoke(cli.app, ["init", str(project)])

    # 第一轮：跑出 SURPRISE，复盘时写下一条信念
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    runner.invoke(cli.app, ["plan", "-p", str(project)])
    _write_result(project, "large", 0.95)
    _write_result(project, "base", 0.801)
    monkeypatch.setattr(cli, "edit_text", FakeEditor())
    runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")
    monkeypatch.setattr(
        cli,
        "edit_text",
        FakeEditor("cause: 增强没关\nbeliefs_added:\n  - 增强对小数据集有害\n"),
    )
    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")
    runner.invoke(cli.app, ["board", "-p", str(project)])

    beliefs = (project / "beliefs.md").read_text(encoding="utf-8")
    assert "增强对小数据集有害" in beliefs
    assert "在册" in beliefs

    # 第二轮：同一条信念被后来的复盘推翻
    from ari.beliefs import make_belief_id

    belief_id = make_belief_id("增强对小数据集有害")
    monkeypatch.setattr(
        cli,
        "edit_text",
        FakeEditor(f"cause: 换了调度器就不成立了\nbeliefs:\n  {belief_id}: refuted\n"),
    )
    runner.invoke(cli.app, ["review", "-p", str(project)], input="y\n")
    runner.invoke(cli.app, ["board", "-p", str(project)])

    beliefs = (project / "beliefs.md").read_text(encoding="utf-8")
    assert "已推翻" in beliefs
    assert "增强对小数据集有害" in beliefs  # 推翻不是删除


def test_beliefs_md_is_a_derived_product(tmp_path, monkeypatch):
    project = tmp_path / "exp"
    runner.invoke(cli.app, ["init", str(project)])
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    runner.invoke(cli.app, ["plan", "-p", str(project)])
    _write_result(project, "large", 0.95)
    _write_result(project, "base", 0.801)
    monkeypatch.setattr(cli, "edit_text", FakeEditor())
    runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")
    monkeypatch.setattr(
        cli, "edit_text", FakeEditor("cause: 增强没关\nbeliefs_added:\n  - 一条信念\n")
    )
    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")
    runner.invoke(cli.app, ["board", "-p", str(project)])
    first = (project / "beliefs.md").read_text(encoding="utf-8")

    (project / "beliefs.md").unlink()
    runner.invoke(cli.app, ["board", "-p", str(project)])

    assert (project / "beliefs.md").read_text(encoding="utf-8") == first
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_e2e_loop.py -v`
Expected: 新增 2 个失败

- [ ] **Step 3: 实现 / 修文档**

绝大部分实现已由 Task 1–6 完成，本步只做三件事：

1. 若测试暴露问题，在这里修。
2. `src/ari/cli.py:81` 的过时提示改成：`typer.echo("下一步：ari plan 开启第一个批次。")`
3. `README.md`：
   - `ari board` 那一行的说明补上 beliefs.md；
   - 「判定」小节末尾那句 `beliefs.md（后续）` 去掉「后续」；
   - 在「命令」表后新增一小节：

```markdown
### 信念账本

复盘不止是写一段感想。`ari review` 的草稿末尾会问两件事：

- **你现在相信什么？** 写下的每一条进账本，拿到一个不可变短 ID（`bel-7a3c`，内容 hash 前 4 位）。
- **这次结果动了哪些已有信念？** 把 `unchanged` 改成 `reinforced` / `weakened` / `refuted`。

`beliefs.md` 由这些事件派生，随 `ari board` 一并重新生成。被推翻的信念不会消失，只是挪到「已推翻」一节——一条被证伪的判断连同证伪它的那次实验，正是 discussion 里最有价值的段落。

引用只用 ID，不用序号：用 `#3` 这类序号引用，插入或删除一条就会让历史上所有引用静默指向别的东西。`beliefs.md` 里的编号只是渲染层给人看的。
```

- [ ] **Step 4: 跑全量测试 + 手动验证**

```bash
uv run pytest -q
./bin/ari --help
```

Expected: 测试全绿；`--help` 正常列出五个命令。

- [ ] **Step 5: 提交**

```bash
git add tests/test_e2e_loop.py README.md src/ari/cli.py
git commit -m "docs: 信念账本的端到端测试与 README"
```

---

## 完成检查

- [ ] `uv run pytest` 全绿
- [ ] `ari review` 只开一次编辑器，信念段可以整段删掉不填（有测试覆盖）
- [ ] `reflection` 事件的 payload 里没有信念字段（有测试覆盖）
- [ ] 删掉 `beliefs.md` 后 `ari board` 能逐字节重建（有测试覆盖）
- [ ] 悬空的信念引用只报警告，不让账本或看板不可用（有测试覆盖）
- [ ] 已推翻的信念仍留在 `beliefs.md` 上（有测试覆盖）
- [ ] `README.md` 与代码里没有残留「尚未实现」「留给计划三」这类过时表述
