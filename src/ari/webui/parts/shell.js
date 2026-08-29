/* 命令面板与深浅色。两件小事，都只跟外壳有关，不碰领域数据。 */

"use strict";

import { $, $$, html, join } from "../lib/dom.js";
import { store } from "../lib/store.js";

/* ---------- 深浅色 ---------- */

const THEME_KEY = "ariadne-theme";

export function initTheme() {
  let theme = null;
  try {
    theme = localStorage.getItem(THEME_KEY);
  } catch {
    theme = null;
  }
  if (theme !== "dark" && theme !== "light") {
    theme = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
  $("#theme").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* 隐私模式下不记忆，仅本次生效 */
    }
  };
}

/* ---------- 命令面板 ---------- */

const PAGES = [
  { label: "今天", sub: "待办与下一步", href: "#/" },
  { label: "新批次", sub: "设计并锁定预测", href: "#/new" },
  { label: "调研", sub: "领域调研与分层阅读", href: "#/surveys" },
  { label: "批次", sub: "全部批次", href: "#/batches" },
  { label: "账本", sub: "想法与信念", href: "#/ledger" },
  { label: "论文", sub: "草稿列表", href: "#/paper" },
];

const palette = { open: false, rows: [], at: 0 };

function entries() {
  const s = store.state;
  if (!s) return [];
  const rows = PAGES.map((page) => ({ kind: "页面", text: page.label, sub: page.sub, href: page.href }));
  for (const batch of s.batches) {
    rows.push({
      kind: "批次",
      text: batch.hypothesis || batch.id,
      sub: `${batch.id} · ${batch.closed ? "已收口" : "进行中"} · ${batch.research_direction || ""}`,
      href: `#/batch/${encodeURIComponent(batch.id)}`,
    });
  }
  for (const survey of s.surveys) {
    rows.push({
      kind: "调研",
      text: survey.topic,
      sub: `${survey.id} · ${survey.query}`,
      href: `#/survey/${encodeURIComponent(survey.id)}`,
    });
    // 里程碑也进搜索：三个月后你只记得论文名，记不得它属于哪次调研。
    for (const paper of survey.milestones) {
      rows.push({
        kind: "论文",
        text: paper.title,
        sub: `${survey.id} · ${paper.year || "年份不详"} · ${paper.read ? "已精读" : "待精读"}`,
        href: `#/survey/${encodeURIComponent(survey.id)}`,
      });
    }
  }
  for (const idea of s.ideas) {
    rows.push({ kind: "想法", text: idea.text, sub: `${idea.id} · ${idea.status}`, href: "#/ledger" });
  }
  for (const belief of s.beliefs) {
    rows.push({ kind: "信念", text: belief.text, sub: `${belief.id} · ${belief.status}`, href: "#/ledger" });
  }
  for (const draft of s.drafts) {
    rows.push({
      kind: "论文",
      text: draft.title,
      sub: `${draft.id} · ${draft.status}`,
      href: `#/paper/${encodeURIComponent(draft.id)}`,
    });
  }
  return rows;
}

function draw(query) {
  const q = query.trim().toLowerCase();
  const all = entries();
  palette.rows = q
    ? all.filter((row) => `${row.text} ${row.sub}`.toLowerCase().includes(q))
    : all.slice(0, 9);
  palette.at = 0;

  const list = $("#palette-list");
  if (!palette.rows.length) {
    list.innerHTML = html`<p class="p-empty">没有匹配「${query}」的内容</p>`;
    return;
  }
  list.innerHTML = join(
    palette.rows.map(
      (row, index) => html`<button type="button" class="p-item ${index === 0 ? "on" : ""}" data-at="${index}" role="option">
        <span class="p-kind">${row.kind}</span>
        <span><span class="p-text">${row.text}</span><span class="p-sub">${row.sub}</span></span>
      </button>`,
    ),
  );
  for (const item of $$("#palette-list .p-item")) {
    item.onclick = () => pick(Number(item.dataset.at));
  }
}

function move(delta) {
  if (!palette.rows.length) return;
  palette.at = (palette.at + delta + palette.rows.length) % palette.rows.length;
  $$("#palette-list .p-item").forEach((item, index) => item.classList.toggle("on", index === palette.at));
  $(`#palette-list .p-item[data-at="${palette.at}"]`)?.scrollIntoView({ block: "nearest" });
}

function pick(index) {
  const row = palette.rows[index];
  if (!row) return;
  close();
  location.hash = row.href;
}

function open() {
  if (palette.open) return;
  palette.open = true;
  $("#palette-bg").hidden = false;
  const input = $("#palette-input");
  input.value = "";
  draw("");
  input.focus();
}

function close() {
  palette.open = false;
  $("#palette-bg").hidden = true;
}

export function initPalette() {
  $("#open-palette").onclick = open;
  $("#palette-bg").addEventListener("mousedown", (event) => {
    if (event.target === $("#palette-bg")) close();
  });
  $("#palette-input").addEventListener("input", (event) => draw(event.target.value));
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      palette.open ? close() : open();
      return;
    }
    if (!palette.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(palette.at);
    }
  });
}
