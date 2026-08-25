"""ari review 命令接线测试。见 plan 第二阶段 Task 9。

review 的职责：读事件流 → 列出待复盘的 SURPRISE → 逐个打开编辑器写复盘 →
追加 reflection 事件。事件流怎么来不归 review 管，这里直接手写一个带 SURPRISE
的序列，聚焦 review 自身的行为。
"""

from __future__ import annotations

from typer.testing import CliRunner

from ari import cli
from ari.events import read_events

runner = CliRunner()


class FakeEditor:
    """按顺序吐出预置文本，并记录每次收到的初始内容。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def __call__(self, initial, name="draft", suffix=".yaml"):
        self.seen.append(initial)
        return self.responses.pop(0) if self.responses else None


# 一个 run 预测 0.83、实测 0.95 → SURPRISE；batch b1。
def _surprise_project(tmp_path, second_run=False):
    project = tmp_path / "p"
    runner.invoke(cli.app, ["init", str(project)])
    runs_jsonl = project / "runs.jsonl"
    lines = [
        '{"v":1,"ts":"2026-08-24T09:00:00+08:00","type":"batch_opened","batch":"b1",'
        '"payload":{"hypothesis":"large 更好","dimensions":{"model":["base","large"]},'
        '"metric_specs":{}}}',
        '{"v":1,"ts":"2026-08-24T09:05:00+08:00","type":"prediction","batch":"b1",'
        '"run":"model=large","payload":{"metrics":{"top1_acc":0.83},'
        '"rationale":"容量更大","confidence":"medium"}}',
        '{"v":1,"ts":"2026-08-24T12:00:00+08:00","type":"run_result","batch":"b1",'
        '"run":"model=large","payload":{"seed":0,"metrics":{"top1_acc":0.95},'
        '"source":{"path":"logs/large/s0/results.json","kind":"structured",'
        '"mtime":"2026-08-24T11:58:00+08:00"}}}',
    ]
    if second_run:
        lines += [
            '{"v":1,"ts":"2026-08-24T09:06:00+08:00","type":"prediction","batch":"b1",'
            '"run":"model=base","payload":{"metrics":{"top1_acc":0.80},'
            '"rationale":"基线","confidence":"high"}}',
            '{"v":1,"ts":"2026-08-24T12:01:00+08:00","type":"run_result","batch":"b1",'
            '"run":"model=base","payload":{"seed":0,"metrics":{"top1_acc":0.70},'
            '"source":{"path":"logs/base/s0/results.json","kind":"structured",'
            '"mtime":"2026-08-24T11:59:00+08:00"}}}',
        ]
    runs_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return project


def _confirmed_project(tmp_path):
    """全 CONFIRMED 的批次——没有待复盘项。"""
    project = tmp_path / "p"
    runner.invoke(cli.app, ["init", str(project)])
    runs_jsonl = project / "runs.jsonl"
    runs_jsonl.write_text(
        '{"v":1,"ts":"2026-08-24T09:00:00+08:00","type":"batch_opened","batch":"b1",'
        '"payload":{"hypothesis":"large 更好","dimensions":{"model":["base","large"]},'
        '"metric_specs":{}}}\n'
        '{"v":1,"ts":"2026-08-24T09:05:00+08:00","type":"prediction","batch":"b1",'
        '"run":"model=large","payload":{"metrics":{"top1_acc":0.83},'
        '"rationale":"容量更大","confidence":"medium"}}\n'
        '{"v":1,"ts":"2026-08-24T12:00:00+08:00","type":"run_result","batch":"b1",'
        '"run":"model=large","payload":{"seed":0,"metrics":{"top1_acc":0.831},'
        '"source":{"path":"logs/large/s0/results.json","kind":"structured",'
        '"mtime":"2026-08-24T11:58:00+08:00"}}}\n',
        encoding="utf-8",
    )
    return project


REFLECTION = "cause: 数据增强没关\nnext: 关掉重跑\n"
BATCH_REFLECTION = "cause: 整体学到了 lr 太大伤大模型\nnext: 下批扫 lr\n"


def test_review_writes_a_reflection_event_for_each_surprise(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path, second_run=True)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION, REFLECTION))

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    reflections = [e for e in events if e.type == "reflection"]
    assert {e.run for e in reflections} == {"model=large", "model=base"}
    for e in reflections:
        assert e.payload["scope"] == "run"
        assert e.payload["cause"] == "数据增强没关"
        assert e.batch == "b1"


def test_review_abandoning_one_run_skips_it_and_continues(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path, second_run=True)
    # 第一个 run 放弃（None），第二个写复盘
    monkeypatch.setattr(cli, "edit_text", FakeEditor(None, REFLECTION))

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    reflections = [e for e in events if e.type == "reflection"]
    assert [e.run for e in reflections] == ["model=base"]


def test_review_with_no_pending_gives_a_friendly_message(tmp_path, monkeypatch):
    project = _confirmed_project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor())  # 不应被调用

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    assert "待复盘" in result.output or "没有" in result.output
    events, _ = read_events(project / "runs.jsonl")
    assert not [e for e in events if e.type == "reflection"]


def test_review_invalid_cause_reopens_with_errors_and_keeps_content(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    # 第一次：占位符没改 → 校验失败重开；第二次：有效
    placeholder_draft = "cause: <为什么会这样？>\nnext: \n"
    editor = FakeEditor(placeholder_draft, REFLECTION)
    monkeypatch.setattr(cli, "edit_text", editor)

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    # 重开时带上了错误注释
    assert "cause" in editor.seen[1]
    events, _ = read_events(project / "runs.jsonl")
    reflections = [e for e in events if e.type == "reflection"]
    assert len(reflections) == 1
    assert reflections[0].payload["cause"] == "数据增强没关"


def test_review_batch_closure_after_all_surprises_done(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    # 复盘该 run，然后同意 batch 收口
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION, BATCH_REFLECTION))

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="y\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    reflections = [e for e in events if e.type == "reflection"]
    assert [e.payload["scope"] for e in reflections] == ["run", "batch"]
    assert reflections[1].run is None  # batch 级 reflection 不绑定 run


def test_review_declining_batch_closure_skips_it(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION))

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    reflections = [e for e in events if e.type == "reflection"]
    assert len(reflections) == 1
    assert reflections[0].payload["scope"] == "run"


def test_review_without_any_batch_is_a_friendly_error(tmp_path):
    project = tmp_path / "p"
    runner.invoke(cli.app, ["init", str(project)])

    result = runner.invoke(cli.app, ["review", "-p", str(project)])

    assert result.exit_code != 0
    assert "plan" in result.output


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
        cli,
        "edit_text",
        FakeEditor(REFLECTION, "cause: 整体结论\nbeliefs_added:\n  - 批次级信念\n"),
    )

    runner.invoke(cli.app, ["review", "-p", str(project)], input="y\n")

    events, _ = read_events(project / "runs.jsonl")
    added = [e for e in events if e.type == "belief_added"]
    assert [e.payload["text"] for e in added] == ["批次级信念"]
    assert added[0].run is None


# ── AI 的追问（spec §7 第 2 步） ──────────────────────────────────────

from ari.llm import LLMUnavailable

PROBE = {
    "questions": ["两组的数据增强配置一样吗？"],
    "hypotheses": ["和 b2 那次是同一个原因"],
}


def test_probe_appears_in_the_draft_as_comments(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    editor = FakeEditor(REFLECTION)
    monkeypatch.setattr(cli, "edit_text", editor)
    monkeypatch.setattr(cli, "probe", lambda *a, **k: PROBE)

    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    draft = editor.seen[0]
    assert "数据增强配置一样吗" in draft
    assert "同一个原因" in draft
    # 追问必须在注释区，否则会被 YAML 当成字段
    for line in draft.splitlines():
        if "数据增强配置一样吗" in line or "同一个原因" in line:
            assert line.lstrip().startswith("#")


def test_probe_does_not_add_an_extra_editor_round_trip(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    editor = FakeEditor(REFLECTION)
    monkeypatch.setattr(cli, "edit_text", editor)
    monkeypatch.setattr(cli, "probe", lambda *a, **k: PROBE)

    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert len(editor.seen) == 1  # 摩擦不许涨


def test_probe_is_archived_as_a_note(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION))
    monkeypatch.setattr(cli, "probe", lambda *a, **k: PROBE)

    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    events, _ = read_events(project / "runs.jsonl")
    notes = [e for e in events if e.type == "note"]
    assert len(notes) == 1
    assert notes[0].payload["kind"] == "ai_probe"
    assert notes[0].payload["probe"] == PROBE
    assert notes[0].run == "model=large"
    # 追问发生在写复盘之前
    types = [e.type for e in events]
    assert types.index("note") < types.index("reflection")


def test_review_degrades_to_plain_handwriting_without_llm(tmp_path, monkeypatch):
    """spec §8：LLM 不可用时 review 降级为无追问的纯手写模式。"""
    project = _surprise_project(tmp_path)
    editor = FakeEditor(REFLECTION)
    monkeypatch.setattr(cli, "edit_text", editor)

    def unavailable(*args, **kwargs):
        raise LLMUnavailable("没配 key")

    monkeypatch.setattr(cli, "probe", unavailable)
    result = runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    assert result.exit_code == 0
    assert "cause" in editor.seen[0]  # 草稿照常，只是少了追问那一段
    events, _ = read_events(project / "runs.jsonl")
    assert len([e for e in events if e.type == "reflection"]) == 1
    assert not [e for e in events if e.type == "note"]


def test_probe_text_is_not_parsed_into_the_reflection(tmp_path, monkeypatch):
    project = _surprise_project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION))
    monkeypatch.setattr(cli, "probe", lambda *a, **k: PROBE)

    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")

    events, _ = read_events(project / "runs.jsonl")
    reflection = [e for e in events if e.type == "reflection"][0]
    assert set(reflection.payload) == {"scope", "cause", "next"}
    assert "questions" not in str(reflection.payload)
