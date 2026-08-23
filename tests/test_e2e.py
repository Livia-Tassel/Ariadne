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
