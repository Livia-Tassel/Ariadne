"""LLM 层的离线降级。见 spec §8。

这个文件只验证一件事，但它是整个 LLM 层的验收条件：**没有 LLM 时，
闭环的行为和没有 LLM 层的时候一模一样。**

不是「大致能跑」，而是事件流逐条相同、退出码全是 0、不需要任何 flag。
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from ari import cli
from ari.events import read_events

runner = CliRunner()

DESIGN = """
hypothesis: large 比 base 好
dimensions:
  model: [base, large]
metrics:
  top1_acc:
result_path: "logs/{model}/s{seed}/results.json"
"""

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
BATCH_REFLECTION = "cause: 整体是增强的问题\nnext: 下批固定增强\n"


class FakeEditor:
    def __init__(self, *responses):
        self.responses = list(responses)

    def __call__(self, initial, name="draft", suffix=".yaml"):
        return self.responses.pop(0) if self.responses else None


def _full_loop(project, monkeypatch, drop_config=False) -> list[str]:
    """跑完整条闭环，返回事件类型序列。每一步都断言退出码为 0。"""
    assert runner.invoke(cli.app, ["init", str(project)]).exit_code == 0
    if drop_config:
        (project / "config.toml").unlink()

    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    assert runner.invoke(cli.app, ["plan", "-p", str(project)]).exit_code == 0

    for run, value in (("large", 0.95), ("base", 0.801)):
        path = project / "logs" / run / "s0" / "results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"top1_acc": value}), encoding="utf-8")

    monkeypatch.setattr(cli, "edit_text", FakeEditor())
    assert runner.invoke(
        cli.app, ["result", "-p", str(project)], input="y\n"
    ).exit_code == 0

    monkeypatch.setattr(cli, "edit_text", FakeEditor(REFLECTION, BATCH_REFLECTION))
    assert runner.invoke(
        cli.app, ["review", "-p", str(project)], input="y\n"
    ).exit_code == 0

    assert runner.invoke(cli.app, ["board", "-p", str(project)]).exit_code == 0

    events, errors = read_events(project / "runs.jsonl")
    assert errors == []
    return [e.type for e in events]


EXPECTED = [
    "batch_opened",
    "prediction",
    "prediction",
    "run_result",
    "run_result",
    "reflection",
    "reflection",
]


def test_the_whole_loop_runs_with_no_config_at_all(tmp_path, monkeypatch):
    assert _full_loop(tmp_path / "exp", monkeypatch, drop_config=True) == EXPECTED


def test_config_present_but_no_api_key_behaves_identically(tmp_path, monkeypatch):
    # conftest 已经把 API key 环境变量摘掉了，这里就是「配了模板但没设 key」
    assert _full_loop(tmp_path / "exp", monkeypatch) == EXPECTED


def test_a_provider_that_refuses_to_connect_behaves_identically(tmp_path, monkeypatch):
    """配全了、key 也有，但 provider 连不上——照样一切正常。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")

    def refuse(*args, **kwargs):
        from ari.llm import LLMUnavailable

        raise LLMUnavailable("连不上 anthropic：Connection refused")

    monkeypatch.setattr(cli, "advise", refuse)
    monkeypatch.setattr(cli, "probe", refuse)

    assert _full_loop(tmp_path / "exp", monkeypatch) == EXPECTED


def test_board_never_touches_the_llm(tmp_path, monkeypatch):
    """看板是纯派生产物。任何 LLM 调用都会让它变得不可复现。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")

    def explode(*args, **kwargs):
        raise AssertionError("board 不该碰 LLM")

    monkeypatch.setattr(cli, "advise", explode)
    monkeypatch.setattr(cli, "probe", explode)

    project = tmp_path / "exp"
    monkeypatch.setattr(cli, "edit_text", FakeEditor())
    runner.invoke(cli.app, ["init", str(project)])

    assert runner.invoke(cli.app, ["board", "-p", str(project)]).exit_code == 0
