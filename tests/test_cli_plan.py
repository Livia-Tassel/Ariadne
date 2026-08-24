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
  - run: model=base
    top1_acc: [0.78, 0.81]
    confidence: high
    rationale: 跑过很多次的基线
  - run: model=large
    top1_acc: [0.82, 0.85]
    confidence: medium
    rationale: 容量翻倍但数据量没变
"""


class FakeEditor:
    """按顺序吐出预置文本，并记录每次收到的初始内容。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def __call__(self, initial, name="draft", suffix=".yaml"):
        self.seen.append(initial)
        return self.responses.pop(0) if self.responses else None


def _project(tmp_path):
    runner.invoke(cli.app, ["init", str(tmp_path / "p")])
    return tmp_path / "p"


def test_plan_writes_batch_opened_and_one_prediction_per_run(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))

    result = runner.invoke(cli.app, ["plan", "-p", str(project)])

    assert result.exit_code == 0
    events, errors = read_events(project / "runs.jsonl")
    assert errors == []
    assert [e.type for e in events] == ["batch_opened", "prediction", "prediction"]
    assert events[0].batch == "b1"
    assert {e.run for e in events[1:]} == {"model=base", "model=large"}


def test_second_plan_opens_b2(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))
    runner.invoke(cli.app, ["plan", "-p", str(project)])
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))

    runner.invoke(cli.app, ["plan", "-p", str(project)])

    events, _ = read_events(project / "runs.jsonl")
    assert {e.batch for e in events} == {"b1", "b2"}


def test_abandoning_the_first_editor_writes_nothing(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(None))

    result = runner.invoke(cli.app, ["plan", "-p", str(project)])

    assert result.exit_code == 0
    assert (project / "runs.jsonl").read_text(encoding="utf-8") == ""


def test_abandoning_the_prediction_table_writes_nothing(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, None))

    runner.invoke(cli.app, ["plan", "-p", str(project)])

    assert (project / "runs.jsonl").read_text(encoding="utf-8") == ""


def test_invalid_design_reopens_with_errors_and_keeps_user_content(tmp_path, monkeypatch):
    project = _project(tmp_path)
    broken = DESIGN.replace("hypothesis: large 比 base 好", "hypothesis: ''")
    editor = FakeEditor(broken, DESIGN, PREDICTIONS)
    monkeypatch.setattr(cli, "edit_text", editor)

    result = runner.invoke(cli.app, ["plan", "-p", str(project)])

    assert result.exit_code == 0
    # 第二次打开的内容里既有错误提示，也原封不动带着用户填的东西
    reopened = editor.seen[1]
    assert "hypothesis" in reopened
    assert "dimensions:" in reopened
    assert "model: [base, large]" in reopened


def test_invalid_predictions_reopen_with_errors_and_keep_user_content(tmp_path, monkeypatch):
    project = _project(tmp_path)
    broken = PREDICTIONS.replace("    rationale: 跑过很多次的基线\n", "    rationale:\n")
    editor = FakeEditor(DESIGN, broken, PREDICTIONS)
    monkeypatch.setattr(cli, "edit_text", editor)

    runner.invoke(cli.app, ["plan", "-p", str(project)])

    reopened = editor.seen[2]
    assert "rationale" in reopened
    assert "容量翻倍但数据量没变" in reopened  # 另一个 run 填好的内容没丢


def test_dims_option_presets_the_design_draft(tmp_path, monkeypatch):
    project = _project(tmp_path)
    editor = FakeEditor(DESIGN, PREDICTIONS)
    monkeypatch.setattr(cli, "edit_text", editor)

    runner.invoke(cli.app, ["plan", "-p", str(project), "--dims", "model=base,large"])

    # --dims 只负责把维度预填进草稿；最终以用户保存的内容为准，
    # 所以用户仍然可以在编辑器里改掉它。
    assert "model: [base, large]" in editor.seen[0]
    events, _ = read_events(project / "runs.jsonl")
    assert {e.run for e in events if e.run} == {"model=base", "model=large"}


def test_dims_option_rejects_a_malformed_spec(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(DESIGN, PREDICTIONS))

    result = runner.invoke(cli.app, ["plan", "-p", str(project), "--dims", "model"])

    assert result.exit_code != 0
