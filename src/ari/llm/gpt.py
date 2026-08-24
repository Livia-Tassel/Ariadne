"""OpenAI 适配器。

用 chat.completions 而不是更新的 Responses API：config.toml 明确暴露了
base_url，科研环境里指向 vLLM 之类 OpenAI 兼容的自建服务是常态，而这些
服务几乎都实现 /chat/completions、极少实现 /responses。兼容性在这里
比跟进新接口重要。

request() 是唯一碰网络的函数，测试不调它。
"""

from __future__ import annotations

from . import LLMUnavailable


def request(ref, system: str, user: str, schema: dict) -> str:
    # 延迟导入，理由同 claude.py
    try:
        import openai
    except ImportError as exc:
        raise LLMUnavailable("没有安装 openai SDK（跑一次 uv sync）") from exc

    client = openai.OpenAI(api_key=ref.api_key, base_url=ref.base_url)
    try:
        response = client.chat.completions.create(
            model=ref.model,
            messages=[
                {"role": "developer", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "ari_output", "strict": True, "schema": schema},
            },
        )
    except openai.APIConnectionError as exc:
        raise LLMUnavailable(f"连不上 {ref.provider}：{exc}") from exc
    except openai.AuthenticationError as exc:
        raise LLMUnavailable(f"{ref.provider} 认证失败，检查 API key") from exc
    except openai.RateLimitError as exc:
        raise LLMUnavailable(f"{ref.provider} 限流，稍后再试") from exc
    except openai.APIStatusError as exc:
        raise LLMUnavailable(f"{ref.provider} 返回 {exc.status_code}") from exc

    return extract_text(response)


def extract_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    content = choices[0].message.content if choices else None
    if not content:
        raise LLMUnavailable("OpenAI 的响应里没有内容")
    return content
