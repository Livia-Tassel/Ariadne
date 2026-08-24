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
