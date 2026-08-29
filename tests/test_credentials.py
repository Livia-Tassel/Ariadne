"""密钥存取。密钥永远不进项目目录——config.toml 会进 git。"""

from __future__ import annotations

import stat
import sys

import pytest

from ari.credentials import (
    application_data_dir,
    load_secrets,
    load_settings,
    mask,
    save,
    secret_for,
)


@pytest.fixture
def store(tmp_path):
    return tmp_path / "credentials.toml"


def test_saving_and_reading_a_secret(store):
    save(secrets={"ANTHROPIC_API_KEY": "sk-test-123"}, path=store)

    assert load_secrets(store) == {"ANTHROPIC_API_KEY": "sk-test-123"}


def test_the_file_is_not_readable_by_other_users(store):
    """里面是明文密钥，同机其他用户不该读得到。"""
    save(secrets={"ANTHROPIC_API_KEY": "sk-test"}, path=store)

    mode = stat.S_IMODE(store.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_environment_wins_over_the_stored_value(monkeypatch, store):
    """环境变量是 CI 与自动化的显式路径，不该被 GUI 里填的东西盖掉。"""
    save(secrets={"ANTHROPIC_API_KEY": "sk-from-file"}, path=store)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")

    assert secret_for("ANTHROPIC_API_KEY", store) == "sk-from-env"


def test_stored_value_is_used_when_the_environment_is_empty(store):
    save(secrets={"ANTHROPIC_API_KEY": "sk-from-file"}, path=store)

    assert secret_for("ANTHROPIC_API_KEY", store) == "sk-from-file"


def test_saving_merges_instead_of_replacing(store):
    save(secrets={"ANTHROPIC_API_KEY": "a"}, path=store)
    save(secrets={"OPENAI_API_KEY": "b"}, path=store)

    assert load_secrets(store) == {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "b"}


def test_an_empty_value_deletes_the_entry(store):
    save(secrets={"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "b"}, path=store)

    save(secrets={"ANTHROPIC_API_KEY": ""}, path=store)

    assert load_secrets(store) == {"OPENAI_API_KEY": "b"}


def test_settings_live_alongside_secrets_but_separately(store):
    save(secrets={"ANTHROPIC_API_KEY": "a"}, settings={"openalex_mailto": "me@lab.edu"}, path=store)

    assert load_settings(store) == {"openalex_mailto": "me@lab.edu"}
    assert "openalex_mailto" not in load_secrets(store)


def test_values_with_quotes_and_backslashes_survive_a_round_trip(store):
    nasty = 'sk-a"b\\c'
    save(secrets={"WEIRD_KEY": nasty}, path=store)

    assert load_secrets(store)["WEIRD_KEY"] == nasty


def test_a_missing_or_broken_file_reads_as_empty(tmp_path):
    """密钥缺失是常态，不该让整个应用起不来。"""
    assert load_secrets(tmp_path / "nope.toml") == {}

    broken = tmp_path / "broken.toml"
    broken.write_text("这不是 toml [[[", encoding="utf-8")
    assert load_secrets(broken) == {}
    assert load_settings(broken) == {}


def test_mask_never_reveals_the_whole_key():
    assert mask("sk-ant-api03-abcdefgh1234") == "sk-…1234"
    assert mask("short") == "………"
    assert mask("") == ""


@pytest.mark.skipif(sys.platform != "darwin", reason="路径按操作系统习惯，只在 macOS 上断言")
def test_data_dir_follows_macos_convention():
    assert application_data_dir().as_posix().endswith("Library/Application Support/Ariadne")
