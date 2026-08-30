"""OpenAI 适配器。

用 chat.completions 而不是更新的 Responses API：config.toml 明确暴露了
base_url，科研环境里指向 vLLM 之类 OpenAI 兼容的自建服务是常态，而这些
服务几乎都实现 /chat/completions、极少实现 /responses。兼容性在这里
比跟进新接口重要。

request() 是唯一碰网络的函数，测试不调它。
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from . import LLMUnavailable


def _is_official_openai(base_url: str | None) -> bool:
    """只有 OpenAI 官方 endpoint 才假设支持完整的 Chat Completions 扩展。

    ``openai`` provider 也承载 DeepSeek、vLLM 等兼容服务。它们通常只实现
    ``system`` 角色和旧 JSON mode，不能因为 SDK 相同就假定能力也相同。
    """
    if not base_url:
        return True
    return (urlparse(base_url).hostname or "").lower() == "api.openai.com"


def build_request(ref, system: str, user: str, schema: dict) -> dict:
    """构造一次 Chat Completions 请求，官方与兼容 endpoint 分开处理。"""
    if _is_official_openai(ref.base_url):
        return {
            "model": ref.model,
            "messages": [
                {"role": "developer", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ari_output", "strict": True, "schema": schema},
            },
        }

    # OpenAI-compatible 只意味着路径/响应大体兼容，不意味着支持 developer
    # 或 Structured Outputs。DeepSeek Chat Completions 明确只接受 system 角色，
    # JSON 输出使用 json_object。schema 仍由本项目在收到响应后严格校验。
    json_instruction = (
        "\n\n只返回 JSON，不要使用 Markdown 代码块。输出必须符合这个 JSON Schema：\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    return {
        "model": ref.model,
        "messages": [
            {"role": "system", "content": system + json_instruction},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }


def _endpoint_name(ref) -> str:
    return (urlparse(ref.base_url).hostname if ref.base_url else None) or ref.provider


def _status_detail(exc) -> str:
    """从 SDK 异常中只取服务端说明，不回显请求头、key 或完整请求。"""
    body = getattr(exc, "body", None)
    message = ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or ""
        message = message or body.get("message") or ""
    if not message:
        message = getattr(exc, "message", "") or ""
    return " ".join(str(message).split())[:500]


def request(ref, system: str, user: str, schema: dict) -> str:
    # 延迟导入，理由同 claude.py
    try:
        import openai
    except ImportError as exc:
        raise LLMUnavailable("没有安装 openai SDK（跑一次 uv sync）") from exc

    endpoint = _endpoint_name(ref)
    try:
        client = openai.OpenAI(api_key=ref.api_key, base_url=ref.base_url)
        response = client.chat.completions.create(**build_request(ref, system, user, schema))
    except ImportError as exc:
        # httpx 在检测到 SOCKS_PROXY 时会延迟导入 socksio；缺依赖也必须走
        # LLMUnavailable 降级，不能让可选 AI 层把 plan/review 整体撞掉。
        raise LLMUnavailable(f"{endpoint} 客户端缺少网络依赖：{exc}") from exc
    except openai.APIConnectionError as exc:
        raise LLMUnavailable(f"连不上 {endpoint}：{exc}") from exc
    except openai.AuthenticationError as exc:
        raise LLMUnavailable(f"{endpoint} 认证失败，检查 API key") from exc
    except openai.RateLimitError as exc:
        raise LLMUnavailable(f"{endpoint} 限流，稍后再试") from exc
    except openai.APIStatusError as exc:
        detail = _status_detail(exc)
        suffix = f"：{detail}" if detail else ""
        raise LLMUnavailable(f"{endpoint} 返回 {exc.status_code}{suffix}") from exc

    return extract_text(response)


def extract_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    content = choices[0].message.content if choices else None
    if not content:
        raise LLMUnavailable("OpenAI 的响应里没有内容")
    return content
