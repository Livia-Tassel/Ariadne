"""论文草稿：研究流程的最后一段。

「写论文所需的一切材料，在过程中自然沉淀」——批次收口时结论已经写
下，信念账本就是 discussion 的原材料。这里只提供分节写作与素材引用：
每个章节可以引用批次和信念作为 materials，追溯「这一段话的证据是
哪次实验」。section_saved 只追加不修改，最新一次保存生效。

草稿用 p1 / p2 编号（paper），与批次 b1 / b2 呼应。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 论文的标准章节与展示名。顺序即写作的常规顺序。
SECTIONS: list[tuple[str, str]] = [
    ("abstract", "摘要"),
    ("intro", "引言"),
    ("related", "相关工作"),
    ("method", "方法"),
    ("results", "结果"),
    ("discussion", "讨论"),
    ("conclusion", "结论"),
]
SECTION_NAMES = dict(SECTIONS)

STATUS_WRITING = "撰写中"
STATUS_SUBMITTED = "已投稿"
STATUS_PUBLISHED = "已发表"
_STATUS_EVENT_VALUES = {
    "writing": STATUS_WRITING,
    "submitted": STATUS_SUBMITTED,
    "published": STATUS_PUBLISHED,
}


def next_draft_id(drafts: dict) -> str:
    """p1 / p2 / ...。认不出的 id 直接忽略，与 next_batch_id 同一套规则。"""
    used = []
    for key in drafts:
        if isinstance(key, str) and key.startswith("p") and key[1:].isdigit():
            used.append(int(key[1:]))
    return f"p{max(used, default=0) + 1}"


@dataclass
class Section:
    name: str
    text: str = ""
    materials: list[dict] = field(default_factory=list)
    saved_ts: str = ""


@dataclass
class Draft:
    id: str
    title: str
    venue: str = ""
    opened_ts: str = ""
    status: str = STATUS_WRITING
    sections: dict[str, Section] = field(default_factory=dict)

    def ordered_sections(self) -> list[Section]:
        """按标准章节顺序返回；只含有内容的那些。"""
        return [
            self.sections[name]
            for name, _label in SECTIONS
            if name in self.sections
        ]


def project_drafts(events) -> tuple[dict[str, Draft], list[str]]:
    """把 draft_* 事件折叠成草稿集合。返回 (drafts, 警告)。"""
    drafts: dict[str, Draft] = {}
    warnings: list[str] = []

    def warn(line_no: int, message: str):
        warnings.append(f"第 {line_no} 行：{message}，已跳过")

    for event in events:
        if event.type == "draft_opened":
            draft_id = (event.payload.get("draft") or "").strip()
            title = (event.payload.get("title") or "").strip()
            if not draft_id or not title:
                warn(event.line_no, "draft_opened 缺少 draft 或 title")
                continue
            if draft_id in drafts:
                continue  # 同一草稿重复开启，保留最早那次
            drafts[draft_id] = Draft(
                id=draft_id,
                title=title,
                venue=(event.payload.get("venue") or "").strip(),
                opened_ts=event.ts,
            )

        elif event.type == "section_saved":
            draft_id = (event.payload.get("draft") or "").strip()
            draft = drafts.get(draft_id)
            if draft is None:
                warn(event.line_no, f"section_saved 引用了不存在的草稿 {draft_id!r}")
                continue
            name = (event.payload.get("section") or "").strip()
            if name not in SECTION_NAMES:
                warn(event.line_no, f"未知章节 {name!r}")
                continue
            materials = event.payload.get("materials")
            if materials is not None and not isinstance(materials, list):
                warn(event.line_no, "materials 需要是列表")
                materials = []
            draft.sections[name] = Section(
                name=name,
                text=(event.payload.get("text") or "").rstrip(),
                materials=[m for m in (materials or []) if isinstance(m, dict)],
                saved_ts=event.ts,
            )

        elif event.type == "draft_status_changed":
            draft_id = (event.payload.get("draft") or "").strip()
            draft = drafts.get(draft_id)
            if draft is None:
                warn(event.line_no, f"draft_status_changed 引用了不存在的草稿 {draft_id!r}")
                continue
            raw = (event.payload.get("status") or "").strip()
            if raw not in _STATUS_EVENT_VALUES:
                warn(event.line_no, f"未知草稿状态 {raw!r}")
                continue
            draft.status = _STATUS_EVENT_VALUES[raw]

    return drafts, warnings


def render_markdown(draft: Draft, detail=None) -> str:
    """把草稿渲染成一份可直接交给合作者的 Markdown。

    素材引用渲染成脚注样式的来源清单：论文文本里最重要的是能回溯
    「这一段的证据是哪次实验」。

    detail 是可选的展开器 `material -> list[str]`：光给一个 ID 不够，
    related work 要的是里程碑清单本身。展开逻辑由调用方注入，因为本模块
    是纯投影，不该知道调研或批次长什么样。
    """
    lines = [f"# {draft.title}", ""]
    if draft.venue:
        lines += [f"> 目标发表：{draft.venue}", ""]

    for section in draft.ordered_sections():
        lines += [f"## {SECTION_NAMES[section.name]}", ""]
        if section.text:
            lines += [section.text, ""]
        if section.materials:
            lines += ["**素材来源**", ""]
            for material in section.materials:
                lines += [f"- {material_label(material)}"]
                if detail:
                    lines += detail(material)
            lines += [""]

    if not draft.ordered_sections():
        lines += ["还没有开始写。", ""]
    return "\n".join(lines)


def material_label(material: dict) -> str:
    if "batch" in material:
        return f"实验批次 {material['batch']}"
    if "belief" in material:
        return f"信念 {material['belief']}"
    if "idea" in material:
        return f"想法 {material['idea']}"
    if "survey" in material:
        return f"领域调研 {material['survey']}"
    return "未知素材"
