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
