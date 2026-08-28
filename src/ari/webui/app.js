/* 入口：路由、顶栏状态、启动。所有状态来自 /api/state。 */

"use strict";

import { $, $$, html } from "./lib/dom.js";
import { toast } from "./lib/api.js";
import { hitRate, refresh, store, subscribe, todos } from "./lib/store.js";
import { initPalette, initTheme } from "./parts/shell.js";
import { renderToday } from "./views/today.js";
import { renderBatches } from "./views/batches.js";
import { renderBatch } from "./views/batch.js";
import { renderPlan } from "./views/plan.js";
import { renderLedger } from "./views/ledger.js";
import { renderPaper } from "./views/paper.js";
import { captureDirty, renderDraft, restoreDirty } from "./views/draft.js";

/* ---------- 路由 ---------- */

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const params = new URLSearchParams(queryPart || "");
  const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);

  if (!parts.length) return { view: "today", params };
  if (parts[0] === "batches") return { view: "batches", params };
  if (parts[0] === "new") return { view: "new", params };
  if (parts[0] === "ledger") return { view: "ledger", params };
  if (parts[0] === "paper") return { view: parts[1] ? "draft" : "paper", draft: parts[1], params };
  if (parts[0] === "batch" && parts[1]) {
    return {
      view: "batch",
      batch: parts[1],
      run: parts[2] === "run" ? parts[3] : null,
      params,
    };
  }
  return { view: "today", params };
}

const TAB_OF = { batch: "batches", new: "batches", draft: "paper" };

const RENDER = {
  today: renderToday,
  batches: renderBatches,
  batch: renderBatch,
  new: renderPlan,
  ledger: renderLedger,
  paper: renderPaper,
  draft: renderDraft,
};

/* ---------- 渲染 ---------- */

function draw() {
  if (!store.state) return;
  const view = store.route.view;
  $$(".view").forEach((node) => node.classList.toggle("on", node.id === `view-${view}`));
  const tab = TAB_OF[view] || view;
  $$(".tab").forEach((node) => node.classList.toggle("on", node.dataset.tab === tab));
  $("#tabs").classList.remove("open");

  drawDocLine();
  RENDER[view]?.();
}

/** 文档行：项目、批次数、命中率、待办数。一行等宽，不是五个瓦片。 */
function drawDocLine() {
  const s = store.state;
  const { hit, judged } = hitRate();
  const pending = todos().filter((item) => item.hot).length;

  $("#doc-line").innerHTML = html`
    <span class="path">${s.project.path}</span>
    <span class="sep">·</span><span>${s.summary.batches} 批次</span>
    <span class="sep">·</span><span>${s.summary.runs} run</span>
    ${judged ? html`<span class="sep">·</span><span>命中 <b>${hit}/${judged}</b></span>` : ""}
    ${pending ? html`<span class="sep">·</span><span class="hot">待处理 <b>${pending}</b></span>` : ""}
  `;

  const count = (id, value, hot = false) => {
    const node = $(id);
    node.textContent = value;
    node.hidden = !value;
    node.className = hot ? "" : "quiet";
  };
  count("#n-todo", pending, true);
  count("#n-batches", s.summary.batches);
  count("#n-ledger", s.summary.open_ideas + s.beliefs.length);
  count("#n-paper", s.summary.drafts);
}

/* ---------- 启动 ---------- */

let lastHash = "";
let restoring = false;

function onHashChange() {
  if (restoring) {
    restoring = false;
    return;
  }
  if (store.dirty.size && !window.confirm("有未保存的章节，离开会丢掉刚写的内容。确定离开吗？")) {
    restoring = true;
    location.hash = lastHash || "#/paper";
    return;
  }
  store.dirty.clear();
  lastHash = location.hash;
  store.route = parseHash();
  store.scrollTo = store.route.run;
  draw();
}

function setup() {
  initTheme();
  initPalette();

  $("#menu").onclick = () => $("#tabs").classList.toggle("open");

  // 刷新会重渲染整页；先把没保存的文字抠出来，渲染完再放回去。
  subscribe(() => {
    const snapshot = captureDirty();
    draw();
    restoreDirty(snapshot);
  });

  window.addEventListener("hashchange", onHashChange);
  window.addEventListener("beforeunload", (event) => {
    if (store.dirty.size) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  // ⌘S 存当前这一节。写作时手会自然去按，不给它就会丢字。
  document.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
    const view = $("#view-draft.on");
    if (!view) return;
    const form =
      (event.target instanceof Element && event.target.closest(".sec")) ||
      $(".sec.dirty", view) ||
      $(".sec", view);
    if (!form) return;
    event.preventDefault();
    form.requestSubmit();
  });

  store.route = parseHash();
  store.scrollTo = store.route.run;
  lastHash = location.hash;
  refresh();
}

document.addEventListener("DOMContentLoaded", setup);

// 桌面壳就绪后才有换目录这个动作；浏览器里这个按钮始终隐藏。
window.addEventListener("pywebviewready", () => {
  const button = $("#switch-project");
  button.hidden = false;
  button.title = "切换研究目录";
  button.onclick = async () => {
    try {
      const result = await window.pywebview.api.choose_project();
      if (!result.ok && !result.cancelled) toast(result.error || "无法打开这个目录", true);
    } catch (error) {
      toast(String(error), true);
    }
  };
});
