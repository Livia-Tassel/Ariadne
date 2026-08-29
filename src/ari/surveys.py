"""领域调研的分层与投影。见 v0.5 spec §4、§6、§7。

两件事：

**分层是算出来的，不是问 AI 的。** 里程碑 = 种子集内部被引数高的那些。
理由与「AI 不给数值」同构但更严重：编造的数值跑一次实验就发现，编造的
引用会跟着你进 related work。而且引用图数据本来就是可核实、可复现的，
正好对应本项目那条原则——结论必须纯离线可复现。

**AI 摘要与「我读过」在事件类型层面就分开。** 精读落 paper_read，AI 摘要
落 note（kind=ai_paper_summary），而 note 被所有投影跳过。这一层真正的
风险不是幻觉，是读了 40 篇摘要之后记成自己调研过——所以它必须是结构
保证，不能只是界面上一个标签。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

TIER_MILESTONE = "milestone"
TIER_FOLLOWUP = "followup"

_ID_RE = re.compile(r"^s(\d+)$")


def next_survey_id(surveys: dict) -> str:
    """s1、s2……与批次 ID 同构。"""
    used = [int(m.group(1)) for key in surveys if (m := _ID_RE.match(str(key)))]
    return f"s{max(used, default=0) + 1}"


def in_set_citations(referenced_by_work: dict[str, list[str]]) -> dict[str, int]:
    """种子集内部被引：S 里有多少篇引用了 w。

    读法是「这个子领域的近期工作里，7/25 篇都引了它」。这比原始被引数好——
    原始被引数受领域规模影响极大，一篇平庸的综述可能比奠基工作被引更多。

    同一篇论文重复引用同一条参考文献只算一次；论文不计自己。
    """
    counts: Counter[str] = Counter()
    for work, referenced in referenced_by_work.items():
        for ref in set(referenced or []):
            if ref and ref != work:
                counts[ref] += 1
    return dict(counts)


def milestone_threshold(seed_count: int) -> int:
    """至少 3 篇，或种子集的 15%，取大者。

    下限 3 是因为 1–2 篇的共引很可能是巧合；15% 让阈值随种子集规模走，
    否则种子集一大，什么都能过线。
    """
    return max(3, math.ceil(0.15 * max(seed_count, 0)))


def rank_milestones(
    referenced_by_work: dict[str, list[str]], *, limit: int = 20
) -> list[tuple[str, int]]:
    """按内部被引数降序取里程碑候选，只返回过线的。

    返回 (work, 内部被引数)，同分时按 work ID 排序保证结果稳定——
    同一份数据每次跑必须给出同一个答案。
    """
    counts = in_set_citations(referenced_by_work)
    floor = milestone_threshold(len(referenced_by_work))
    passing = [(work, n) for work, n in counts.items() if n >= floor]
    passing.sort(key=lambda item: (-item[1], item[0]))
    return passing[:limit]


@dataclass
class PaperState:
    work: str
    title: str = ""
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str = ""
    cited_by: int = 0
    doi: str = ""
    abstract: str = ""
    in_set: int = 0
    tier: str = TIER_FOLLOWUP
    tier_by: str = "auto"
    takeaway: str = ""
    read_ts: str = ""
    skipped: bool = False
    skip_reason: str = ""

    @property
    def read(self) -> bool:
        """只有 paper_read 事件能让它为真。AI 摘要不行——那是两件事。"""
        return bool(self.read_ts)


@dataclass
class Survey:
    id: str
    topic: str = ""
    question: str = ""
    query: str = ""
    source: str = "openalex"
    opened_ts: str = ""
    papers: dict[str, PaperState] = field(default_factory=dict)
    budget: dict | None = None
    fetched_ts: str = ""
    bottleneck: str = ""
    bottleneck_ts: str = ""
    closed: bool = False
    ideas: list[str] = field(default_factory=list)

    def tier(self, name: str) -> list[PaperState]:
        """某一层的论文。里程碑按内部被引降序，长尾按年份新到旧。"""
        rows = [p for p in self.papers.values() if p.tier == name and not p.skipped]
        if name == TIER_MILESTONE:
            return sorted(rows, key=lambda p: (-p.in_set, -p.cited_by, p.work))
        return sorted(rows, key=lambda p: (-(p.year or 0), p.work))

    @property
    def unread_milestones(self) -> list[PaperState]:
        return [p for p in self.tier(TIER_MILESTONE) if not p.read]

    @property
    def ready_for_bottleneck(self) -> bool:
        """里程碑都读完了，该收口写瓶颈了。"""
        return bool(self.tier(TIER_MILESTONE)) and not self.unread_milestones


_KNOWN = {
    "survey_opened",
    "survey_fetched",
    "paper_found",
    "paper_tiered",
    "paper_read",
    "paper_skipped",
    "survey_bottleneck",
    "survey_closed",
}


def project_surveys(events) -> tuple[dict[str, Survey], list[str]]:
    """把事件流折叠成调研状态。与 project_ideas / project_beliefs 同构。

    note 事件（含 AI 摘要）在这里被完全忽略——摘要过的论文不会因此变成
    「已读」。这不是疏漏，是 §6 那条诚实性约束的实现。
    """
    surveys: dict[str, Survey] = {}
    warnings: list[str] = []

    for event in events:
        if event.type not in _KNOWN:
            continue

        if event.type == "survey_opened":
            surveys[event.batch] = Survey(
                id=event.batch,
                topic=event.payload.get("topic", ""),
                question=event.payload.get("question", ""),
                query=event.payload.get("query", ""),
                source=event.payload.get("source", "openalex"),
                opened_ts=event.ts,
            )
            continue

        survey = surveys.get(event.batch)
        if survey is None:
            warnings.append(
                f"第 {event.line_no} 行：事件属于未开启的调研 {event.batch!r}，已跳过"
            )
            continue

        if event.type == "survey_fetched":
            survey.fetched_ts = event.ts
            survey.budget = {
                "remaining": event.payload.get("budget_remaining"),
                "limit": event.payload.get("budget_limit"),
                "reset": event.payload.get("budget_reset"),
            }
            continue
        if event.type == "survey_bottleneck":
            survey.bottleneck = event.payload.get("text", "")
            survey.bottleneck_ts = event.ts
            continue
        if event.type == "survey_closed":
            survey.closed = True
            continue

        work = event.payload.get("work") or ""
        if not work:
            warnings.append(f"第 {event.line_no} 行：{event.type} 缺少 work 字段，已跳过")
            continue

        if event.type == "paper_found":
            survey.papers[work] = PaperState(
                work=work,
                title=event.payload.get("title", ""),
                year=event.payload.get("year"),
                authors=list(event.payload.get("authors") or []),
                venue=event.payload.get("venue", ""),
                cited_by=event.payload.get("cited_by") or 0,
                doi=event.payload.get("doi", ""),
                abstract=event.payload.get("abstract", ""),
                in_set=event.payload.get("in_set") or 0,
                tier=event.payload.get("tier") or TIER_FOLLOWUP,
            )
            continue

        paper = survey.papers.get(work)
        if paper is None:
            warnings.append(f"第 {event.line_no} 行：{work} 不在调研 {survey.id} 里，已跳过")
            continue

        if event.type == "paper_tiered":
            paper.tier = event.payload.get("tier") or TIER_FOLLOWUP
            paper.tier_by = event.payload.get("by") or "manual"
        elif event.type == "paper_read":
            # 精读笔记只有人能写。摘要走 note，到不了这里。
            paper.takeaway = event.payload.get("takeaway", "")
            paper.read_ts = event.ts
            paper.skipped = False
        elif event.type == "paper_skipped":
            paper.skipped = True
            paper.skip_reason = event.payload.get("reason", "")

    return surveys, warnings
