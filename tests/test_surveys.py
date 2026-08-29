"""调研的分层算法与事件投影。全是纯函数。"""

from __future__ import annotations

from ari.events import Event
from ari.surveys import (
    TIER_FOLLOWUP,
    TIER_MILESTONE,
    in_set_citations,
    milestone_threshold,
    next_survey_id,
    project_surveys,
    rank_milestones,
)

SURVEY = "s1"


def _event(type_, payload=None, ts="2026-08-29T10:00:00+08:00", survey=SURVEY):
    return Event(ts=ts, type=type_, batch=survey, payload=payload or {})


def _opened(**overrides):
    payload = {"topic": "小数据集上的正则化", "query": "dropout small data", "source": "openalex"}
    payload.update(overrides)
    return _event("survey_opened", payload)


def _found(work, **overrides):
    payload = {"work": work, "title": f"论文 {work}", "year": 2024}
    payload.update(overrides)
    return _event("paper_found", payload)


# ---------- 分层：里程碑是算出来的 ----------


def test_in_set_citations_counts_how_many_of_the_set_cite_each_work():
    """读法是「这个子领域的近期工作里，3/4 篇都引了它」。"""
    counts = in_set_citations(
        {
            "A": ["X", "Y"],
            "B": ["X"],
            "C": ["X", "Z"],
            "D": ["Y"],
        }
    )

    assert counts == {"X": 3, "Y": 2, "Z": 1}


def test_a_paper_citing_the_same_work_twice_only_counts_once():
    assert in_set_citations({"A": ["X", "X", "X"]}) == {"X": 1}


def test_a_paper_does_not_cite_itself_into_the_ranking():
    """数据里偶尔会出现自引成环，不该让一篇论文把自己顶成里程碑。"""
    assert in_set_citations({"A": ["A", "X"]}) == {"X": 1}


def test_threshold_has_a_floor_and_scales_with_the_set():
    # 1–2 篇的共引很可能是巧合，所以下限是 3
    assert milestone_threshold(4) == 3
    assert milestone_threshold(20) == 3
    # 种子集一大，阈值要跟着走，否则什么都能过线
    assert milestone_threshold(50) == 8
    assert milestone_threshold(100) == 15
    assert milestone_threshold(0) == 3


def test_rank_milestones_returns_only_what_passes_the_threshold():
    referenced = {f"P{i}": ["FOUNDATION"] for i in range(5)}
    referenced["P0"] += ["RARE"]
    referenced["P1"] += ["RARE"]

    ranked = rank_milestones(referenced)

    # 5 篇 → 阈值 3。FOUNDATION 5 票过线，RARE 2 票不过。
    assert ranked == [("FOUNDATION", 5)]


def test_rank_milestones_is_stable_for_ties():
    """同一份数据每次跑必须给出同一个答案，否则「可复现」是空话。"""
    referenced = {f"P{i}": ["B_WORK", "A_WORK"] for i in range(4)}

    assert rank_milestones(referenced) == [("A_WORK", 4), ("B_WORK", 4)]


def test_rank_milestones_respects_the_limit():
    referenced = {f"P{i}": [f"F{j}" for j in range(30)] for i in range(4)}

    assert len(rank_milestones(referenced, limit=5)) == 5


# ---------- 投影 ----------


def test_survey_ids_follow_the_batch_convention():
    assert next_survey_id({}) == "s1"
    assert next_survey_id({"s1": None, "s2": None}) == "s3"
    assert next_survey_id({"s9": None, "s10": None}) == "s11"


def test_projection_folds_papers_into_a_survey():
    surveys, warnings = project_surveys(
        [
            _opened(),
            _found("W1", tier=TIER_MILESTONE, in_set=7, cited_by=34236, year=2014),
            _found("W2", year=2024),
        ]
    )

    survey = surveys["s1"]
    assert survey.topic == "小数据集上的正则化"
    assert [p.work for p in survey.tier(TIER_MILESTONE)] == ["W1"]
    assert [p.work for p in survey.tier(TIER_FOLLOWUP)] == ["W2"]
    assert warnings == []


def test_manual_tiering_overrides_the_algorithm():
    """算法给的是起点，不是判决。你比它更懂你在找什么。"""
    surveys, _ = project_surveys(
        [
            _opened(),
            _found("W2", tier=TIER_FOLLOWUP),
            _event("paper_tiered", {"work": "W2", "tier": TIER_MILESTONE, "by": "manual"}),
        ]
    )

    paper = surveys["s1"].papers["W2"]
    assert paper.tier == TIER_MILESTONE
    assert paper.tier_by == "manual"


def test_an_ai_summary_never_makes_a_paper_count_as_read():
    """这一层真正的风险不是幻觉，是读了 40 篇摘要之后记成自己调研过。

    摘要走 note 事件，而投影完全忽略 note——所以「已读」在数据层面就不
    可能被 AI 写入。这是结构保证，不是界面上一个标签。
    """
    surveys, _ = project_surveys(
        [
            _opened(),
            _found("W1", tier=TIER_MILESTONE),
            Event(
                ts="2026-08-29T11:00:00+08:00",
                type="note",
                batch=SURVEY,
                payload={"kind": "ai_paper_summary", "work": "W1", "summary": "它把 dropout 率按层深退火"},
            ),
        ]
    )

    paper = surveys["s1"].papers["W1"]
    assert paper.read is False
    assert paper.takeaway == ""
    assert surveys["s1"].unread_milestones == [paper]


def test_reading_a_paper_records_what_you_took_away():
    surveys, _ = project_surveys(
        [
            _opened(),
            _found("W1", tier=TIER_MILESTONE),
            _event(
                "paper_read",
                {"work": "W1", "takeaway": "dropout 的等价解释是模型平均，不是噪声注入"},
                ts="2026-08-29T12:00:00+08:00",
            ),
        ]
    )

    paper = surveys["s1"].papers["W1"]
    assert paper.read is True
    assert paper.takeaway.startswith("dropout 的等价解释")
    assert surveys["s1"].unread_milestones == []


def test_skipped_papers_drop_out_of_both_tiers():
    surveys, _ = project_surveys(
        [
            _opened(),
            _found("W1", tier=TIER_MILESTONE),
            _found("W2"),
            _event("paper_skipped", {"work": "W2", "reason": "只是换了数据集"}),
        ]
    )

    survey = surveys["s1"]
    assert survey.tier(TIER_FOLLOWUP) == []
    assert survey.papers["W2"].skipped is True
    assert survey.papers["W2"].skip_reason == "只是换了数据集"


def test_ready_for_bottleneck_only_once_every_milestone_is_read():
    events = [_opened(), _found("W1", tier=TIER_MILESTONE), _found("W2", tier=TIER_MILESTONE)]

    surveys, _ = project_surveys(events)
    assert surveys["s1"].ready_for_bottleneck is False

    events.append(_event("paper_read", {"work": "W1", "takeaway": "读了"}, ts="2026-08-29T12:00:00+08:00"))
    events.append(_event("paper_read", {"work": "W2", "takeaway": "也读了"}, ts="2026-08-29T13:00:00+08:00"))
    surveys, _ = project_surveys(events)
    assert surveys["s1"].ready_for_bottleneck is True


def test_a_survey_with_no_milestones_is_not_ready_to_close():
    """一篇里程碑都没有的调研，不该显示成「读完了」。"""
    surveys, _ = project_surveys([_opened(), _found("W2")])

    assert surveys["s1"].ready_for_bottleneck is False


def test_milestones_sort_by_in_set_citations_not_raw_citation_count():
    """原始被引数受领域规模影响极大，一篇平庸的综述可能比奠基工作被引更多。"""
    surveys, _ = project_surveys(
        [
            _opened(),
            _found("REVIEW", tier=TIER_MILESTONE, in_set=3, cited_by=99999),
            _found("FOUNDATION", tier=TIER_MILESTONE, in_set=9, cited_by=100),
        ]
    )

    assert [p.work for p in surveys["s1"].tier(TIER_MILESTONE)] == ["FOUNDATION", "REVIEW"]


def test_bottleneck_and_close_are_recorded():
    surveys, _ = project_surveys(
        [
            _opened(),
            _event("survey_bottleneck", {"text": "没人分开量过容量与正则的贡献"}),
            _event("survey_closed", {}),
        ]
    )

    survey = surveys["s1"]
    assert survey.bottleneck.startswith("没人分开量过")
    assert survey.closed is True


def test_events_for_an_unopened_survey_are_warned_not_fatal():
    surveys, warnings = project_surveys([_found("W1")])

    assert surveys == {}
    assert len(warnings) == 1 and "未开启的调研" in warnings[0]


def test_an_event_for_an_unknown_paper_is_warned_not_fatal():
    surveys, warnings = project_surveys(
        [_opened(), _event("paper_read", {"work": "W9", "takeaway": "读了个不存在的"})]
    )

    assert surveys["s1"].papers == {}
    assert len(warnings) == 1 and "不在调研" in warnings[0]
