"""config.toml 的读取与角色解析。见 spec §6、§8。

配置缺失、角色没配、环境变量没设——三种情况都必须收敛成「LLM 不可用」
这一种结果，而不是三种不同的崩法。
"""

from __future__ import annotations

import pytest

from ari.config import ModelRef, load_config, resolve_role
from ari.llm import LLMUnavailable

CONFIG = """\
[providers.anthropic]
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"

[providers.openai]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[roles]
reason = "anthropic:claude-opus-5"
"""


def _write(tmp_path, text=CONFIG):
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_missing_config_is_unavailable_not_a_crash(tmp_path):
    with pytest.raises(LLMUnavailable):
        load_config(tmp_path)


def test_malformed_config_is_unavailable(tmp_path):
    with pytest.raises(LLMUnavailable):
        load_config(_write(tmp_path, "这不是 toml [[["))


def test_resolve_role_returns_provider_model_and_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = load_config(_write(tmp_path))

    ref = resolve_role(config, "reason")

    assert ref == ModelRef(
        provider="anthropic",
        model="claude-opus-5",
        base_url="https://api.anthropic.com",
        api_key="sk-test",
    )


def test_unconfigured_role_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = load_config(_write(tmp_path))

    with pytest.raises(LLMUnavailable) as exc:
        resolve_role(config, "extract")

    assert "extract" in str(exc.value)


def test_unset_api_key_env_names_the_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = load_config(_write(tmp_path))

    with pytest.raises(LLMUnavailable) as exc:
        resolve_role(config, "reason")

    assert "ANTHROPIC_API_KEY" in str(exc.value)  # 说清楚该设哪个变量


def test_placeholder_model_is_unavailable(tmp_path, monkeypatch):
    # 模板里发下去的是 <strong-model>，没改就用等于没配
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = load_config(
        _write(tmp_path, CONFIG.replace("claude-opus-5", "<strong-model>"))
    )

    with pytest.raises(LLMUnavailable):
        resolve_role(config, "reason")


def test_unknown_provider_is_unavailable(tmp_path):
    config = load_config(
        _write(tmp_path, CONFIG.replace("anthropic:claude-opus-5", "grok:whatever"))
    )

    with pytest.raises(LLMUnavailable) as exc:
        resolve_role(config, "reason")

    assert "grok" in str(exc.value)


def test_role_without_a_colon_is_unavailable(tmp_path):
    config = load_config(_write(tmp_path, CONFIG.replace("anthropic:claude-opus-5", "claude")))

    with pytest.raises(LLMUnavailable):
        resolve_role(config, "reason")


def test_provider_without_api_key_env_is_unavailable(tmp_path):
    config = load_config(
        _write(tmp_path, CONFIG.replace('api_key_env = "ANTHROPIC_API_KEY"', ""))
    )

    with pytest.raises(LLMUnavailable):
        resolve_role(config, "reason")
