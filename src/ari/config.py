"""config.toml 的读取与角色解析。见 spec §6。

配置文件会进 git，所以里面只有平台地址与**环境变量名**，密钥的值永远
从环境读。

所有「配不全」的情况——文件不存在、TOML 坏了、角色没配、环境变量没设、
provider 不认识——都收敛成同一个 LLMUnavailable。调用方只需要处理一种
失败，spec §8 要求的离线降级才可能写得干净。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .credentials import load_settings, secret_for
from .llm import LLMUnavailable

KNOWN_PROVIDERS = ("anthropic", "openai")
_DEFAULT_API_KEY_ENVS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str
    base_url: str | None
    api_key: str


def load_config(project_dir) -> dict:
    path = Path(project_dir) / "config.toml"
    if not path.exists():
        raise LLMUnavailable(f"没有 {path}，跳过 AI 那一段")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise LLMUnavailable(f"{path} 读不了：{exc}") from exc


def resolve_role(config: dict, role: str) -> ModelRef:
    """把 [roles] 里的 "provider:model" 解析成一次调用需要的全部信息。

    支持从用户级 credentials.toml 的 [settings] 段读取：
    - {role}_model: 角色对应的 "provider:model"，用户配置优先（一次设置全局生效）
    - {provider}_base_url: 第三方中转地址，用户配置优先（与模型保持同一优先级）
    """
    user_settings = load_settings()

    # 角色解析：用户级设置优先，其次才是项目 config.toml
    # 用户在 GUI 设置的模型应该对所有项目生效
    spec = user_settings.get(f"{role}_model")
    if not spec:
        spec = (config.get("roles") or {}).get(role)

    if not isinstance(spec, str) or ":" not in spec:
        raise LLMUnavailable(
            f'config.toml 的 [roles] 里没有配 {role}'
            f'（形如 {role} = "anthropic:claude-opus-5"）'
        )

    provider, _, model = spec.partition(":")
    provider, model = provider.strip(), model.strip()

    if provider not in KNOWN_PROVIDERS:
        raise LLMUnavailable(
            f"不认识的 provider {provider!r}，目前支持 {'、'.join(KNOWN_PROVIDERS)}"
        )
    if not model or model.startswith("<"):
        raise LLMUnavailable(f"[roles] 的 {role} 还是模板占位符，填一个真实的模型名")

    # API key：项目 config 声明环境变量名，fallback 到默认的环境变量名
    settings = (config.get("providers") or {}).get(provider) or {}
    key_env = settings.get("api_key_env") or _DEFAULT_API_KEY_ENVS.get(provider, "")
    # 环境变量优先，其次是应用数据目录里存的那份。密钥不该被迫写进
    # config.toml——那个文件是要进 git 的。见 credentials.py。
    api_key = secret_for(key_env) if key_env else None
    if not api_key:
        raise LLMUnavailable(
            f"环境变量 {key_env} 没有设置" if key_env
            else f"config.toml 的 [providers.{provider}] 没有声明 api_key_env"
        )

    # base_url 必须和 GUI 里选的模型保持同一优先级。旧逻辑是「用户模型优先，
    # 项目 URL 优先」，会把 OrcaRouter 的模型名发到 DeepSeek 官方地址之类的
    # 错误组合。用户在设置页填写了地址，就把它视为当前 provider 的全局覆盖；
    # 清空后才回到项目 config.toml。
    base_url = user_settings.get(f"{provider}_base_url")
    if not base_url:
        base_url = settings.get("base_url")

    return ModelRef(
        provider=provider,
        model=model,
        base_url=base_url or None,
        api_key=api_key,
    )
