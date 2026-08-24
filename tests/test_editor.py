import pytest

from ari import editor


def _fake_run(replacement):
    """伪造编辑器：把用户「编辑」后的内容写进临时文件。"""

    def run(argv, check=True):
        from pathlib import Path

        Path(argv[-1]).write_text(replacement, encoding="utf-8")

    return run


def test_returns_the_edited_text(monkeypatch):
    monkeypatch.setenv("EDITOR", "fake-editor")
    monkeypatch.setattr(editor.subprocess, "run", _fake_run("改过了\n"))

    assert editor.edit_text("原文") == "改过了\n"


def test_returns_none_when_unchanged(monkeypatch):
    monkeypatch.setenv("EDITOR", "fake-editor")
    monkeypatch.setattr(editor.subprocess, "run", _fake_run("原文"))

    assert editor.edit_text("原文") is None


def test_returns_none_when_emptied(monkeypatch):
    monkeypatch.setenv("EDITOR", "fake-editor")
    monkeypatch.setattr(editor.subprocess, "run", _fake_run("   \n\n"))

    assert editor.edit_text("原文") is None


def test_temp_file_is_named_for_the_user(monkeypatch):
    seen = {}

    def run(argv, check=True):
        from pathlib import Path

        seen["path"] = argv[-1]
        Path(argv[-1]).write_text("改过了", encoding="utf-8")

    monkeypatch.setenv("EDITOR", "fake-editor")
    monkeypatch.setattr(editor.subprocess, "run", run)

    editor.edit_text("原文", name="plan-b1")

    assert seen["path"].endswith("plan-b1.yaml")


def test_editor_with_arguments_is_supported(monkeypatch):
    seen = {}

    def run(argv, check=True):
        from pathlib import Path

        seen["argv"] = argv
        Path(argv[-1]).write_text("改过了", encoding="utf-8")

    monkeypatch.setenv("EDITOR", "code --wait")
    monkeypatch.setattr(editor.subprocess, "run", run)

    editor.edit_text("原文")

    assert seen["argv"][:2] == ["code", "--wait"]


def test_visual_takes_precedence_over_editor(monkeypatch):
    seen = {}

    def run(argv, check=True):
        from pathlib import Path

        seen["argv"] = argv
        Path(argv[-1]).write_text("改过了", encoding="utf-8")

    monkeypatch.setenv("EDITOR", "vi")
    monkeypatch.setenv("VISUAL", "mate")
    monkeypatch.setattr(editor.subprocess, "run", run)

    editor.edit_text("原文")

    assert seen["argv"][0] == "mate"


def test_missing_editor_binary_raises_a_readable_error(monkeypatch):
    def boom(argv, check=True):
        raise FileNotFoundError(argv[0])

    monkeypatch.setenv("EDITOR", "nope-not-installed")
    monkeypatch.setattr(editor.subprocess, "run", boom)

    with pytest.raises(editor.EditorUnavailable) as exc:
        editor.edit_text("原文")

    assert "EDITOR" in str(exc.value)


def test_no_temp_file_is_left_behind(monkeypatch):
    from pathlib import Path

    seen = {}

    def run(argv, check=True):
        seen["path"] = Path(argv[-1])
        seen["path"].write_text("改过了", encoding="utf-8")

    monkeypatch.setenv("EDITOR", "fake-editor")
    monkeypatch.setattr(editor.subprocess, "run", run)

    editor.edit_text("原文")

    assert not seen["path"].exists()
