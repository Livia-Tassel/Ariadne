"""端到端全闭环。见 plan 第二阶段 Task 10。

把 init → plan → result → review → board 串起来跑一遍，全程不手写一行
JSON——编辑器全部 monkeypatch。校验的是整条链路的事件流动，以及看板上
SURPRISE 从「置顶待复盘」到「复盘后消失、批次收口」的转变。
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from ari import cli

runner = CliRunner()

DESIGN = """
hypothesis: large 比 base 好
dimensions:
  model: [base, large]
metrics:
  top1_acc:
result_path: "logs/{model}/s{seed}/results.json"
"""

# large 预测 0.83，base 预测 [0.78, 0.81]。
PREDICTIONS = """
runs:
  - run: model=large
    top1_acc: 0.83
    confidence: medium
    rationale: 容量翻倍但数据量没变
  - run: model=base
    top1_acc: [0.78, 0.81]
    confidence: high
    rationale: 跑过很多次的基线
"""

REFLECTION = "cause: 数据增强没关\nnext: 关掉重跑\n"
BATCH_REFLECTION = "cause: large 没涨是增强没关，非容量问题\nnext: 下批固定增强\n"


class FakeEditor:
    def __init__(self, *responses):
        self.responses = list(responses)

    def __call__(self, initial, name="draft", suffix=".yaml"):
        return self.responses.pop(0) if self.responses else None


def _write_result(project, run, value):
    path = project / "logs" / run / "s0" / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"top1_acc": value}), encoding="utf-8")
    return path


def test_full_loop_plans_results_reviews_and_closes(tmp_path, monkeypatch):
    project = tmp_path / "exp"

    # 1. init
    assert runner.invoke(cli.app, ["init", str(project)]).exit_code == 0

    # 2. plan —— 编辑器依次吐设计草稿与预测表
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    assert runner.invoke(cli.app, ["plan", "-p", str(project)]).exit_code == 0

    # 3. result —— large 实测 0.95（SURPRISE），base 实测 0.801（CONFIRMED）
    _write_result(project, "large", 0.95)
    _write_result(project, "base", 0.801)
    monkeypatch.setattr(cli, "edit_text", FakeEditor())  # 自动发现，不开编辑器
    assert runner.invoke(
        cli.app, ["result", "-p", str(project)], input="y\n"
    ).exit_code == 0

    # 4. board —— SURPRISE 置顶待复盘
    assert runner.invoke(cli.app, ["board", "-p", str(project)]).exit_code == 0
    board_before = (project / "board.md").read_text(encoding="utf-8")
    assert "待复盘" in board_before
    assert "model=large" in board_before

    # 5. review —— 复盘 large，再同意 batch 收口
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION, BATCH_REFLECTION))
    assert runner.invoke(
        cli.app, ["review", "-p", str(project)], input="y\n"
    ).exit_code == 0

    # 6. board —— 复盘后待复盘消失，批次已收口
    runner.invoke(cli.app, ["board", "-p", str(project)])
    board_after = (project / "board.md").read_text(encoding="utf-8")
    assert "待复盘" not in board_after
    assert "已收口" in board_after


def test_full_loop_writes_events_in_the_right_order(tmp_path, monkeypatch):
    from ari.events import read_events

    project = tmp_path / "exp"
    runner.invoke(cli.app, ["init", str(project)])
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    runner.invoke(cli.app, ["plan", "-p", str(project)])
    _write_result(project, "large", 0.95)
    _write_result(project, "base", 0.801)
    monkeypatch.setattr(cli, "edit_text", FakeEditor())
    runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")
    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION, BATCH_REFLECTION))
    runner.invoke(cli.app, ["review", "-p", str(project)], input="y\n")

    events, errors = read_events(project / "runs.jsonl")
    assert errors == []
    types = [e.type for e in events]
    # batch_opened → 2 条 prediction → 2 条 run_result → run 反思 → batch 收口
    assert types == [
        "batch_opened",
        "prediction",
        "prediction",
        "run_result",
        "run_result",
        "reflection",
        "reflection",
    ]
    run_level = events[-2]
    batch_level = events[-1]
    assert run_level.run == "model=large"
    assert run_level.payload["scope"] == "run"
    assert batch_level.run is None
    assert batch_level.payload["scope"] == "batch"


def _loop_until_review(project, monkeypatch, reflection):
    """跑到 review 为止：init → plan → result → review。"""
    runner.invoke(cli.app, ["init", str(project)])
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    runner.invoke(cli.app, ["plan", "-p", str(project)])
    _write_result(project, "large", 0.95)
    _write_result(project, "base", 0.801)
    monkeypatch.setattr(cli, "edit_text", FakeEditor())
    runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")
    monkeypatch.setattr(cli, "edit_text", FakeEditor(reflection))
    runner.invoke(cli.app, ["review", "-p", str(project)], input="n\n")


def test_belief_survives_the_loop_and_can_be_refuted_later(tmp_path, monkeypatch):
    from ari.beliefs import make_belief_id

    project = tmp_path / "exp"

    # 第一轮：跑出 SURPRISE，复盘时写下一条信念
    _loop_until_review(
        project, monkeypatch, "cause: 增强没关\nbeliefs_added:\n  - 增强对小数据集有害\n"
    )
    runner.invoke(cli.app, ["board", "-p", str(project)])

    beliefs = (project / "beliefs.md").read_text(encoding="utf-8")
    assert "增强对小数据集有害" in beliefs
    assert "在册" in beliefs

    # 第二轮：同一条信念被后来的复盘推翻
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
    _loop_until_review(
        project, monkeypatch, "cause: 增强没关\nbeliefs_added:\n  - 一条信念\n"
    )
    runner.invoke(cli.app, ["board", "-p", str(project)])
    first = (project / "beliefs.md").read_text(encoding="utf-8")

    (project / "beliefs.md").unlink()
    runner.invoke(cli.app, ["board", "-p", str(project)])

    assert (project / "beliefs.md").read_text(encoding="utf-8") == first
