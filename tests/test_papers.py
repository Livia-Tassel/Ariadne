"""论文草稿：分节写作与素材引用的投影。"""

from __future__ import annotations

from ari.events import Event
from ari.papers import (
    next_draft_id,
    project_drafts,
    render_markdown,
)


def _events(*rows):
    return [
        Event(ts=f"2026-08-26T11:0{i}:00+00:00", type=row[0], payload=row[1])
        for i, row in enumerate(rows)
    ]


def test_next_draft_id_counts_like_batches():
    assert next_draft_id({}) == "p1"
    assert next_draft_id({"p1": None}) == "p2"
    assert next_draft_id({"p1": None, "p3": None, "weird": None}) == "p4"


def test_open_save_and_latest_wins():
    drafts, warnings = project_drafts(
        _events(
            ("draft_opened", {"draft": "p1", "title": "容量与增强", "venue": "TMLR"}),
            ("section_saved", {"draft": "p1", "section": "results", "text": "第一版结论", "materials": [{"batch": "b1"}]}),
            ("section_saved", {"draft": "p1", "section": "results", "text": "第二版结论", "materials": []}),
        )
    )

    assert not warnings
    draft = drafts["p1"]
    assert draft.title == "容量与增强"
    assert draft.venue == "TMLR"
    assert draft.status == "撰写中"
    section = draft.sections["results"]
    assert section.text == "第二版结论"
    assert section.materials == []


def test_status_changes_and_event_values():
    drafts, _ = project_drafts(
        _events(
            ("draft_opened", {"draft": "p1", "title": "T"}),
            ("draft_status_changed", {"draft": "p1", "status": "submitted"}),
            ("draft_status_changed", {"draft": "p1", "status": "published"}),
        )
    )
    assert drafts["p1"].status == "已发表"


def test_materials_are_kept_with_sections():
    drafts, _ = project_drafts(
        _events(
            ("draft_opened", {"draft": "p1", "title": "T"}),
            (
                "section_saved",
                {
                    "draft": "p1",
                    "section": "discussion",
                    "text": "增强是主要混淆因素",
                    "materials": [
                        {"batch": "b1"},
                        {"belief": "bel-7a3c"},
                        {"idea": "idea-c4b3"},
                    ],
                },
            ),
        )
    )
    assert drafts["p1"].sections["discussion"].materials == [
        {"batch": "b1"},
        {"belief": "bel-7a3c"},
        {"idea": "idea-c4b3"},
    ]


def test_unknown_sections_and_dangling_drafts_warn():
    drafts, warnings = project_drafts(
        _events(
            ("draft_opened", {"draft": "p1", "title": "T"}),
            ("section_saved", {"draft": "p9", "section": "results", "text": ""}),
            ("section_saved", {"draft": "p1", "section": "appendix", "text": ""}),
            ("draft_status_changed", {"draft": "p9", "status": "writing"}),
            ("draft_status_changed", {"draft": "p1", "status": "burned"}),
        )
    )
    assert list(drafts) == ["p1"]
    assert len(warnings) == 4
    assert all("已跳过" in w for w in warnings)


def test_render_markdown_includes_sections_and_sources():
    drafts, _ = project_drafts(
        _events(
            ("draft_opened", {"draft": "p1", "title": "容量与增强", "venue": "TMLR"}),
            (
                "section_saved",
                {
                    "draft": "p1",
                    "section": "results",
                    "text": "base 与 large 的差异稳定。",
                    "materials": [{"batch": "b1"}, {"belief": "bel-7a3c"}],
                },
            ),
        )
    )
    markdown = render_markdown(drafts["p1"])
    assert "# 容量与增强" in markdown
    assert "> 目标发表：TMLR" in markdown
    assert "## 结果" in markdown
    assert "base 与 large 的差异稳定。" in markdown
    assert "实验批次 b1" in markdown
    assert "信念 bel-7a3c" in markdown


def test_render_markdown_empty_draft():
    drafts, _ = project_drafts(_events(("draft_opened", {"draft": "p1", "title": "T"})))
    assert "还没有开始写" in render_markdown(drafts["p1"])


def test_render_markdown_can_expand_a_material_into_detail_lines():
    """素材引用光给一个 ID 是不够的——related work 要的是里程碑清单本身。

    展开器由调用方注入：papers.py 是纯投影，不该知道调研或批次长什么样。
    """
    from ari.papers import Draft, Section, render_markdown

    draft = Draft(id="p1", title="标题", opened_ts="2026-08-29T10:00:00+08:00")
    draft.sections["related"] = Section(
        name="related",
        text="见调研。",
        materials=[{"survey": "s1"}],
        saved_ts="2026-08-29T11:00:00+08:00",
    )

    markdown = render_markdown(
        draft,
        detail=lambda m: ["  - Deep Residual Learning（2016）[19 引用]", "      我的收获：残差连接"],
    )

    assert "- 领域调研 s1" in markdown
    assert "  - Deep Residual Learning（2016）[19 引用]" in markdown
    assert "      我的收获：残差连接" in markdown


def test_render_markdown_without_an_expander_still_lists_the_label():
    from ari.papers import Draft, Section, render_markdown

    draft = Draft(id="p1", title="标题", opened_ts="2026-08-29T10:00:00+08:00")
    draft.sections["related"] = Section(
        name="related", text="", materials=[{"survey": "s1"}], saved_ts="2026-08-29T11:00:00+08:00"
    )

    assert "- 领域调研 s1" in render_markdown(draft)
