"""调研这一层的 AI。见 v0.5 spec §5。

**AI 绝不产出论文条目。** 所有条目来自 OpenAlex，每条都带 Work ID，可点开
核实。这是结构保证不是提示词里的一句请求——下面三个 schema 里根本没有让
模型自由填写论文标题的字段。

理由与 advising.py 的「不给数值」同构，但更严重：编造的数值跑一次实验就
发现了，编造的引用会跟着你进 related work，直到审稿人指出来。

AI 只做三件它真正擅长的事：把一句话主题变成检索式；把真实摘要读成「它相
对于那篇改了什么」；在你写下自己的瓶颈之后给一份独立判断。
"""

from __future__ import annotations

from pathlib import Path

from .config import load_config, resolve_role
from .llm import LLMUnavailable, complete

# ---------- 一、主题 → 检索式 ----------

QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["query", "rationale"],
    "additionalProperties": False,
}

QUERY_SYSTEM = """\
把研究者的一句话主题变成一个 OpenAlex 全文检索式。

规则：
1. 只用英文关键词，OpenAlex 的语料是英文的。
2. 三到六个词，覆盖「问题域 + 方法 + 场景」，不要堆同义词。
3. 不要用布尔运算符、引号、通配符——OpenAlex 的 search 参数是自然语言相关度
   检索，加符号只会更差。
4. rationale 用一句中文说清你为什么这么选词，让对方能判断要不要改。
"""


def build_query_prompt(topic: str, question: str = "") -> str:
    lines = [f"主题：{topic}"]
    if question:
        lines.append(f"想回答的问题：{question}")
    lines.append("")
    lines.append("给一个 OpenAlex 检索式。")
    return "\n".join(lines)


def check_query(result: dict) -> dict:
    query = (result.get("query") or "").strip()
    if not query:
        raise LLMUnavailable("AI 没有给出检索式")
    if len(query) > 200:
        raise LLMUnavailable("AI 给的检索式过长，多半跑偏了")
    return {"query": query, "rationale": (result.get("rationale") or "").strip()}


def suggest_query(root: Path, topic: str, question: str = "") -> dict:
    ref = resolve_role(load_config(root), "reason")
    return check_query(
        complete(ref, QUERY_SYSTEM, build_query_prompt(topic, question), QUERY_SCHEMA)
    )


# ---------- 二、长尾论文：它相对于里程碑改了什么 ----------

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "changed": {"type": "string"},
        "worth_reading": {"type": "boolean"},
        "why": {"type": "string"},
    },
    "required": ["changed", "worth_reading", "why"],
    "additionalProperties": False,
}

SUMMARY_SYSTEM = """\
你在帮一位研究者分配注意力。他已经打算精读这个领域的几篇奠基工作，现在要
决定长尾里的这一篇值不值得也精读。

给三样：
1. changed —— 相对于奠基工作，这篇具体改了哪一处。一句话，要具体到可以动手
   核对（「把 dropout 率按层深退火，其余照搬原设置」），不要写「提出了一种
   新方法」这种等于没说的话。
2. worth_reading —— 值不值得精读。多数应该是 false：长尾里绝大多数是小改动，
   这正是它们被归到长尾的原因。只有当它换掉了某个核心假设时才给 true。
3. why —— 一句话说明理由。

只依据给你的摘要。摘要里没有的信息不要补，不确定就在 why 里说明摘要不够。
绝不编造实验数字。
"""


def build_summary_prompt(title: str, abstract: str, milestones: list[str]) -> str:
    lines = ["这个领域的奠基工作："]
    lines += [f"  - {name}" for name in milestones] or ["  （尚未确定）"]
    lines += ["", f"待判断的论文：{title}", "", "摘要：", abstract or "（这篇没有摘要）"]
    return "\n".join(lines)


def check_summary(result: dict) -> dict:
    changed = (result.get("changed") or "").strip()
    if not changed:
        raise LLMUnavailable("AI 没有说清这篇改了什么")
    return {
        "changed": changed,
        "worth_reading": bool(result.get("worth_reading")),
        "why": (result.get("why") or "").strip(),
    }


def summarize_paper(root: Path, title: str, abstract: str, milestones: list[str]) -> dict:
    ref = resolve_role(load_config(root), "reason")
    return check_summary(
        complete(
            ref,
            SUMMARY_SYSTEM,
            build_summary_prompt(title, abstract, milestones),
            SUMMARY_SCHEMA,
        )
    )


# ---------- 三、独立的瓶颈判断 ----------

BOTTLENECK_SCHEMA = {
    "type": "object",
    "properties": {
        "bottleneck": {"type": "string"},
        "unexamined": {"type": "array", "items": {"type": "string"}},
        "agrees": {"type": "boolean"},
    },
    "required": ["bottleneck", "unexamined", "agrees"],
    "additionalProperties": False,
}

BOTTLENECK_SYSTEM = """\
研究者读完了一个领域的奠基工作，写下了他认为的瓶颈。给一份**独立**判断。

给三样：
1. bottleneck —— 你认为这个领域现在卡在哪。一句话，要具体到能设计实验去检验。
2. unexamined —— 这批工作共同没有检验的假设，两到四条。这是最有价值的部分：
   一个领域里所有人都默认成立、但从没有人单独验证过的东西。
3. agrees —— 你的判断是否与研究者写的实质一致。

**不一致不是问题，是这次调用的价值所在。** 不要为了附和而改口；如果你看到
的瓶颈不同，就直说不同。

只依据给你的论文标题与研究者的精读笔记。不要提到没给你的论文，不要编造
文献，不要给数值。
"""


def build_bottleneck_prompt(survey) -> str:
    lines = [f"主题：{survey.topic}"]
    if survey.question:
        lines.append(f"想回答的问题：{survey.question}")
    lines += ["", "他精读的奠基工作，以及他记下的收获："]
    for paper in survey.tier("milestone"):
        year = f"{paper.year}" if paper.year else "年份不详"
        lines.append(f"  - [{year}] {paper.title}（被本领域近期工作引用 {paper.in_set} 次）")
        if paper.takeaway:
            lines.append(f"      他的收获：{paper.takeaway}")
    lines += ["", f"他写下的瓶颈：{survey.bottleneck}", "", "给你的独立判断。"]
    return "\n".join(lines)


def check_bottleneck(result: dict) -> dict:
    text = (result.get("bottleneck") or "").strip()
    if not text:
        raise LLMUnavailable("AI 没有给出瓶颈判断")
    return {
        "bottleneck": text,
        "unexamined": [str(x).strip() for x in (result.get("unexamined") or []) if str(x).strip()],
        "agrees": bool(result.get("agrees")),
    }


def reason_bottleneck(root: Path, survey) -> dict:
    """必须在研究者写下自己的判断之后才调用——锚定约束在 web.ask_bottleneck。"""
    ref = resolve_role(load_config(root), "reason")
    return check_bottleneck(
        complete(ref, BOTTLENECK_SYSTEM, build_bottleneck_prompt(survey), BOTTLENECK_SCHEMA)
    )
