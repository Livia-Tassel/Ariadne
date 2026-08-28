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

/** 最近的落差：只取意外，按批次新到旧。校准记录的种子。 */
export function recentDeviations(limit = 8) {
  const s = store.state;
  if (!s) return [];
  const out = [];
  for (const batch of [...s.batches].reverse()) {
    for (const run of batch.runs) {
      for (const [name, judgement] of Object.entries(run.judgements || {})) {
        if (judgement.deviation === null || judgement.deviation === undefined) continue;
        if (!Number.isFinite(Number(judgement.deviation))) continue;
        out.push({
          batch: batch.id,
          run: run.run,
          metric: name,
          deviation: Number(judgement.deviation),
          hot: judgement.verdict === "SURPRISE",
        });
        if (out.length >= limit) return out;
      }
    }
  }
  return out;
}

/** 命中率：有判定的 run 里落在预期内的比例。 */
export function hitRate() {
  const s = store.state;
  let hit = 0;
  let judged = 0;
  for (const batch of s?.batches || []) {
    for (const run of batch.runs) {
      if (run.verdict === "CONFIRMED" || run.verdict === "SURPRISE") {
        judged += 1;
        if (run.verdict === "CONFIRMED") hit += 1;
      }
    }
  }
  return { hit, judged };
}

export const findBatch = (id) => store.state?.batches.find((batch) => batch.id === id);
