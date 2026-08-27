"""Ariadne 本地 GUI 的服务层与 HTTP 入口。

HTTP 层保持很薄：浏览器提交结构化表单，服务校验后调用现有领域函数并
追加事件。页面展示的所有状态都从 runs.jsonl 重新投影，不在 GUI 旁边再
维护一份会漂移的数据库。
"""

from __future__ import annotations

import json
import math
import mimetypes
import re
import threading
import traceback
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .beliefs import project_beliefs
from .drafts import parse_number, parse_prediction
from .events import Event, append_event, read_events
from .ideas import make_idea_id, project_ideas
from .ingest import compile_template
from .metrics import MetricSpec, default_spec
from .papers import (
    SECTIONS,
    next_draft_id,
    project_drafts,
    render_markdown as render_draft_markdown,
)
from .planning import Design, build_events, expand_runs, next_batch_id
from .project import closure_blockers, project as project_events
from .reviewing import build_reflection_events, deviation_lines, pending
from .resources import asset_file
from .verdict import Verdict
from .workspace import initialize_project


class GuiInputError(ValueError):
    """可直接展示给用户的输入错误。"""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = int(status)


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _text(value, label: str, *, required: bool = True) -> str:
    result = value.strip() if isinstance(value, str) else ""
    if required and not result:
        raise GuiInputError(f"{label}不能为空")
    return result


def _jsonable_prediction(value):
    return list(value) if isinstance(value, tuple) else value


class GuiService:
    """GUI 的应用服务。方法只收/发 JSON 可序列化对象，便于直接测试。"""

    MAX_RUNS = 200

    def __init__(self, project_dir: str | Path):
        self.root = initialize_project(project_dir, exist_ok=True)
        self.runs_path = self.root / "runs.jsonl"
        self._write_lock = threading.Lock()

    def _load(self):
        events, parse_errors = read_events(self.runs_path)
        batches, warnings = project_events(events)
        ledger, belief_warnings = project_beliefs(events)
        ideas, idea_warnings = project_ideas(events)
        drafts, draft_warnings = project_drafts(events)
        all_warnings = warnings + belief_warnings + idea_warnings + draft_warnings
        return events, parse_errors, batches, all_warnings, ledger, ideas, drafts

    def preview_runs(self, payload: dict) -> dict:
        dimensions = self._dimensions(payload.get("dimensions"))
        runs = expand_runs(dimensions)
        if len(runs) > self.MAX_RUNS:
            raise GuiInputError(
                f"这个设计会生成 {len(runs)} 个 run；GUI 单批次上限是 {self.MAX_RUNS}。"
                "请缩小变量范围或拆成多个批次"
            )
        return {"ok": True, "dimensions": dimensions, "runs": runs}

    def create_batch(self, payload: dict) -> dict:
        research_direction = _text(payload.get("research_direction"), "研究方向")
        hypothesis = _text(payload.get("hypothesis"), "实验假设")
        dimensions = self._dimensions(payload.get("dimensions"))
        runs = expand_runs(dimensions)
        if len(runs) > self.MAX_RUNS:
            raise GuiInputError(f"一次最多创建 {self.MAX_RUNS} 个 run，当前是 {len(runs)} 个")

        metric_names, metric_specs = self._metrics(payload.get("metrics"))
        predictions = self._predictions(payload.get("predictions"), runs, metric_names)
        result_path = self._result_path(payload.get("result_path"))
        expected_ranking = self._expected_ranking(
            payload.get("expected_ranking"), runs, metric_names
        )

        _, _, batches, _, _, ideas, _ = self._load()
        idea_ref = self._idea_reference(payload.get("idea"), ideas)
        batch_id = next_batch_id(batches)
        design = Design(
            hypothesis=hypothesis,
            dimensions=dimensions,
            metrics=metric_names,
            metric_specs=metric_specs,
            result_path=result_path,
            expected_ranking=expected_ranking,
            research_direction=research_direction,
            idea=idea_ref,
        )
        new_events = build_events(batch_id, design, predictions, now=_now())
        with self._write_lock:
            # 写入前重新确认 batch id，避免两个页面同时提交时撞号。
            current, _ = read_events(self.runs_path)
            current_batches, _ = project_events(current)
            if next_batch_id(current_batches) != batch_id:
                raise GuiInputError("项目刚刚在另一个窗口中发生了变化，请刷新后再提交", 409)
            for event in new_events:
                append_event(self.runs_path, event)
        return {"ok": True, "batch": batch_id, "run_count": len(runs)}

    def revise_batch_meta(self, payload: dict) -> dict:
        """批次开启后补填 result_path / expected_ranking。

        建批次时未必知道结果文件长什么样——很多人是跑起来之后才确定路径。
        补填走独立事件，不改写 batch_opened：事件流只追加不修改。
        """
        batch_id = _text(payload.get("batch"), "批次")
        _, _, batches, _, _, _, _ = self._load()
        batch = batches.get(batch_id)
        if batch is None:
            raise GuiInputError(f"找不到批次 {batch_id}", 404)

        revised: dict = {}
        if "result_path" in payload:
            revised["result_path"] = self._result_path(payload.get("result_path"))
        if "expected_ranking" in payload:
            revised["expected_ranking"] = self._expected_ranking(
                payload.get("expected_ranking"),
                list(batch.runs) or expand_runs(batch.dimensions),
                self._batch_metric_names(batch),
            )
        if not revised:
            raise GuiInputError("没有要修改的字段")

        with self._write_lock:
            append_event(
                self.runs_path,
                Event(ts=_now(), type="batch_meta_revised", batch=batch_id, payload=revised),
            )
        return {"ok": True, "batch": batch_id}

    @staticmethod
    def _result_path(raw) -> str | None:
        """校验结果文件的路径模板。空值合法——这一项本来就是可选的。"""
        if raw in (None, ""):
            return None
        if not isinstance(raw, str):
            raise GuiInputError("结果路径模板必须是一段文本")
        template = raw.strip()
        if not template:
            return None
        if template.startswith("/") or template.startswith("~"):
            raise GuiInputError("结果路径模板要相对于项目目录，不要用绝对路径")
        try:
            compile_template(template)
        except (re.error, ValueError) as exc:
            raise GuiInputError(f"结果路径模板不合法：{exc}") from exc
        return template

    @staticmethod
    def _expected_ranking(raw, runs: list[str], metric_names: list[str]) -> dict | None:
        if raw in (None, "", {}):
            return None
        if not isinstance(raw, dict):
            raise GuiInputError("预期排序的格式不正确")
        metric = _text(raw.get("metric"), "预期排序的指标")
        if metric not in metric_names:
            raise GuiInputError(f"预期排序引用了未声明的指标 {metric}")
        order = raw.get("order")
        if not isinstance(order, list) or len(order) < 2:
            raise GuiInputError("预期排序至少要列出两个 run，否则没有可比的东西")
        known = set(runs)
        for item in order:
            if item not in known:
                raise GuiInputError(f"预期排序里的 {item!r} 不是这个批次的 run")
        if len(set(order)) != len(order):
            raise GuiInputError("预期排序里有重复的 run")
        return {"metric": metric, "order": list(order)}

    def add_results(self, payload: dict) -> dict:
        batch_id = _text(payload.get("batch"), "批次")
        raw_rows = payload.get("rows")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise GuiInputError("至少填写一条实验结果")

        _, _, batches, _, _, _, _ = self._load()
        batch = batches.get(batch_id)
        if batch is None:
            raise GuiInputError(f"找不到批次 {batch_id}", 404)
        metric_names = self._batch_metric_names(batch)
        if not metric_names:
            raise GuiInputError(f"批次 {batch_id} 没有指标")

        new_events: list[Event] = []
        seen: set[tuple[str, int]] = set()
        for index, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                raise GuiInputError(f"第 {index} 条结果格式不正确")
            run_key = _text(row.get("run"), f"第 {index} 条结果的 run")
            run = batch.runs.get(run_key)
            if run is None or run.prediction is None:
                raise GuiInputError(f"{run_key} 不属于批次 {batch_id}")
            seed = self._seed(row.get("seed"), index)
            key = (run_key, seed)
            if key in seen or any(seed in samples for samples in run.samples.values()):
                raise GuiInputError(
                    f"{run_key} 的 seed={seed} 已经存在。为避免无提示覆盖，请换一个 seed"
                )
            seen.add(key)

            raw_metrics = row.get("metrics")
            if not isinstance(raw_metrics, dict):
                raise GuiInputError(f"{run_key} 的指标格式不正确")
            metrics: dict[str, float] = {}
            for name in metric_names:
                if name not in raw_metrics or raw_metrics[name] in (None, ""):
                    raise GuiInputError(f"{run_key} 的 {name} 还没填")
                try:
                    value = parse_number(raw_metrics[name])
                except ValueError as exc:
                    raise GuiInputError(f"{run_key} 的 {name}：{exc}") from exc
                if not math.isfinite(value):
                    raise GuiInputError(f"{run_key} 的 {name} 必须是有限数值")
                metrics[name] = value

            new_events.append(
                Event(
                    ts=_now(),
                    type="run_result",
                    batch=batch_id,
                    run=run_key,
                    payload={
                        "seed": seed,
                        "metrics": metrics,
                        "source": self._source(row.get("source")),
                    },
                )
            )

        with self._write_lock:
            for event in new_events:
                append_event(self.runs_path, event)
        return {"ok": True, "written": len(new_events)}

    @staticmethod
    def _source(raw) -> dict:
        """结果的来源。手敲的与从文件抽的必须能区分开。

        mtime 是 project._check_integrity 的输入：结果文件早于预测写入时间
        就是「先看结果再补预测」的嫌疑。手敲没有 mtime，因此也拿不到这个
        检查——这是自动发现必须成为主路径的原因，不只是省几次敲键盘。
        """
        if not isinstance(raw, dict):
            return {"path": None, "kind": "manual_gui", "mtime": None}
        path = raw.get("path")
        mtime = raw.get("mtime")
        return {
            "path": str(path) if path else None,
            "kind": "structured" if path else "manual_gui",
            "mtime": str(mtime) if mtime else None,
        }

    def add_review(self, payload: dict) -> dict:
        batch_id = _text(payload.get("batch"), "批次")
        run_key = _text(payload.get("run"), "run")
        cause = _text(payload.get("cause"), "原因分析")
        nxt = _text(payload.get("next"), "下一步", required=False)

        _, _, batches, _, ledger, _, _ = self._load()
        batch = batches.get(batch_id)
        run = batch.runs.get(run_key) if batch else None
        if run is None:
            raise GuiInputError(f"找不到 {batch_id} / {run_key}", 404)
        if run.verdict is not Verdict.SURPRISE or run.closed:
            raise GuiInputError("只有尚未复盘的 SURPRISE 可以在这里提交复盘", 409)

        parsed = {
            "scope": "run",
            "cause": cause,
            "next": nxt,
            "beliefs_added": self._beliefs_added(payload.get("beliefs_added")),
            "belief_changes": self._belief_changes(payload.get("belief_changes"), ledger),
        }
        new_events = build_reflection_events(parsed, batch_id, run_key, ledger, _now())
        with self._write_lock:
            for event in new_events:
                append_event(self.runs_path, event)
        return {"ok": True, "written": len(new_events)}

    def close_batch(self, payload: dict) -> dict:
        batch_id = _text(payload.get("batch"), "批次")
        cause = _text(payload.get("cause"), "批次结论")
        nxt = _text(payload.get("next"), "下一步", required=False)

        _, _, batches, _, ledger, _, _ = self._load()
        batch = batches.get(batch_id)
        if batch is None:
            raise GuiInputError(f"找不到批次 {batch_id}", 404)
        if batch.closed:
            raise GuiInputError(f"批次 {batch_id} 已经收口", 409)
        blockers = closure_blockers(batch)
        if blockers:
            raise GuiInputError("这个批次还不能收口：" + "；".join(blockers), 409)

        parsed = {
            "scope": "batch",
            "cause": cause,
            "next": nxt,
            "beliefs_added": self._beliefs_added(payload.get("beliefs_added")),
            "belief_changes": self._belief_changes(payload.get("belief_changes"), ledger),
        }
        new_events = build_reflection_events(parsed, batch_id, None, ledger, _now())
        with self._write_lock:
            for event in new_events:
                append_event(self.runs_path, event)
        return {"ok": True, "written": len(new_events)}

    def state(self) -> dict:
        _, parse_errors, batches, warnings, ledger, ideas, drafts = self._load()
        serialized_batches = [self._batch_json(batch) for batch in reversed(list(batches.values()))]
        pending_runs = [
            {
                "batch": run.batch,
                "run": run.run,
                "deviations": deviation_lines(run),
                "rationale": (run.prediction or {}).get("rationale", ""),
            }
            for run in pending(batches)
        ]
        beliefs = [
            {
                "id": belief.id,
                "text": belief.text,
                "status": belief.status,
                "refuted": belief.refuted,
                "batch": belief.batch,
                "run": belief.run,
                "changes": [asdict(change) for change in belief.changes],
            }
            for belief in ledger.values()
        ]
        serialized_ideas = [
            {
                "id": idea.id,
                "text": idea.text,
                "motivation": idea.motivation,
                "status": idea.status(batches),
                "discarded": idea.discarded,
                "discard_reason": idea.discard_reason,
                "batches": idea.batches,
                "added_ts": idea.added_ts,
            }
            for idea in reversed(list(ideas.values()))
        ]
        serialized_drafts = [self._draft_json(draft) for draft in reversed(list(drafts.values()))]
        open_ideas = sum(1 for idea in ideas.values() if idea.status(batches) == "待验证")
        all_runs = [run for batch in batches.values() for run in batch.runs.values()]
        counts = {verdict.value: 0 for verdict in Verdict}
        for run in all_runs:
            counts[run.verdict.value] += 1
        return {
            "ok": True,
            "project": {"name": self.root.name, "path": str(self.root)},
            "summary": {
                "batches": len(batches),
                "runs": len(all_runs),
                "pending_reviews": len(pending_runs),
                "verdicts": counts,
                "ideas": len(ideas),
                "open_ideas": open_ideas,
                "drafts": len(drafts),
            },
            "batches": serialized_batches,
            "pending_reviews": pending_runs,
            "beliefs": beliefs,
            "ideas": serialized_ideas,
            "drafts": serialized_drafts,
            "sections": [{"name": name, "label": label} for name, label in SECTIONS],
            "warnings": warnings,
            "parse_errors": [asdict(error) for error in parse_errors],
        }

    # ---------- 想法 ----------

    def add_idea(self, payload: dict) -> dict:
        text = _text(payload.get("text"), "想法内容")
        motivation = _text(payload.get("motivation"), "动机", required=False)
        _, _, _, _, _, ideas, _ = self._load()
        existing = {idea.id: idea.text for idea in ideas.values()}
        try:
            idea_id = make_idea_id(text, existing)
        except ValueError as exc:
            raise GuiInputError(str(exc)) from exc
        if idea_id in ideas:
            raise GuiInputError("这个想法已经在账本里了", 409)
        event = Event(
            ts=_now(),
            type="idea_captured",
            payload={"id": idea_id, "text": " ".join(text.split()), "motivation": motivation},
        )
        with self._write_lock:
            append_event(self.runs_path, event)
        return {"ok": True, "idea": idea_id}

    def discard_idea(self, payload: dict) -> dict:
        idea_id = _text(payload.get("idea"), "想法")
        reason = _text(payload.get("reason"), "放弃原因", required=False)
        _, _, batches, _, _, ideas, _ = self._load()
        idea = ideas.get(idea_id)
        if idea is None:
            raise GuiInputError(f"找不到想法 {idea_id}", 404)
        if idea.discarded:
            raise GuiInputError("这个想法已经放弃了", 409)
        if any(not batches[b].closed for b in idea.batches if b in batches):
            raise GuiInputError("想法还有未收口的实验批次，先收口或放弃那些批次", 409)
        event = Event(
            ts=_now(),
            type="idea_discarded",
            payload={"id": idea_id, "reason": reason},
        )
        with self._write_lock:
            append_event(self.runs_path, event)
        return {"ok": True, "idea": idea_id}

    @staticmethod
    def _idea_reference(raw, ideas) -> str:
        idea_id = (raw or "").strip() if isinstance(raw, str) else ""
        if not idea_id:
            return ""
        if idea_id not in ideas:
            raise GuiInputError(f"找不到想法 {idea_id}")
        return idea_id

    # ---------- 论文 ----------

    def create_draft(self, payload: dict) -> dict:
        title = _text(payload.get("title"), "论文标题")
        venue = _text(payload.get("venue"), "目标期刊或会议", required=False)
        _, _, _, _, _, _, drafts = self._load()
        draft_id = next_draft_id(drafts)
        event = Event(
            ts=_now(),
            type="draft_opened",
            payload={"draft": draft_id, "title": title, "venue": venue},
        )
        with self._write_lock:
            current, _ = read_events(self.runs_path)
            current_drafts, _ = project_drafts(current)
            if next_draft_id(current_drafts) != draft_id:
                raise GuiInputError("项目刚刚在另一个窗口中发生了变化，请刷新后再提交", 409)
            append_event(self.runs_path, event)
        return {"ok": True, "draft": draft_id}

    def save_section(self, payload: dict) -> dict:
        draft_id = _text(payload.get("draft"), "草稿")
        section = _text(payload.get("section"), "章节")
        text = _text(payload.get("text"), "章节内容", required=False)
        _, _, batches, _, ledger, ideas, drafts = self._load()
        draft = drafts.get(draft_id)
        if draft is None:
            raise GuiInputError(f"找不到草稿 {draft_id}", 404)
        if section not in dict(SECTIONS):
            raise GuiInputError(f"未知章节 {section}")
        materials = self._materials(payload.get("materials"), batches, ledger, ideas)
        event = Event(
            ts=_now(),
            type="section_saved",
            payload={
                "draft": draft_id,
                "section": section,
                "text": text,
                "materials": materials,
            },
        )
        with self._write_lock:
            append_event(self.runs_path, event)
        return {"ok": True, "draft": draft_id, "section": section}

    def set_draft_status(self, payload: dict) -> dict:
        draft_id = _text(payload.get("draft"), "草稿")
        status = _text(payload.get("status"), "草稿状态")
        _, _, _, _, _, _, drafts = self._load()
        draft = drafts.get(draft_id)
        if draft is None:
            raise GuiInputError(f"找不到草稿 {draft_id}", 404)
        allowed = {"writing": "撰写中", "submitted": "已投稿", "published": "已发表"}
        if status not in allowed and status not in allowed.values():
            raise GuiInputError(f"草稿状态不正确：{status}")
        value = status if status in allowed else next(k for k, v in allowed.items() if v == status)
        event = Event(
            ts=_now(),
            type="draft_status_changed",
            payload={"draft": draft_id, "status": value},
        )
        with self._write_lock:
            append_event(self.runs_path, event)
        return {"ok": True, "draft": draft_id, "status": allowed[value]}

    def export_draft(self, payload: dict) -> dict:
        draft_id = _text(payload.get("draft"), "草稿")
        _, _, _, _, _, _, drafts = self._load()
        draft = drafts.get(draft_id)
        if draft is None:
            raise GuiInputError(f"找不到草稿 {draft_id}", 404)
        return {"ok": True, "draft": draft_id, "markdown": render_draft_markdown(draft)}

    @staticmethod
    def _materials(raw, batches, ledger, ideas) -> list[dict]:
        if raw in (None, ""):
            return []
        if not isinstance(raw, list):
            raise GuiInputError("素材引用格式不正确")
        materials: list[dict] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict) or len(item) != 1:
                raise GuiInputError(f"第 {index} 条素材引用格式不正确")
            if "batch" in item:
                if item["batch"] not in batches:
                    raise GuiInputError(f"素材引用了不存在的批次 {item['batch']}")
                materials.append({"batch": str(item["batch"])})
            elif "belief" in item:
                if item["belief"] not in ledger:
                    raise GuiInputError(f"素材引用了不存在的信念 {item['belief']}")
                materials.append({"belief": str(item["belief"])})
            elif "idea" in item:
                if item["idea"] not in ideas:
                    raise GuiInputError(f"素材引用了不存在的想法 {item['idea']}")
                materials.append({"idea": str(item["idea"])})
            else:
                raise GuiInputError(f"第 {index} 条素材引用格式不正确")
        return materials

    @staticmethod
    def _draft_json(draft) -> dict:
        return {
            "id": draft.id,
            "title": draft.title,
            "venue": draft.venue,
            "status": draft.status,
            "opened_ts": draft.opened_ts,
            "sections": [
                {
                    "name": section.name,
                    "text": section.text,
                    "materials": section.materials,
                    "saved_ts": section.saved_ts,
                }
                for section in draft.ordered_sections()
            ],
        }

    @staticmethod
    def _dimensions(raw) -> dict[str, list[str]]:
        rows = raw.items() if isinstance(raw, dict) else raw
        if not rows:
            raise GuiInputError("至少添加一个变量维度")
        dimensions: dict[str, list[str]] = {}
        for index, row in enumerate(rows, start=1):
            if isinstance(raw, dict):
                name, values = row
            elif isinstance(row, dict):
                name, values = row.get("name"), row.get("values")
            else:
                raise GuiInputError(f"第 {index} 个变量维度格式不正确")
            name = _text(name, f"第 {index} 个变量名")
            if name in dimensions:
                raise GuiInputError(f"变量名 {name} 重复")
            if isinstance(values, str):
                values = values.split(",")
            if not isinstance(values, (list, tuple)):
                raise GuiInputError(f"变量 {name} 的取值需要用逗号分隔")
            cleaned = [str(value).strip() for value in values if str(value).strip()]
            if not cleaned:
                raise GuiInputError(f"变量 {name} 至少需要一个取值")
            if len(set(cleaned)) != len(cleaned):
                raise GuiInputError(f"变量 {name} 中有重复取值")
            dimensions[name] = cleaned
        return dimensions

    @staticmethod
    def _metrics(raw) -> tuple[list[str], dict[str, MetricSpec]]:
        if not isinstance(raw, list) or not raw:
            raise GuiInputError("至少添加一个指标")
        names: list[str] = []
        specs: dict[str, MetricSpec] = {}
        for index, row in enumerate(raw, start=1):
            if not isinstance(row, dict):
                raise GuiInputError(f"第 {index} 个指标格式不正确")
            name = _text(row.get("name"), f"第 {index} 个指标名")
            if name in specs:
                raise GuiInputError(f"指标名 {name} 重复")
            inferred = default_spec(name) or MetricSpec()
            try:
                tolerance = float(row.get("tolerance", inferred.tolerance))
                spec = MetricSpec(
                    direction=row.get("direction") or inferred.direction,
                    compare=row.get("compare") or inferred.compare,
                    tolerance=tolerance,
                )
            except (TypeError, ValueError) as exc:
                raise GuiInputError(f"指标 {name} 的规格有问题：{exc}") from exc
            if not math.isfinite(spec.tolerance):
                raise GuiInputError(f"指标 {name} 的容差必须是有限数值")
            names.append(name)
            specs[name] = spec
        return names, specs

    @staticmethod
    def _predictions(raw, runs: list[str], metrics: list[str]) -> dict[str, dict]:
        if not isinstance(raw, list) or not raw:
            raise GuiInputError("请先生成并填写预测表")
        by_run: dict[str, dict] = {}
        for index, row in enumerate(raw, start=1):
            if not isinstance(row, dict):
                raise GuiInputError(f"第 {index} 条预测格式不正确")
            run = _text(row.get("run"), f"第 {index} 条预测的 run")
            if run not in runs:
                raise GuiInputError(f"预测表里的 {run} 不属于当前变量组合")
            if run in by_run:
                raise GuiInputError(f"run {run} 在预测表中重复")
            raw_metrics = row.get("metrics")
            if not isinstance(raw_metrics, dict):
                raise GuiInputError(f"{run} 的预测指标格式不正确")
            parsed_metrics = {}
            for name in metrics:
                if name not in raw_metrics or raw_metrics[name] in (None, ""):
                    raise GuiInputError(f"{run} 的 {name} 预测还没填")
                try:
                    parsed = parse_prediction(raw_metrics[name])
                except ValueError as exc:
                    raise GuiInputError(f"{run} 的 {name}：{exc}") from exc
                values = parsed if isinstance(parsed, tuple) else (parsed,)
                if not all(math.isfinite(value) for value in values):
                    raise GuiInputError(f"{run} 的 {name} 必须是有限数值")
                parsed_metrics[name] = _jsonable_prediction(parsed)
            confidence = row.get("confidence") or "medium"
            if confidence not in ("low", "medium", "high"):
                raise GuiInputError(f"{run} 的置信度不正确")
            rationale = _text(row.get("rationale"), f"{run} 的预测理由")
            by_run[run] = {
                "metrics": parsed_metrics,
                "confidence": confidence,
                "rationale": rationale,
            }
        missing = [run for run in runs if run not in by_run]
        if missing:
            raise GuiInputError(f"还有 {len(missing)} 个 run 没有预测")
        return by_run

    @staticmethod
    def _seed(value, index: int) -> int:
        if isinstance(value, bool):
            raise GuiInputError(f"第 {index} 条结果的 seed 必须是整数")
        try:
            seed = int(value)
        except (TypeError, ValueError) as exc:
            raise GuiInputError(f"第 {index} 条结果的 seed 必须是整数") from exc
        if str(value).strip() not in (str(seed), f"+{seed}"):
            raise GuiInputError(f"第 {index} 条结果的 seed 必须是整数")
        return seed

    @staticmethod
    def _beliefs_added(raw) -> list[str]:
        if raw in (None, ""):
            return []
        values = raw.splitlines() if isinstance(raw, str) else raw
        if not isinstance(values, list):
            raise GuiInputError("新信念需要一行一条")
        return [str(value).strip() for value in values if str(value).strip()]

    @staticmethod
    def _belief_changes(raw, ledger) -> dict[str, str]:
        if raw in (None, ""):
            return {}
        if not isinstance(raw, dict):
            raise GuiInputError("信念状态变更格式不正确")
        names = {
            "reinforced": "belief_reinforced",
            "weakened": "belief_weakened",
            "refuted": "belief_refuted",
            "belief_reinforced": "belief_reinforced",
            "belief_weakened": "belief_weakened",
            "belief_refuted": "belief_refuted",
        }
        changes = {}
        for belief_id, value in raw.items():
            if value in (None, "", "unchanged"):
                continue
            if belief_id not in ledger:
                raise GuiInputError(f"找不到信念 {belief_id}")
            if value not in names:
                raise GuiInputError(f"信念 {belief_id} 的新状态不正确")
            changes[belief_id] = names[value]
        return changes

    @staticmethod
    def _batch_metric_names(batch) -> list[str]:
        names: list[str] = []
        for run in batch.runs.values():
            for name in (run.prediction or {}).get("metrics", {}):
                if name not in names:
                    names.append(name)
        return names

    def _batch_json(self, batch) -> dict:
        metric_names = self._batch_metric_names(batch)
        runs = []
        for run in batch.runs.values():
            runs.append(
                {
                    "run": run.run,
                    "verdict": run.verdict.value,
                    "closed": run.closed,
                    "revised": run.revised,
                    "prediction": run.prediction,
                    "samples": {name: values for name, values in run.samples.items()},
                    "aggregates": {
                        name: {"mean": agg.mean, "sd": agg.sd, "n": agg.n}
                        for name, agg in run.aggregates.items()
                    },
                    "judgements": {
                        name: {
                            "verdict": judgement.verdict.value,
                            "deviation": judgement.deviation,
                            "threshold": judgement.threshold,
                            "note": judgement.note,
                        }
                        for name, judgement in run.metric_judgements.items()
                    },
                    "reflection": run.reflection,
                    "integrity": run.integrity,
                    "warnings": run.warnings,
                }
            )
        ranking = None
        if batch.ranking is not None:
            ranking = {
                "verdict": batch.ranking.verdict.value,
                "real_flips": batch.ranking.real_flips,
                "noisy_flips": batch.ranking.noisy_flips,
            }
        return {
            "id": batch.id,
            "research_direction": batch.research_direction,
            "hypothesis": batch.hypothesis,
            "idea": batch.idea,
            "dimensions": batch.dimensions,
            "metrics": metric_names,
            "metric_specs": batch.metric_specs,
            "result_path": batch.result_path,
            "opened_at": batch.opened_ts,
            "closed": batch.closed,
            "batch_reflection": batch.batch_reflection,
            "close_blockers": closure_blockers(batch),
            "info_signal": batch.info_signal,
            "ranking": ranking,
            "runs": runs,
            "warnings": batch.warnings,
        }


_POST_ROUTES = {
    "/api/runs/preview": "preview_runs",
    "/api/batches": "create_batch",
    "/api/batches/meta": "revise_batch_meta",
    "/api/results": "add_results",
    "/api/reviews": "add_review",
    "/api/batches/close": "close_batch",
    "/api/ideas": "add_idea",
    "/api/ideas/discard": "discard_idea",
    "/api/drafts": "create_draft",
    "/api/drafts/section": "save_section",
    "/api/drafts/status": "set_draft_status",
    "/api/drafts/export": "export_draft",
}

_STATIC_SUFFIXES = frozenset({".html", ".css", ".js", ".svg"})
_STATIC_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _static_target(url_path: str) -> str | None:
    """把 URL 路径映射到 `webui/` 下的相对文件名；不合法返回 None。

    前端拆成了 `lib/` `views/` `parts/` 多个 ES 模块，写死的字典不再够用。
    但目录服务必须把字典写法「构造上安全」这个性质显式补回来。

    只做词法校验，不碰文件系统：`asset_file()` 在 wheel 安装时返回的是
    importlib.resources 的 Traversable 而不是 Path，能不能 `resolve()`
    取决于安装形态。词法白名单在源码、wheel 与 .app 三种形态下行为一致，
    也不会因为符号链接而出现差异。

    URL 不做百分号解码：`/..%2fweb.py` 因此以字面量形式撞上字符集白名单。
    """
    if url_path in ("/", "/index.html"):
        return "index.html"
    if not url_path.startswith("/"):
        return None
    segments = url_path[1:].split("/")
    for segment in segments:
        if segment in (".", "..") or not _STATIC_SEGMENT.match(segment):
            return None
    if not segments or "." + segments[-1].rsplit(".", 1)[-1].lower() not in _STATIC_SUFFIXES:
        return None
    return "/".join(segments)


def _handler_for(service: GuiService, allowed_hosts=()):
    hosts = {"127.0.0.1", "localhost", "::1", *allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Ariadne/0.2"

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            if not self._host_allowed():
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "不允许的 Host"})
                return
            path = urlsplit(self.path).path
            if path == "/api/state":
                self._json(HTTPStatus.OK, service.state())
                return
            asset = _static_target(path)
            if asset is None:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "页面不存在"})
                return
            resource = asset_file("webui", asset)
            try:
                body = resource.read_bytes()
            except (FileNotFoundError, OSError):
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"界面资源 {asset} 不存在，安装包可能不完整"},
                )
                return
            content_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
            if not self._host_allowed():
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "不允许的 Host"})
                return
            path = urlsplit(self.path).path
            method_name = _POST_ROUTES.get(path)
            if method_name is None:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_000_000:
                    raise GuiInputError("提交内容过大", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise GuiInputError("提交内容应为对象")
                result = getattr(service, method_name)(payload)
            except json.JSONDecodeError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON 格式不正确"})
            except GuiInputError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except Exception:
                # 详细异常留在终端，浏览器不泄露本地路径或调用栈。
                traceback.print_exc()
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": "保存时发生了内部错误，请查看启动终端"},
                )
            else:
                self._json(HTTPStatus.OK, result)

        def _json(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _host_allowed(self) -> bool:
            raw = (self.headers.get("Host") or "").strip().lower()
            if raw.startswith("[") and "]" in raw:
                hostname = raw[1 : raw.index("]")]
            else:
                hostname = raw.rsplit(":", 1)[0]
            return hostname in hosts

        def log_message(self, format, *args):
            # 保留错误日志，隐藏每次轮询的访问噪声。
            return

    return Handler


def make_server(
    project_dir: str | Path, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    service = GuiService(project_dir)
    return ThreadingHTTPServer((host, port), _handler_for(service, {host}))


def serve(
    project_dir: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    server = make_server(project_dir, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in ("0.0.0.0", "::") else actual_host
    url = f"http://{display_host}:{actual_port}/"
    print(f"Ariadne GUI 已启动：{url}")
    print(f"项目：{Path(project_dir).expanduser().resolve()}")
    print("按 Ctrl+C 停止。")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
