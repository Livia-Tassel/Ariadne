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

DESIGN_NO_TEMPLATE = """
hypothesis: large 比 base 好
dimensions:
  model: [base, large]
metrics:
  top1_acc:
"""

PREDICTIONS = """
runs:
  - run: model=base
    top1_acc: [0.78, 0.81]
    confidence: high
    rationale: 基线
  - run: model=large
    top1_acc: [0.82, 0.85]
    confidence: medium
    rationale: 容量翻倍
"""

MANUAL = """
results:
  - run: model=base
    seed: 0
    top1_acc: 0.796
  - run: model=large
    seed: 0
    top1_acc: 0.883
"""


class FakeEditor:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def __call__(self, initial, name="draft", suffix=".yaml"):
        self.seen.append(initial)
        return self.responses.pop(0) if self.responses else None


def _planned(tmp_path, monkeypatch, design=DESIGN):
    project = tmp_path / "p"
    runner.invoke(cli.app, ["init", str(project)])
    monkeypatch.setattr(cli, "edit_text", FakeEditor(design, PREDICTIONS))
    runner.invoke(cli.app, ["plan", "-p", str(project)])
    return project


def _write_result(project, relative, payload):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_result_ingests_discovered_files_after_confirmation(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)
    _write_result(project, "logs/base/s0/results.json", {"top1_acc": 0.796})
    _write_result(project, "logs/large/s0/results.json", {"top1_acc": 0.883})

    result = runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    results = [e for e in events if e.type == "run_result"]
    assert {e.run for e in results} == {"model=base", "model=large"}
    assert results[0].payload["source"]["kind"] == "structured"
    assert results[0].payload["source"]["mtime"]


def test_declining_the_confirmation_writes_nothing(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)
    _write_result(project, "logs/base/s0/results.json", {"top1_acc": 0.796})

    runner.invoke(cli.app, ["result", "-p", str(project)], input="n\n")

    events, _ = read_events(project / "runs.jsonl")
    assert not [e for e in events if e.type == "run_result"]


def test_multiple_seeds_become_multiple_events(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)
    _write_result(project, "logs/base/s0/results.json", {"top1_acc": 0.731})
    _write_result(project, "logs/base/s1/results.json", {"top1_acc": 0.779})

    runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")

    events, _ = read_events(project / "runs.jsonl")
    seeds = [e.payload["seed"] for e in events if e.type == "run_result"]
    assert sorted(seeds) == [0, 1]


def test_files_matching_the_shape_but_no_run_are_reported(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)
    _write_result(project, "logs/huge/s0/results.json", {"top1_acc": 0.9})

    result = runner.invoke(cli.app, ["result", "-p", str(project)], input="n\n")

    assert "huge" in result.output


def test_missing_metric_is_reported_in_the_confirmation(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)
    _write_result(project, "logs/base/s0/results.json", {"other_metric": 1.0})

    result = runner.invoke(cli.app, ["result", "-p", str(project)], input="n\n")

    assert "top1_acc" in result.output


def test_manual_mode_when_the_batch_has_no_template(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch, design=DESIGN_NO_TEMPLATE)
    monkeypatch.setattr(cli, "edit_text", FakeEditor(MANUAL))

    result = runner.invoke(cli.app, ["result", "-p", str(project)], input="y\n")

    assert result.exit_code == 0
    events, _ = read_events(project / "runs.jsonl")
    results = [e for e in events if e.type == "run_result"]
    assert {e.run for e in results} == {"model=base", "model=large"}
    assert results[0].payload["source"]["kind"] == "manual"


def test_manual_flag_forces_manual_mode_even_with_a_template(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)
    _write_result(project, "logs/base/s0/results.json", {"top1_acc": 0.796})
    editor = FakeEditor(MANUAL)
    monkeypatch.setattr(cli, "edit_text", editor)

    runner.invoke(cli.app, ["result", "-p", str(project), "--manual"], input="y\n")

    assert editor.seen  # 走的是编辑器而不是自动发现
    events, _ = read_events(project / "runs.jsonl")
    assert [e for e in events if e.type == "run_result"][0].payload["source"]["kind"] == "manual"


def test_no_files_found_says_so_instead_of_silently_doing_nothing(tmp_path, monkeypatch):
    project = _planned(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["result", "-p", str(project)])

    assert result.exit_code == 0
    assert "没找到" in result.output


def test_result_without_any_batch_is_a_friendly_error(tmp_path):
    project = tmp_path / "p"
    runner.invoke(cli.app, ["init", str(project)])

    result = runner.invoke(cli.app, ["result", "-p", str(project)])

    assert "ari plan" in result.output
