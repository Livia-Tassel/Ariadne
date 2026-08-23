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
