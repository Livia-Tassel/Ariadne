/* 唯一的前端状态：来自 /api/state 的快照。前端不持有第二份真相。 */

"use strict";

import { $ } from "./dom.js";
import { api, toast } from "./api.js";

export const store = {
  state: null,
  route: { view: "today", params: new URLSearchParams() },
  scrollTo: null,
  /** 草稿页有未保存改动的节名。跨刷新保护写在 views/draft.js。 */
  dirty: new Set(),
  /** 新批次表单的暂存，切页面回来不丢。 */
  plan: { runs: [], metrics: [], idea: "" },
};

let onChange = () => {};

export const subscribe = (fn) => {
  onChange = fn;
};

export async function refresh() {
  try {
    store.state = await api("/api/state");
    onChange();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("#loading").hidden = true;
  }
}

/** 全部待办，按优先级排好序。首屏与顶栏计数共用这一份，不会各算各的。 */
export function todos() {
  const s = store.state;
  if (!s) return [];
  const items = [];

  for (const batch of s.batches) {
    for (const run of batch.runs) {
      if (run.verdict === "SURPRISE" && !run.closed) {
        items.push({ kind: "待复盘", hot: true, batch, run, act: "写复盘" });
      }
    }
  }
  for (const batch of s.batches) {
    for (const run of batch.runs) {
      if (run.integrity?.includes("result_without_prediction")) {
        items.push({ kind: "预测缺席", hot: true, batch, run, act: "锁预测" });
      }
    }
  }
  // 调研的待办排在意外之后：意外会随时间衰减，论文不会。
  for (const todo of s.survey_todos || []) {
    items.push({ ...todo, survey: todo.survey, act: todo.kind === "待精读" ? "去读" : "写瓶颈" });
  }
  for (const batch of s.batches) {
    for (const run of batch.runs) {
      if (run.verdict === "NOISY") {
        items.push({ kind: "补 seed", batch, run, act: "补 seed" });
      }
    }
  }
  for (const batch of s.batches) {
    if (batch.closed) continue;
    const waiting = batch.runs.filter(
      (run) => run.verdict === "NO_RESULT" || run.verdict === "UNVERIFIED",
    );
    const unpredicted = waiting.filter((run) =>
      run.integrity?.includes("result_without_prediction"),
    ).length;
    const left = waiting.length - unpredicted;
    if (left > 0) items.push({ kind: "等结果", batch, count: left });
  }
  for (const batch of s.batches) {
    if (!batch.closed && batch.close_blockers.length === 0) {
      items.push({ kind: "可收口", batch, act: "写结论" });
    }
  }
  return items;
}

/** 命中率。校准的完整算法在服务端（web._calibration），这里只取一个数
    给顶栏用——前端不持有第二份真相。 */
export function hitRate() {
  const cal = store.state?.calibration;
  return { hit: cal?.hit ?? 0, judged: cal?.judged ?? 0 };
}

export const findBatch = (id) => store.state?.batches.find((batch) => batch.id === id);
