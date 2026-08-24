"""Anthropic 适配器。

接口形状（output_config / thinking / 异常类名）都对着已安装的 anthropic
SDK 核实过，勿凭记忆改；改前先读 @claude-api skill。

request() 是这个文件里唯一碰网络的函数，测试不调它。extract_text 是纯
函数，用 fixture 测——这与 editor.py 把 $EDITOR 收窄到一处是同一结构。
"""

from __future__ import annotations

from . import LLMUnavailable

MAX_TOKENS = 16000


def request(ref, system: str, user: str, schema: dict) -> str:
    """发一次请求，返回模型输出的原始文本。"""
    # 延迟导入：ari board 之类的命令用不到 SDK，不该为它付启动开销
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("没有安装 anthropic SDK（跑一次 uv sync）") from exc

    client = anthropic.Anthropic(api_key=ref.api_key, base_url=ref.base_url)
    try:
        response = client.messages.create(
            model=ref.model,
            max_tokens=MAX_TOKENS,
            # 排序与混淆因素是要推理的判断。这要求 Claude 4.6 及以上，
            # config.toml 的注释里写明了这个前提。
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable(f"连不上 {ref.provider}：{exc}") from exc
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable(f"{ref.provider} 认证失败，检查 API key") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable(f"{ref.provider} 限流，稍后再试") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"{ref.provider} 返回 {exc.status_code}") from exc

    return extract_text(response)


def extract_text(response) -> str:
    """取第一个文本块。thinking 打开时前面可能还有 thinking 块。"""
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    raise LLMUnavailable("Anthropic 的响应里没有文本块")
