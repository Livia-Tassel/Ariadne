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
    from ari import credentials

    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "empty.toml")
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
    from ari import credentials

    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "empty.toml")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = load_config(_write(tmp_path))

    with pytest.raises(LLMUnavailable) as exc:
        resolve_role(config, "reason")

    assert "ANTHROPIC_API_KEY" in str(exc.value)  # 说清楚该设哪个变量


def test_placeholder_model_is_unavailable(tmp_path, monkeypatch):
    from ari import credentials

    # 模板里发下去的是 <strong-model>，没改就用等于没配
    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "empty.toml")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    config = load_config(
        _write(tmp_path, CONFIG.replace("claude-opus-5", "<strong-model>"))
    )

    with pytest.raises(LLMUnavailable):
        resolve_role(config, "reason")


def test_unknown_provider_is_unavailable(tmp_path, monkeypatch):
    from ari import credentials

    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "empty.toml")
    config = load_config(
        _write(tmp_path, CONFIG.replace("anthropic:claude-opus-5", "grok:whatever"))
    )

    with pytest.raises(LLMUnavailable) as exc:
        resolve_role(config, "reason")

    assert "grok" in str(exc.value)


def test_role_without_a_colon_is_unavailable(tmp_path, monkeypatch):
    from ari import credentials

    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "empty.toml")
    config = load_config(_write(tmp_path, CONFIG.replace("anthropic:claude-opus-5", "claude")))

    with pytest.raises(LLMUnavailable):
        resolve_role(config, "reason")


def test_provider_without_api_key_env_is_unavailable(tmp_path, monkeypatch):
    from ari import credentials

    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "empty.toml")
    config = load_config(
        _write(tmp_path, CONFIG.replace('api_key_env = "ANTHROPIC_API_KEY"', ""))
    )

    with pytest.raises(LLMUnavailable):
        resolve_role(config, "reason")


def test_resolve_role_falls_back_to_the_stored_credential(tmp_path, monkeypatch):
    """没设环境变量时用应用数据目录里存的那份——密钥不该被迫写进
    config.toml，那个文件是要进 git 的。"""
    from ari import credentials
    from ari.config import resolve_role

    store = tmp_path / "credentials.toml"
    credentials.save(secrets={"ANTHROPIC_API_KEY": "sk-stored"}, path=store)
    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: store)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    ref = resolve_role(
        {
            "roles": {"reason": "anthropic:claude-opus-5"},
            "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
        },
        "reason",
    )

    assert ref.api_key == "sk-stored"


def test_a_missing_key_still_reports_the_environment_variable_name(tmp_path, monkeypatch):
    """报错要说清该去设哪个环境变量，而不是笼统一句「没配」。"""
    from ari import credentials
    from ari.config import resolve_role
    from ari.llm import LLMUnavailable

    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: tmp_path / "none.toml")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMUnavailable, match="ANTHROPIC_API_KEY"):
        resolve_role(
            {
                "roles": {"reason": "anthropic:x"},
                "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
            },
            "reason",
        )


@pytest.fixture
def user_store(tmp_path, monkeypatch):
    """把用户级设置指到临时文件，别碰开发机上真实的那份。"""
    from ari import credentials

    store = tmp_path / "credentials.toml"
    monkeypatch.setattr(credentials, "credentials_path", lambda path=None: store)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    credentials.save(secrets={"ANTHROPIC_API_KEY": "sk-x"}, path=store)
    return store


def test_base_url_falls_back_to_the_user_level_setting(user_store):
    """第三方 endpoint 是用户级的事：你用中转，所有项目都用中转。
    不该每开一个项目就去手改一次 config.toml。"""
    from ari import credentials
    from ari.config import resolve_role

    credentials.save(settings={"anthropic_base_url": "https://relay.example/v1"}, path=user_store)

    ref = resolve_role(
        {"roles": {"reason": "anthropic:claude-opus-5"}, "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}}},
        "reason",
    )

    assert ref.base_url == "https://relay.example/v1"


def test_the_user_level_base_url_overrides_the_project_config(user_store):
    """GUI 里的模型与地址必须是同一层覆盖，不能拼出跨平台的错误组合。"""
    from ari import credentials
    from ari.config import resolve_role

    credentials.save(settings={"anthropic_base_url": "https://relay.example/v1"}, path=user_store)

    ref = resolve_role(
        {
            "roles": {"reason": "anthropic:claude-opus-5"},
            "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY", "base_url": "https://in-project/v1"}},
        },
        "reason",
    )

    assert ref.base_url == "https://relay.example/v1"


def test_user_model_and_url_override_project_as_one_configuration(user_store):
    """回归：OrcaRouter 模型名不能被发到项目遗留的 DeepSeek 地址。"""
    from ari import credentials
    from ari.config import resolve_role

    credentials.save(
        settings={
            "reason_model": "openai:deepseek/deepseek-v4-flash-free",
            "openai_base_url": "https://api.orcarouter.ai/v1",
        },
        path=user_store,
    )
    credentials.save(secrets={"OPENAI_API_KEY": "sk-o"}, path=user_store)

    ref = resolve_role(
        {
            "roles": {"reason": "openai:deepseek-v4-pro"},
            "providers": {
                "openai": {
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://api.deepseek.com",
                }
            },
        },
        "reason",
    )

    assert (ref.model, ref.base_url) == (
        "deepseek/deepseek-v4-flash-free",
        "https://api.orcarouter.ai/v1",
    )


def test_the_role_itself_can_come_from_the_user_level_setting(user_store):
    """中转站往往要配一个不同的模型名。config.toml 里没写 [roles] 时用这份。"""
    from ari import credentials
    from ari.config import resolve_role

    credentials.save(
        settings={"reason_model": "openai:deepseek-v4-pro", "openai_base_url": "https://relay/v1"},
        path=user_store,
    )
    credentials.save(secrets={"OPENAI_API_KEY": "sk-o"}, path=user_store)

    ref = resolve_role({"providers": {"openai": {"api_key_env": "OPENAI_API_KEY"}}}, "reason")

    assert (ref.provider, ref.model, ref.base_url) == (
        "openai",
        "deepseek-v4-pro",
        "https://relay/v1",
    )


def test_a_provider_with_no_api_key_env_configured_still_finds_the_default(user_store):
    """config.toml 里没有 [providers] 段时也该能用——环境变量名是可推断的。"""
    from ari.config import resolve_role

    ref = resolve_role({"roles": {"reason": "anthropic:claude-opus-5"}}, "reason")

    assert ref.api_key == "sk-x"
