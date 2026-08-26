/* ------------------------------------------------------------------
   Ariadne GUI 前端
   以研究流程为主线：工作台 → 批次 → run。
   所有状态来自 /api/state，写入走领域 API，前端不持有第二份真相。
------------------------------------------------------------------ */

"use strict";

const app = {
  state: null,
  route: { view: "dashboard" },
  pendingScroll: null, // 仅 hash 跳转时置位，刷新数据后的重渲染不滚动
  plan: { runs: [], metrics: [], idea: "" },
  dirtySections: new Set(), // 草稿页有未保存改动的节名
};

/* ---------- 基础工具 ---------- */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value = "") => String(value)
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let body;
  try { body = await response.json(); } catch { body = { error: "服务返回了无法读取的内容" }; }
  if (!response.ok) throw new Error(body.error || `请求失败（${response.status}）`);
  return body;
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 3200);
}

function formError(node, error) {
  node.textContent = error?.message || String(error);
  node.hidden = false;
}

/* ---------- 展示辅助 ---------- */

const VERDICT_LABEL = {
  CONFIRMED: "符合预期", SURPRISE: "超出预期", NOISY: "噪声过大",
  NO_RESULT: "等待结果", UNVERIFIED: "待确认",
};
const DIRECTION_LABEL = { higher_better: "越大越好", lower_better: "越小越好" };
const COMPARE_LABEL = { absolute: "绝对", relative: "相对" };

function verdictBadge(verdict, reviewed = false) {
  if (reviewed && verdict === "SURPRISE") return '<span class="badge done">已复盘</span>';
  return `<span class="badge ${esc(verdict)}">${esc(VERDICT_LABEL[verdict] || verdict)}</span>`;
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number) >= 1000 || (Math.abs(number) > 0 && Math.abs(number) < 0.001)) {
    return number.toExponential(3);
  }
  return Number(number.toPrecision(5)).toString();
}

function fmtPrediction(value) {
  return Array.isArray(value) ? `${fmt(value[0])} ~ ${fmt(value[1])}` : fmt(value);
}

function fmtActual(agg) {
  if (!agg) return "—";
  const spread = agg.sd === null || agg.sd === undefined ? "" : ` ± ${fmt(agg.sd)}`;
  return `${fmt(agg.mean)}${spread} <small class="muted">n=${agg.n}</small>`;
}

function dateLabel(ts) {
  if (!ts) return "";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function metricPredictionLines(run) {
  const metrics = run.prediction?.metrics || {};
  return `<div class="mlines">${Object.entries(metrics).map(([name, value]) =>
    `<span><b>${esc(name)}</b><span class="num">${esc(fmtPrediction(value))}</span></span>`).join("")}</div>`;
}

function metricActualLines(run) {
  const metrics = run.prediction?.metrics || {};
  const names = Object.keys(metrics).length ? Object.keys(metrics) : Object.keys(run.aggregates || {});
  return `<div class="mlines">${names.map(name =>
    `<span><b>${esc(name)}</b><span class="num">${fmtActual(run.aggregates?.[name])}</span></span>`).join("") || '<span class="muted">—</span>'}</div>`;
}

function emptyState({ icon, title, body, cta, href }) {
  return `<div class="card empty">
    <div class="empty-ico">${icon}</div>
    <h3>${esc(title)}</h3>
    <p>${esc(body)}</p>
    ${cta ? `<a class="btn primary" href="${href}">${esc(cta)}</a>` : ""}
  </div>`;
}

function runSeeds(run) {
  const seeds = new Set();
  for (const samples of Object.values(run.samples || {})) {
    for (const seed of Object.keys(samples)) seeds.add(Number(seed));
  }
  return [...seeds].sort((a, b) => a - b);
}

function nextSeed(run) {
  const seeds = runSeeds(run);
  return seeds.length ? Math.max(...seeds) + 1 : 0;
}

/* ---------- 路由 ---------- */

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const params = new URLSearchParams(queryPart || "");
  const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  if (!parts.length) return { view: "dashboard", params };
  if (parts[0] === "experiments") return { view: "experiments", params };
  if (parts[0] === "beliefs") return { view: "beliefs", params };
  if (parts[0] === "ideas") return { view: "ideas", params };
  if (parts[0] === "paper") {
    return { view: parts[1] ? "draft" : "paper", draft: parts[1], params };
  }
  if (parts[0] === "new") return { view: "new", params };
  if (parts[0] === "batch" && parts[1]) {
    return { view: "batch", batch: parts[1], run: parts[2] === "run" ? parts[3] : null, params };
  }
  return { view: "dashboard", params };
}

function go(hash) { location.hash = hash; }

const PAGE_META = {
  dashboard: ["工作台", "从一个想法，到一篇论文——全程在这里"],
  ideas: ["想法", "研究从念头开始。先把它留住，再决定要不要验证"],
  experiments: ["实验批次", "每一个批次是一次假设的检验"],
  new: ["新实验", "在开跑之前，先写下你对结果的判断"],
  beliefs: ["信念账本", "实验会结束，能指导下一次预测的判断会留下来"],
  paper: ["论文", "实验结束时，材料已经在这里了"],
  draft: ["论文草稿", ""],
};

/* ---------- 渲染调度 ---------- */

function render() {
  app.route = parseHash();
  app.pendingScroll = app.route.run;
  renderCurrentView();
}

function renderCurrentView() {
  const view = app.route.view;
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${view}`));
  const navKey = view === "batch" ? "experiments" : view === "draft" ? "paper" : view;
  $$(".nav-link").forEach(node => node.classList.toggle("active", node.dataset.nav === navKey));
  $("#sidebar").classList.remove("open");

  if (view === "dashboard") renderDashboard();
  else if (view === "ideas") renderIdeas();
  else if (view === "experiments") renderExperiments();
  else if (view === "batch") renderBatch();
  else if (view === "new") renderPlanView();
  else if (view === "beliefs") renderBeliefs();
  else if (view === "paper") renderPaper();
  else if (view === "draft") renderDraft();
}

function updateNavCounts() {
  const s = app.state;
  const set = (id, value) => {
    const node = $(id);
    node.textContent = value;
    node.hidden = !value;
  };
  set("#nav-ideas", s.summary.open_ideas);
  set("#nav-batches", s.summary.batches);
  set("#nav-beliefs", s.beliefs.length);
  set("#nav-paper", s.summary.drafts);
}

async function refresh() {
  const dirtySnapshot = captureDirtyDraft();
  try {
    app.state = await api("/api/state");
    $("#project-path").textContent = app.state.project.path;
    updateNavCounts();
    renderCurrentView();
    restoreDirtyDraft(dirtySnapshot);
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("#loading").hidden = true;
  }
}

/* ---------- 工作台 ---------- */

function computeActions() {
  const s = app.state;
  const actions = [];
  if (s.pending_reviews.length) {
    const first = s.pending_reviews[0];
    actions.push({
      tone: "surprise", icon: "!",
      title: `${s.pending_reviews.length} 条 SURPRISE 待复盘`,
      desc: "意外是信息量最大的结果，先解释它们",
      href: `#/batch/${encodeURIComponent(first.batch)}/run/${encodeURIComponent(first.run)}`,
    });
  }
  const closable = s.batches.filter(batch => !batch.closed && batch.close_blockers.length === 0);
  if (closable.length) {
    actions.push({
      tone: "ok", icon: "✓",
      title: `${closable.length} 个批次可以收口`,
      desc: "结果齐了、SURPRISE 已复盘，写下批次结论",
      href: `#/batch/${encodeURIComponent(closable[0].id)}`,
    });
  }
  const noisy = [];
  for (const batch of s.batches) {
    for (const run of batch.runs) {
      if (run.verdict === "NOISY") noisy.push({ batch: batch.id, run: run.run });
    }
  }
  if (noisy.length) {
    actions.push({
      tone: "noisy", icon: "~",
      title: `${noisy.length} 个 run 噪声过大`,
      desc: "seed 间方差已超过判定分辨率，需要补 seed",
      href: `#/batch/${encodeURIComponent(noisy[0].batch)}/run/${encodeURIComponent(noisy[0].run)}`,
    });
  }
  if (!actions.length) {
    const waiting = [];
    for (const batch of s.batches) {
      if (batch.closed) continue;
      for (const run of batch.runs) {
        if (run.verdict === "NO_RESULT" || run.verdict === "UNVERIFIED") waiting.push({ batch: batch.id });
      }
    }
    if (waiting.length) {
      actions.push({
        tone: "neutral", icon: "◷",
        title: `${waiting.length} 个 run 还在等结果`,
        desc: "实验跑完后回来录入，判定会自动更新",
        href: `#/batch/${encodeURIComponent(waiting[0].batch)}`,
      });
    }
  }
  if (!actions.length) {
    if (!s.batches.length && s.summary.open_ideas) {
      actions.push({
        tone: "neutral", icon: "◎",
        title: `${s.summary.open_ideas} 个想法等着被验证`,
        desc: "把一个想法推进成实验批次——开跑前锁定预测",
        href: "#/ideas",
      });
    }
    if (s.batches.length && s.batches.every(batch => batch.closed) && !s.summary.drafts) {
      actions.push({
        tone: "ok", icon: "✎",
        title: "实验都已收口，可以开始写论文了",
        desc: "批次结论与信念账本就是最原始的讨论材料",
        href: "#/paper",
      });
    }
  }
  return actions;
}

function renderDashboard() {
  const s = app.state;
  const [title, sub] = PAGE_META.dashboard;
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;

  const notices = [
    ...s.parse_errors.map(item => `runs.jsonl 第 ${item.line_no} 行：${item.reason}`),
    ...s.warnings,
  ];
  $("#dash-actions").innerHTML = notices.length
    ? `<div class="notice">${notices.map(esc).join("<br>")}</div>` + actionsHtml(computeActions())
    : actionsHtml(computeActions());

  $("#dash-stats").innerHTML = `
    <div class="stat"><span>想法</span><strong>${s.summary.ideas}</strong><small>${s.summary.open_ideas} 个待验证</small></div>
    <div class="stat"><span>实验批次</span><strong>${s.summary.batches}</strong><small>${s.summary.runs} 个 run</small></div>
    <div class="stat accent"><span>待复盘</span><strong>${s.summary.pending_reviews}</strong><small>最有信息量</small></div>
    <div class="stat"><span>信念</span><strong>${s.beliefs.length}</strong><small>持续演化</small></div>
    <div class="stat"><span>论文草稿</span><strong>${s.summary.drafts}</strong><small>素材自然沉淀</small></div>`;

  const target = $("#dash-batches");
  if (!s.batches.length) {
    if (!s.summary.ideas) {
      target.innerHTML = emptyState({
        icon: "◎",
        title: "从一个想法开始",
        body: "研究从念头开始：先把它记下来，再推进成实验——开跑前锁定预测，实验的差异才会变成知识，最后沉淀成论文。",
        cta: "记下第一个想法",
        href: "#/ideas",
      });
      return;
    }
    target.innerHTML = emptyState({
      icon: "⌁",
      title: "想法已经在账本上了",
      body: "挑一个最值得追的，把它推进成实验批次：设计变量与指标，开跑前锁定预测。",
      cta: "把想法变成实验",
      href: "#/ideas",
    });
    return;
  }
  target.innerHTML = s.batches.slice(0, 5).map(batchRowHtml).join("");
}

function actionsHtml(actions) {
  if (!actions.length) {
    return `<div class="actions"><div class="action neutral">
      <span class="action-ico">✓</span>
      <div class="action-body"><strong>没有需要立刻处理的事</strong><small>去跑实验吧——回来录入结果，判定会自动更新</small></div>
    </div></div>`;
  }
  return `<div class="actions">${actions.map(action => `
    <a class="action ${action.tone}" href="${action.href}">
      <span class="action-ico">${esc(action.icon)}</span>
      <div class="action-body"><strong>${esc(action.title)}</strong><small>${esc(action.desc)}</small></div>
      <span class="action-go">→</span>
    </a>`).join("")}</div>`;
}

/* ---------- 批次列表 ---------- */

function batchRowHtml(batch) {
  const runs = batch.runs;
  const withResults = runs.filter(run => Object.keys(run.aggregates || {}).length).length;
  const pending = runs.filter(run => run.verdict === "SURPRISE" && !run.closed).length;
  const meta = [
    `${runs.length} runs`,
    withResults ? `${withResults} 有结果` : null,
    pending ? `${pending} 待复盘` : null,
  ].filter(Boolean).join(" · ");
  return `<a class="batch-row" href="#/batch/${encodeURIComponent(batch.id)}">
    <div class="batch-row-main">
      <div class="batch-row-top">
        <span class="batch-id">${esc(batch.id)}</span>
        ${batch.closed ? '<span class="badge done">已收口</span>' : '<span class="badge live">进行中</span>'}
      </div>
      <p class="batch-hyp">${esc(batch.hypothesis)} <small>· ${esc(batch.research_direction || "")}</small></p>
    </div>
    <div class="batch-row-meta"><span>${esc(meta)}</span>${pending ? verdictBadge("SURPRISE") : ""}</div>
  </a>`;
}

function renderExperiments() {
  const [title, sub] = PAGE_META.experiments;
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  const target = $("#experiment-list");
  if (!app.state.batches.length) {
    target.innerHTML = emptyState({
      icon: "▤",
      title: "还没有实验批次",
      body: "批次是一次假设检验的完整记录：设计、预测、结果与复盘。",
      cta: "设计第一个实验",
      href: "#/new",
    });
    return;
  }
  target.innerHTML = app.state.batches.map(batchRowHtml).join("");
}

/* ---------- 想法 ---------- */

const IDEA_STATUS_BADGE = {
  "待验证": "idea-open",
  "实验中": "live",
  "已验证": "done",
  "已放弃": "retired",
};

function ideaCardHtml(idea) {
  const badge = `<span class="badge ${IDEA_STATUS_BADGE[idea.status] || "idea-open"}">${esc(idea.status)}</span>`;
  const batches = idea.batches.length
    ? `<div class="idea-batches">${idea.batches.map(id =>
        `<a class="chip" href="#/batch/${encodeURIComponent(id)}">${esc(id)}</a>`).join("")}</div>`
    : "";
  const motivation = idea.motivation ? `<p class="idea-motivation">${esc(idea.motivation)}</p>` : "";
  const reason = idea.discarded && idea.discard_reason
    ? `<p class="idea-motivation muted">放弃原因：${esc(idea.discard_reason)}</p>` : "";

  let actions = "";
  if (!idea.discarded) {
    actions = `<div class="idea-actions">
      <a class="btn primary sm" href="#/new?idea=${encodeURIComponent(idea.id)}">立项为实验 →</a>
      <button type="button" class="btn ghost sm idea-discard" data-idea="${esc(idea.id)}">放弃</button>
    </div>`;
  }

  return `<article class="card idea-card ${idea.discarded ? "retired" : ""}" data-idea="${esc(idea.id)}">
    <div class="idea-top">${badge}<span class="belief-id">${esc(idea.id)}</span></div>
    <h3>${esc(idea.text)}</h3>
    ${motivation}
    ${batches}
    ${reason}
    ${actions}
    <form class="idea-discard-form" hidden>
      <div class="field">
        <label>为什么放弃？<span class="muted">（可留空，留给以后的自己）</span></label>
        <input class="discard-reason" placeholder="例如：文献里已有系统比较" />
      </div>
      <div class="form-actions">
        <button type="submit" class="btn danger sm">确认放弃</button>
        <button type="button" class="btn ghost sm discard-cancel">再想想</button>
      </div>
      <div class="form-error" hidden></div>
    </form>
  </article>`;
}

function renderIdeas() {
  const [title, sub] = PAGE_META.ideas;
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;

  const target = $("#idea-list");
  const ideas = app.state.ideas;
  if (!ideas.length) {
    target.innerHTML = emptyState({
      icon: "◎",
      title: "想法账本还是空的",
      body: "阅读、讨论、散步时冒出来的念头都值得先记下来——不着急判断值不值得做。",
      cta: "在上方记下第一个想法",
      href: "#/ideas",
    });
    return;
  }
  const active = ideas.filter(idea => !idea.discarded);
  const retired = ideas.filter(idea => idea.discarded);
  target.innerHTML = `
    <div class="belief-section">
      <div class="section-head"><h2>在追（${active.length}）</h2></div>
      <div class="belief-grid">${active.map(ideaCardHtml).join("") || '<p class="muted" style="margin:0">暂无在追的想法。</p>'}</div>
    </div>
    ${retired.length ? `<div class="belief-section">
      <div class="section-head"><h2>已放弃（${retired.length}）</h2></div>
      <div class="belief-grid">${retired.map(ideaCardHtml).join("")}</div>
    </div>` : ""}`;
  bindIdeaCards();
}

function bindIdeaCards() {
  $$("#idea-list .idea-discard").forEach(button => {
    button.onclick = () => {
      const card = button.closest(".idea-card");
      $(".idea-actions", card).hidden = true;
      $(".idea-discard-form", card).hidden = false;
      $(".discard-reason", card).focus();
    };
  });
  $$("#idea-list .discard-cancel").forEach(button => {
    button.onclick = () => {
      const card = button.closest(".idea-card");
      $(".idea-discard-form", card).hidden = true;
      $(".idea-actions", card).hidden = false;
    };
  });
  $$("#idea-list .idea-discard-form").forEach(form => {
    form.onsubmit = async event => {
      event.preventDefault();
      const errorNode = $(".form-error", form);
      errorNode.hidden = true;
      try {
        await api("/api/ideas/discard", {
          method: "POST",
          body: JSON.stringify({
            idea: form.closest(".idea-card").dataset.idea,
            reason: $(".discard-reason", form).value,
          }),
        });
        toast("想法已放入「已放弃」——这不是删除，以后还能翻到");
        await refresh();
      } catch (error) {
        formError(errorNode, error);
      }
    };
  });
}

/* ---------- 批次详情 ---------- */

function renderBatch() {
  const { batch: batchId, run: runKey } = app.route;
  const batch = app.state.batches.find(item => item.id === batchId);
  const target = $("#batch-detail");

  if (!batch) {
    $("#page-title").textContent = "批次不存在";
    $("#page-sub").textContent = "它可能属于另一个研究目录";
    target.innerHTML = emptyState({
      icon: "?", title: "找不到这个批次",
      body: "它可能已被移动或属于另一个项目目录。", cta: "回到工作台", href: "#/",
    });
    return;
  }

  $("#page-title").textContent = `${batch.id} · ${batch.research_direction || "实验批次"}`;
  $("#page-sub").textContent = dateLabel(batch.opened_at);

  const runs = batch.runs;
  const withResults = runs.filter(run => Object.keys(run.aggregates || {}).length).length;
  const pending = runs.filter(run => run.verdict === "SURPRISE" && !run.closed).length;

  const dimChips = Object.entries(batch.dimensions || {})
    .map(([name, values]) => `<span class="chip">${esc(name)} <b>${values.length}</b> 取值</span>`).join("");
  const ideaChip = batch.idea
    ? (() => {
        const idea = app.state.ideas.find(item => item.id === batch.idea);
        const label = idea ? idea.text : batch.idea;
        return `<a class="chip idea-chip" href="#/ideas" title="${esc(label)}">◎ 想法 ${esc(batch.idea)}</a>`;
      })()
    : "";
  const specChips = Object.entries(batch.metric_specs || {})
    .map(([name, spec]) => `<span class="chip"><b>${esc(name)}</b> ${DIRECTION_LABEL[spec.direction] || spec.direction} · ${COMPARE_LABEL[spec.compare] || spec.compare} ${fmt(spec.tolerance)}</span>`).join("");

  target.innerHTML = `
    <article class="card batch-head">
      <a class="crumb" href="#/experiments">← 实验批次</a>
      <div class="batch-head-top">
        <div>
          <h2>${esc(batch.hypothesis)}</h2>
          <p class="batch-direction">${esc(batch.research_direction || "")}</p>
          <div class="batch-chips">${ideaChip}${dimChips}${specChips}</div>
        </div>
        <div class="head-badges">
          ${batch.closed ? '<span class="badge done">已收口</span>' : '<span class="badge live">进行中</span>'}
          ${pending ? verdictBadge("SURPRISE") : ""}
        </div>
      </div>
      <div class="pipeline">
        <span class="pipe-seg done">预测 <b>${runs.length}</b></span><span class="pipe-arrow">›</span>
        <span class="pipe-seg ${withResults === runs.length && runs.length ? "done" : withResults ? "live" : ""}">结果 <b>${withResults}/${runs.length}</b></span><span class="pipe-arrow">›</span>
        <span class="pipe-seg ${pending ? "hot" : "done"}">待复盘 <b>${pending}</b></span><span class="pipe-arrow">›</span>
        <span class="pipe-seg ${batch.closed ? "done" : batch.close_blockers.length ? "" : "live"}">${batch.closed ? "已收口" : "收口"}</span>
      </div>
      ${rankingNoteHtml(batch)}
      ${batch.info_signal ? `<div class="notice">${esc(batch.info_signal)}</div>` : ""}
      ${batch.warnings?.length ? `<div class="notice">${batch.warnings.map(esc).join("<br>")}</div>` : ""}
    </article>

    ${batchChartsHtml(batch)}

    <div class="table-wrap">
      <table class="table">
        <thead><tr><th style="width:26%">Run</th><th>预测</th><th>实测</th><th>判定</th><th></th></tr></thead>
        <tbody id="runs-body">${runs.map(run => runRowHtml(batch, run, run.run === runKey)).join("")}</tbody>
      </table>
    </div>

    ${closeCardHtml(batch)}`;

  bindRunRows(batch);
  bindCloseForm(batch);
  if (app.pendingScroll) {
    const row = $(`#runs-body tr.run-row[data-run="${CSS.escape(app.pendingScroll)}"]`);
    if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
    app.pendingScroll = null;
  }
}

/* ---------- 预测 vs 实测图 ---------- */

function metricVerdictOf(run, name) {
  return run.judgements?.[name]?.verdict || run.verdict || "NO_RESULT";
}

function chartScale(runs, name) {
  let lo = Infinity;
  let hi = -Infinity;
  const push = value => {
    const number = Number(value);
    if (!Number.isFinite(number)) return;
    lo = Math.min(lo, number);
    hi = Math.max(hi, number);
  };
  for (const run of runs) {
    const pred = run.prediction?.metrics?.[name];
    if (Array.isArray(pred)) pred.forEach(push);
    else push(pred);
    const agg = run.aggregates?.[name];
    if (agg) push(agg.mean);
    for (const value of Object.values(run.samples?.[name] || {})) push(value);
  }
  if (lo === Infinity) return null;
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  return { lo: lo - pad, hi: hi + pad };
}

function metricChartHtml(batch, name) {
  const runs = batch.runs;
  const scale = chartScale(runs, name);
  if (!scale) return "";
  const span = scale.hi - scale.lo;
  const pct = value => Math.min(Math.max(((Number(value) - scale.lo) / span) * 100, 0), 100);

  const grid = [25, 50, 75].map(x => `<i class="grid-line" style="left:${x}%"></i>`).join("");
  const rows = runs.map(run => {
    const pred = run.prediction?.metrics?.[name];
    const agg = run.aggregates?.[name];
    const verdict = metricVerdictOf(run, name);
    const parts = [grid];
    if (pred !== undefined && pred !== null) {
      const [pLo, pHi] = Array.isArray(pred) ? pred : [pred, pred];
      const left = pct(pLo);
      const width = Math.max(pct(pHi) - left, 0.8);
      parts.push(`<i class="pred-band" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></i>`);
      if (width > 3) parts.push(`<i class="pred-mid" style="left:${(left + width / 2).toFixed(2)}%"></i>`);
    }
    if (agg) {
      if (agg.sd && agg.sd > 0) {
        const sdLo = pct(agg.mean - agg.sd);
        const sdHi = pct(agg.mean + agg.sd);
        parts.push(`<i class="actual-spread v-${verdict}" style="left:${sdLo.toFixed(2)}%;width:${Math.max(sdHi - sdLo, 0.6).toFixed(2)}%"></i>`);
      }
      for (const value of Object.values(run.samples?.[name] || {})) {
        parts.push(`<i class="seed-dot" style="left:${pct(value).toFixed(2)}%"></i>`);
      }
      parts.push(`<i class="actual-dot v-${verdict}" style="left:${pct(agg.mean).toFixed(2)}%" title="${esc(fmt(agg.mean))}"></i>`);
    }
    return `<div class="chart-row">
      <span class="chart-label" title="${esc(run.run)}">${esc(run.run)}</span>
      <div class="chart-track" role="img" aria-label="${esc(run.run)} 的 ${esc(name)} 预测与实测对比">${parts.join("")}</div>
    </div>`;
  }).join("");

  const spec = batch.metric_specs?.[name] || {};
  const specText = `${DIRECTION_LABEL[spec.direction] || ""}${spec.compare ? ` · ${COMPARE_LABEL[spec.compare] || spec.compare} · 容差 ${fmt(spec.tolerance)}` : ""}`;

  return `<article class="card chart-card">
    <div class="chart-head">
      <h3>${esc(name)}</h3>
      <span class="chart-spec muted">${esc(specText)}</span>
      <span class="chart-legend"><i class="pred-band"></i>预测区间<i class="actual-dot"></i>实测均值</span>
    </div>
    <div class="chart-rows">${rows}</div>
    <div class="chart-axis"><span>${fmt(scale.lo)}</span><span>${fmt((scale.lo + scale.hi) / 2)}</span><span>${fmt(scale.hi)}</span></div>
  </article>`;
}

function batchChartsHtml(batch) {
  const names = Object.keys(batch.runs[0]?.prediction?.metrics || {});
  if (!names.length) return "";
  return names.map(name => metricChartHtml(batch, name)).join("");
}

function rankingNoteHtml(batch) {
  const ranking = batch.ranking;
  if (!ranking) return "";
  const flips = ranking.real_flips.map(pair => `预期 <b>${esc(pair[0])}</b> 优于 <b>${esc(pair[1])}</b>，实测相反`);
  const noisy = ranking.noisy_flips.map(pair => `预期 <b>${esc(pair[0])}</b> 优于 <b>${esc(pair[1])}</b>，差异落在噪声内`);
  return `<div class="ranking-note ${esc(ranking.verdict)}">
    相对排序判定：${esc(VERDICT_LABEL[ranking.verdict] || ranking.verdict)}
    ${[...flips, ...noisy].length ? `<ul>${[...flips, ...noisy].map(line => `<li>${line}</li>`).join("")}</ul>` : ""}
  </div>`;
}

function runRowHtml(batch, run, expanded) {
  const metrics = Object.keys(run.prediction?.metrics || {});
  return `<tr class="run-row ${expanded ? "expanded" : ""}" data-run="${esc(run.run)}">
    <td><span class="run-key">${esc(run.run)}</span>${run.revised ? '<br><small class="muted">预测已修订</small>' : ""}</td>
    <td>${metricPredictionLines(run)}</td>
    <td>${metrics.length ? metricActualLines(run) : '<span class="muted">—</span>'}</td>
    <td>${verdictBadge(run.verdict, run.closed)}</td>
    <td><span class="run-expand">▶</span></td>
  </tr>
  ${expanded ? `<tr class="run-detail"><td colspan="5">${runPanelHtml(batch, run)}</td></tr>` : ""}`;
}

function runPanelHtml(batch, run) {
  const metrics = Object.keys(run.prediction?.metrics || {});
  const detailRows = metrics.map(name => {
    const judgement = run.judgements?.[name];
    const deviation = judgement && Number.isFinite(Number(judgement.deviation)) && judgement.deviation !== null
      ? fmt(judgement.deviation) : (judgement?.note || "—");
    return `<tr>
      <td><b>${esc(name)}</b></td>
      <td class="num">${esc(fmtPrediction(run.prediction.metrics[name]))}</td>
      <td class="num">${fmtActual(run.aggregates?.[name])}</td>
      <td class="num">${esc(deviation)}</td>
      <td>${judgement ? verdictBadge(judgement.verdict) : '<span class="badge NO_RESULT">未判定</span>'}</td>
    </tr>`;
  }).join("");

  const seeds = runSeeds(run);
  const seedsLine = seeds.length
    ? `<p class="seeds-line">已录入 seed：${seeds.map(seed => `<b>${seed}</b>`).join("、")}</p>`
    : '<p class="seeds-line muted">还没有结果——实验跑完后在这里录入。</p>';

  const rationale = run.prediction?.rationale
    ? `<div class="panel-block"><h4>当初的理由</h4>
        <div class="reflection-box"><p>${esc(run.prediction.rationale)}</p>
        <p class="muted" style="margin-top:6px">置信度：${{ low: "低", medium: "中", high: "高" }[run.prediction.confidence] || run.prediction.confidence}</p></div></div>`
    : "";

  const integrity = run.integrity?.length
    ? `<div class="notice problem">${run.integrity.map(esc).join("<br>")}</div>` : "";

  let action = "";
  if (run.verdict === "SURPRISE" && !run.closed) {
    action = reviewFormHtml(run);
  } else if (!Object.keys(run.aggregates || {}).length || ["NO_RESULT", "UNVERIFIED", "NOISY"].includes(run.verdict)) {
    action = resultFormHtml(batch, run, seeds);
  }

  let reflection = "";
  if (run.closed && run.reflection) {
    reflection = `<div class="panel-block"><h4>复盘记录</h4><div class="reflection-box">
      <h5>原因</h5><p>${esc(run.reflection.cause || "")}</p>
      ${run.reflection.next ? `<h5 style="margin-top:10px">下一步</h5><p>${esc(run.reflection.next)}</p>` : ""}
    </div></div>`;
  }

  return `<div class="run-panel" data-run="${esc(run.run)}">
    <div class="panel-block">
      <h4>指标明细</h4>
      <table class="mini-table"><thead><tr><th>指标</th><th>预测</th><th>实测</th><th>偏差</th><th>判定</th></tr></thead><tbody>${detailRows}</tbody></table>
    </div>
    ${seedsLine ? `<div class="panel-block">${seedsLine}</div>` : ""}
    ${integrity}
    ${rationale}
    ${action}
    ${reflection}
  </div>`;
}

/* ---------- 内联结果表单 ---------- */

function resultFormHtml(batch, run, seeds) {
  return `<form class="inline-form result-form" data-run="${esc(run.run)}">
    <div class="inline-grid">
      <div class="field narrow">
        <label>Seed</label>
        <input class="seed-input" type="number" step="1" value="${nextSeed(run)}" required />
      </div>
      ${batch.metrics.map(name => `<div class="field">
        <label>${esc(name)}</label>
        <input class="metric-input" data-metric="${esc(name)}" inputmode="decimal" placeholder="实测值" required />
      </div>`).join("")}
      <button class="btn primary sm" type="submit">保存结果</button>
    </div>
    <div class="form-error" hidden></div>
    <p class="seeds-line muted">${seeds.length ? "保存后自动重新判定；已有 seed 不会被覆盖。" : "保存后自动重新判定。"}</p>
  </form>`;
}

function bindRunRows() {
  $$("#runs-body tr.run-row").forEach(row => {
    row.onclick = () => {
      const batchId = app.route.batch;
      const runKey = row.dataset.run;
      if (app.route.run === runKey) go(`#/batch/${encodeURIComponent(batchId)}`);
      else go(`#/batch/${encodeURIComponent(batchId)}/run/${encodeURIComponent(runKey)}`);
    };
  });
  $$("#runs-body form.result-form").forEach(form => {
    form.onsubmit = async event => {
      event.preventDefault();
      const errorNode = $(".form-error", form);
      errorNode.hidden = true;
      const button = $("button[type=submit]", form);
      button.disabled = true;
      const metrics = Object.fromEntries($$(".metric-input", form).map(input => [input.dataset.metric, input.value.trim()]));
      try {
        const result = await api("/api/results", {
          method: "POST",
          body: JSON.stringify({
            batch: app.route.batch,
            rows: [{ run: form.dataset.run, seed: $(".seed-input", form).value, metrics }],
          }),
        });
        toast(`已保存 ${result.written} 条结果，判定已更新`);
        await refresh();
      } catch (error) {
        formError(errorNode, error);
      } finally {
        button.disabled = false;
      }
    };
  });
  $$("#runs-body form.review-form").forEach(form => {
    form.onsubmit = async event => {
      event.preventDefault();
      const errorNode = $(".form-error", form);
      errorNode.hidden = true;
      const button = $("button[type=submit]", form);
      button.disabled = true;
      const changes = Object.fromEntries($$("select[data-belief]", form).map(select => [select.dataset.belief, select.value]));
      try {
        await api("/api/reviews", {
          method: "POST",
          body: JSON.stringify({
            batch: app.route.batch,
            run: form.dataset.run,
            cause: $(".review-cause", form).value,
            next: $(".review-next", form).value,
            beliefs_added: $(".review-beliefs", form).value,
            belief_changes: changes,
          }),
        });
        toast("复盘已保存，这次意外已进入知识记录");
        await refresh();
      } catch (error) {
        formError(errorNode, error);
      } finally {
        button.disabled = false;
      }
    };
  });
}

/* ---------- 内联复盘表单 ---------- */

function beliefChangeRows() {
  const active = app.state.beliefs.filter(belief => !belief.refuted);
  if (!active.length) return "";
  return `<div class="panel-block"><h4>这次结果改变了哪些已有信念？</h4><div class="belief-fields">
    ${active.map(belief => `<div class="belief-change">
      <span>${esc(belief.text)} <small>${esc(belief.id)}</small></span>
      <select data-belief="${esc(belief.id)}">
        <option value="unchanged">没有改变</option>
        <option value="reinforced">得到加强</option>
        <option value="weakened">有所动摇</option>
        <option value="refuted">被推翻</option>
      </select>
    </div>`).join("")}</div></div>`;
}

function reviewFormHtml(run) {
  return `<form class="inline-form review-form" data-run="${esc(run.run)}">
    <div class="panel-block" style="margin:0"><h4>写下复盘</h4>
      <div class="field">
        <label>你认为为什么会这样？</label>
        <textarea class="review-cause" rows="3" placeholder="如果还不知道，就写下准备如何排查。" required></textarea>
      </div>
      <div class="field">
        <label>下一步准备做什么？<span class="muted">（可留空）</span></label>
        <textarea class="review-next" rows="2"></textarea>
      </div>
      <div class="field">
        <label>这次之后新相信了什么？<span class="muted">（一行一条，可留空）</span></label>
        <textarea class="review-beliefs" rows="2"></textarea>
      </div>
    </div>
    ${beliefChangeRows()}
    <div class="form-actions"><button class="btn primary sm" type="submit">保存复盘</button></div>
    <div class="form-error" hidden></div>
  </form>`;
}

/* ---------- 批次收口 ---------- */

function closeCardHtml(batch) {
  if (batch.closed) {
    return `<div class="card close-card" style="margin-top:16px">
      <h3>批次收口</h3><p>已写下批次级结论，这个批次的闭环完成。</p>
    </div>`;
  }
  if (batch.close_blockers.length) {
    return `<div class="card close-card" style="margin-top:16px">
      <h3>批次收口</h3><p>还差这几件事：</p>
      <ul class="blockers">${batch.close_blockers.map(item => `<li>${esc(item)}</li>`).join("")}</ul>
    </div>`;
  }
  return `<div class="card close-card" style="margin-top:16px">
    <h3>批次收口</h3><p>所有 run 已有可判定结果、SURPRISE 已复盘。写下这一批整体学到了什么。</p>
    <form class="close-form" data-batch="${esc(batch.id)}">
      <div class="field">
        <label>这一批整体学到了什么？</label>
        <textarea class="close-cause" rows="3" required></textarea>
      </div>
      <div class="field">
        <label>下一批准备验证什么？<span class="muted">（可留空）</span></label>
        <textarea class="close-next" rows="2"></textarea>
      </div>
      <div class="field">
        <label>新增信念<span class="muted">（一行一条，可留空）</span></label>
        <textarea class="close-beliefs" rows="2"></textarea>
      </div>
      ${beliefChangeRows()}
      <div class="form-actions"><button class="btn primary" type="submit">收口批次</button></div>
      <div class="form-error" hidden></div>
    </form>
  </div>`;
}

function bindCloseForm() {
  const form = $("#batch-detail .close-form");
  if (!form) return;
  form.onsubmit = async event => {
    event.preventDefault();
    const errorNode = $(".form-error", form);
    errorNode.hidden = true;
    const button = $("button[type=submit]", form);
    button.disabled = true;
    const changes = Object.fromEntries($$("select[data-belief]", form).map(select => [select.dataset.belief, select.value]));
    try {
      await api("/api/batches/close", {
        method: "POST",
        body: JSON.stringify({
          batch: app.route.batch,
          cause: $(".close-cause", form).value,
          next: $(".close-next", form).value,
          beliefs_added: $(".close-beliefs", form).value,
          belief_changes: changes,
        }),
      });
      toast(`批次 ${app.route.batch} 已收口`);
      await refresh();
    } catch (error) {
      formError(errorNode, error);
    } finally {
      button.disabled = false;
    }
  };
}

/* ---------- 新实验 ---------- */

function renderPlanView() {
  const [title, sub] = PAGE_META.new;
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;

  const ideaId = app.route.params?.get("idea") || "";
  if (ideaId && app.plan.idea !== ideaId) {
    const idea = app.state.ideas.find(item => item.id === ideaId);
    if (idea && !$("#hypothesis").value.trim()) {
      $("#hypothesis").value = idea.text;
      app.plan.idea = idea.id;
      renderIdeaLinkChip(idea);
    }
  } else if (!ideaId && app.plan.idea) {
    app.plan.idea = "";
    renderIdeaLinkChip(null);
  }

  if (!app.plan.runs.length) {
    $("#prediction-panel").hidden = true;
    setPlanStep("design");
  }
}

function renderIdeaLinkChip(idea) {
  const chip = $("#idea-link");
  if (!idea) {
    chip.hidden = true;
    return;
  }
  chip.hidden = false;
  chip.innerHTML = `<div class="form-head spread" style="margin:0">
    <div>
      <h3 style="margin:0">来自想法 ${esc(idea.id)}</h3>
      <p style="margin:4px 0 0">${esc(idea.text)}${idea.motivation ? `——${esc(idea.motivation)}` : ""}</p>
    </div>
    <button type="button" class="btn ghost sm" id="unlink-idea">取消关联</button>
  </div>`;
  $("#unlink-idea").onclick = () => {
    app.plan.idea = "";
    chip.hidden = true;
  };
}

function setPlanStep(step) {
  $$(".step").forEach(node => {
    const name = node.dataset.step;
    node.classList.toggle("active", name === step);
    node.classList.toggle("done", name === "design" && step === "prediction");
  });
}

function dimensionRow(name = "", values = "") {
  return `<div class="input-row dimension-row">
    <input class="dimension-name" aria-label="变量名" placeholder="变量名，如 model" value="${esc(name)}" />
    <input class="dimension-values" aria-label="变量取值" placeholder="取值，用逗号分隔，如 base, large" value="${esc(values)}" />
    <button type="button" class="remove-row" aria-label="删除变量">×</button>
  </div>`;
}

const defaultMetric = name => {
  const lower = name.toLowerCase();
  if (/acc|f1|auc|bleu/.test(lower)) return ["higher_better", "absolute", 0.005];
  if (/err/.test(lower)) return ["lower_better", "absolute", 0.005];
  if (/loss|ppl|perplexity/.test(lower)) return ["lower_better", "relative", 0.1];
  return ["higher_better", "relative", 0.1];
};

function metricRow(name = "", direction, compare, tolerance) {
  const defaults = defaultMetric(name);
  direction ??= defaults[0]; compare ??= defaults[1]; tolerance ??= defaults[2];
  return `<div class="input-row metric-row">
    <input class="metric-name" aria-label="指标名" placeholder="指标名，如 top1_acc" value="${esc(name)}" />
    <select class="metric-direction" aria-label="优化方向">
      <option value="higher_better" ${direction === "higher_better" ? "selected" : ""}>越大越好</option>
      <option value="lower_better" ${direction === "lower_better" ? "selected" : ""}>越小越好</option>
    </select>
    <select class="metric-compare" aria-label="比较方式">
      <option value="absolute" ${compare === "absolute" ? "selected" : ""}>绝对偏差</option>
      <option value="relative" ${compare === "relative" ? "selected" : ""}>相对偏差</option>
    </select>
    <input class="metric-tolerance" type="number" min="0" step="any" aria-label="判定容差" value="${esc(tolerance)}" />
    <button type="button" class="remove-row" aria-label="删除指标">×</button>
  </div>`;
}

function bindRows(container) {
  $$(".remove-row", container).forEach(button => {
    button.onclick = () => button.parentElement.remove();
  });
  $$(".metric-name", container).forEach(input => {
    input.onchange = () => {
      const row = input.closest(".metric-row");
      const values = defaultMetric(input.value);
      $(".metric-direction", row).value = values[0];
      $(".metric-compare", row).value = values[1];
      $(".metric-tolerance", row).value = values[2];
    };
  });
}

const collectDimensions = () => $$(".dimension-row").map(row => ({
  name: $(".dimension-name", row).value.trim(),
  values: $(".dimension-values", row).value.split(",").map(value => value.trim()).filter(Boolean),
}));

const collectMetrics = () => $$(".metric-row").map(row => ({
  name: $(".metric-name", row).value.trim(),
  direction: $(".metric-direction", row).value,
  compare: $(".metric-compare", row).value,
  tolerance: $(".metric-tolerance", row).value,
}));

async function previewRuns(event) {
  event?.preventDefault();
  const errorNode = $("#plan-error");
  errorNode.hidden = true;
  const direction = $("#research-direction").value.trim();
  const hypothesis = $("#hypothesis").value.trim();
  if (!direction || !hypothesis) return formError(errorNode, new Error("请先填写研究方向和实验假设"));
  const metrics = collectMetrics();
  if (!metrics.length || metrics.some(item => !item.name)) return formError(errorNode, new Error("请至少填写一个完整的指标名"));
  try {
    const result = await api("/api/runs/preview", { method: "POST", body: JSON.stringify({ dimensions: collectDimensions() }) });
    app.plan.runs = result.runs;
    app.plan.metrics = metrics.map(item => item.name);
    renderPredictionTable();
    $("#prediction-panel").hidden = false;
    setPlanStep("prediction");
    $("#prediction-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    formError(errorNode, error);
  }
}

function renderPredictionTable() {
  $("#prediction-head").innerHTML = `<tr><th>Run</th>${app.plan.metrics.map(name => `<th>${esc(name)} 预测</th>`).join("")}<th>置信度</th><th>为什么这么预期</th></tr>`;
  $("#prediction-body").innerHTML = app.plan.runs.map(run => `<tr class="prediction-row" data-run="${esc(run)}">
    <td><span class="run-key">${esc(run)}</span></td>
    ${app.plan.metrics.map(name => `<td><input class="prediction-value" data-metric="${esc(name)}" placeholder="0.83 或 0.80 ~ 0.84" /></td>`).join("")}
    <td><select class="prediction-confidence"><option value="low">低</option><option value="medium" selected>中</option><option value="high">高</option></select></td>
    <td><input class="rationale-input" placeholder="影响这个判断的关键依据" /></td>
  </tr>`).join("");
}

async function submitPlan(event) {
  event.preventDefault();
  const errorNode = $("#plan-error");
  errorNode.hidden = true;
  if (!app.plan.runs.length) return previewRuns();
  const predictions = $$(".prediction-row").map(row => ({
    run: row.dataset.run,
    metrics: Object.fromEntries($$(".prediction-value", row).map(input => [input.dataset.metric, input.value.trim()])),
    confidence: $(".prediction-confidence", row).value,
    rationale: $(".rationale-input", row).value.trim(),
  }));
  const button = $("#plan-form button[type=submit]");
  button.disabled = true;
  try {
    const result = await api("/api/batches", {
      method: "POST",
      body: JSON.stringify({
        research_direction: $("#research-direction").value,
        hypothesis: $("#hypothesis").value,
        dimensions: collectDimensions(),
        metrics: collectMetrics(),
        predictions,
        idea: app.plan.idea || "",
      }),
    });
    toast(`批次 ${result.batch} 已创建，${result.run_count} 条预测已锁定`);
    resetPlan();
    await refresh();
    go(`#/batch/${encodeURIComponent(result.batch)}`);
  } catch (error) {
    formError(errorNode, error);
  } finally {
    button.disabled = false;
  }
}

function resetPlan() {
  $("#plan-form").reset();
  $("#dimension-rows").innerHTML = dimensionRow("model", "base, large");
  $("#metric-rows").innerHTML = metricRow("top1_acc");
  bindRows($("#plan-form"));
  app.plan = { runs: [], metrics: [], idea: "" };
  renderIdeaLinkChip(null);
  $("#prediction-panel").hidden = true;
  setPlanStep("design");
  $("#plan-error").hidden = true;
}

/* ---------- 信念 ---------- */

function beliefCardHtml(belief) {
  const tone = belief.refuted ? "SURPRISE" : "CONFIRMED";
  return `<article class="card belief-card ${belief.refuted ? "retired" : ""}">
    <span class="badge ${tone}">${esc(belief.status)}</span>
    <h3>${esc(belief.text)}</h3>
    <div class="belief-foot">
      <span class="belief-id">${esc(belief.id)}</span>
      <span>${belief.batch ? `来自 ${esc(belief.batch)}${belief.run ? ` / ${esc(belief.run)}` : ""}` : ""}</span>
    </div>
  </article>`;
}

function renderBeliefs() {
  const [title, sub] = PAGE_META.beliefs;
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  const target = $("#belief-list");
  const beliefs = app.state.beliefs;
  if (!beliefs.length) {
    target.innerHTML = emptyState({
      icon: "✦",
      title: "还没有形成信念",
      body: "复盘 SURPRISE 时写下的新判断会出现在这里，并随着后续实验被加强、动摇或推翻。",
      cta: "去看待复盘", href: "#/",
    });
    return;
  }
  const active = beliefs.filter(belief => !belief.refuted);
  const retired = beliefs.filter(belief => belief.refuted);
  target.innerHTML = `
    <div class="belief-section">
      <div class="section-head"><h2>在册（${active.length}）</h2></div>
      ${active.length ? `<div class="belief-grid">${active.map(beliefCardHtml).join("")}</div>`
        : '<p class="muted" style="margin:0">暂无在册信念。</p>'}
    </div>
    ${retired.length ? `<div class="belief-section">
      <div class="section-head"><h2>已推翻（${retired.length}）</h2></div>
      <div class="belief-grid">${retired.map(beliefCardHtml).join("")}</div>
    </div>` : ""}`;
}

/* ---------- 论文 ---------- */

const DRAFT_STATUS_OPTIONS = [
  ["writing", "撰写中"],
  ["submitted", "已投稿"],
  ["published", "已发表"],
];

function draftCardHtml(draft) {
  const sections = draft.sections || [];
  const written = sections.filter(section => section.text.trim()).length;
  const total = app.state.sections.length;
  const materials = sections.reduce((sum, section) => sum + section.materials.length, 0);
  const statusBadge = draft.status === "已发表"
    ? "done" : draft.status === "已投稿" ? "live" : "idea-open";
  return `<a class="card draft-card" href="#/paper/${encodeURIComponent(draft.id)}">
    <div class="idea-top">
      <span class="badge ${statusBadge}">${esc(draft.status)}</span>
      <span class="belief-id">${esc(draft.id)}</span>
    </div>
    <h3>${esc(draft.title)}</h3>
    <p class="idea-motivation">${esc(draft.venue || "未定目标期刊或会议")}</p>
    <div class="draft-progress">
      <span>${written}/${total} 节已动笔</span>
      <span>·</span>
      <span>${materials} 处素材引用</span>
      <span>·</span>
      <span>${dateLabel(draft.opened_ts)}</span>
    </div>
  </a>`;
}

function draftCreateCardHtml() {
  return `<form id="draft-form" class="card form-card" novalidate>
    <div class="form-head">
      <h3>开始一份新草稿</h3>
      <p>批次结论与信念账本会作为素材待引用——写作即整理。</p>
    </div>
    <div class="field">
      <label for="draft-title">论文标题（工作标题即可）</label>
      <input id="draft-title" placeholder="例如：小数据集上模型容量与数据增强的交互" required />
    </div>
    <div class="field">
      <label for="draft-venue">目标期刊或会议<span class="muted">（可留空）</span></label>
      <input id="draft-venue" placeholder="例如：NeurIPS / TMLR" />
    </div>
    <div id="draft-error" class="form-error" hidden></div>
    <div class="form-actions"><button type="submit" class="btn primary">创建草稿</button></div>
  </form>`;
}

function renderPaper() {
  const [title, sub] = PAGE_META.paper;
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;

  const target = $("#paper-list");
  const drafts = app.state.drafts;
  if (!drafts.length) {
    const hasMaterial = app.state.batches.some(batch => batch.closed) || app.state.beliefs.length;
    target.innerHTML = (hasMaterial
      ? emptyState({
          icon: "✎",
          title: "实验已收口，材料已备好",
          body: "批次的结论、SURPRISE 的复盘与信念账本，就是讨论部分最原始的材料。从这里开始整理成论文。",
          cta: "",
          href: "",
        })
      : emptyState({
          icon: "✎",
          title: "论文工作区",
          body: "从想法到实验再到论文，全程都在这里。实验陆续收口后，素材会自然沉淀下来供写作引用。",
          cta: "",
          href: "",
        })) + draftCreateCardHtml();
  } else {
    target.innerHTML = `<div class="belief-grid">${drafts.map(draftCardHtml).join("")}</div>` + draftCreateCardHtml();
  }
  bindDraftForm();
}

function bindDraftForm() {
  const form = $("#draft-form");
  if (!form) return;
  form.onsubmit = async event => {
    event.preventDefault();
    const errorNode = $("#draft-error");
    errorNode.hidden = true;
    const button = $("button[type=submit]", form);
    button.disabled = true;
    try {
      const result = await api("/api/drafts", {
        method: "POST",
        body: JSON.stringify({
          title: $("#draft-title").value,
          venue: $("#draft-venue").value,
        }),
      });
      toast(`草稿 ${result.draft} 已创建`);
      await refresh();
      go(`#/paper/${encodeURIComponent(result.draft)}`);
    } catch (error) {
      formError(errorNode, error);
    } finally {
      button.disabled = false;
    }
  };
}

/* ---------- 草稿详情 ---------- */

function materialLabel(material) {
  if (material.batch) {
    const batch = app.state.batches.find(item => item.id === material.batch);
    return `批次 ${material.batch}：${batch ? batch.hypothesis : "（已不存在）"}`;
  }
  if (material.belief) {
    const belief = app.state.beliefs.find(item => item.id === material.belief);
    return `信念 ${material.belief}：${belief ? belief.text : "（已不存在）"}`;
  }
  if (material.idea) {
    const idea = app.state.ideas.find(item => item.id === material.idea);
    return `想法 ${material.idea}：${idea ? idea.text : "（已不存在）"}`;
  }
  return "未知素材";
}

function materialKey(material) {
  return material.batch ? `batch:${material.batch}`
    : material.belief ? `belief:${material.belief}`
    : material.idea ? `idea:${material.idea}` : "unknown";
}

function materialReferenceText(material) {
  if (material.batch) {
    const batch = app.state.batches.find(item => item.id === material.batch);
    if (!batch) return `- 批次 ${material.batch}（数据已不存在）`;
    const lines = [`**批次 ${batch.id}**：${batch.hypothesis}`];
    if (batch.research_direction) lines.push(`（方向：${batch.research_direction}）`);
    for (const run of batch.runs) {
      const verdict = run.closed && run.verdict === "SURPRISE" ? "已复盘的超出预期" : (VERDICT_LABEL[run.verdict] || run.verdict);
      const predicted = Object.entries(run.prediction?.metrics || {})
        .map(([name, value]) => `${name} ${fmtPrediction(value)}`).join("，");
      const actual = Object.entries(run.aggregates || {})
        .map(([name, agg]) => `${name} ${fmt(agg.mean)}±${agg.sd === null ? "?" : fmt(agg.sd)}(n=${agg.n})`).join("，");
      lines.push(`- \`${run.run}\`：预测 ${predicted || "—"}；实测 ${actual || "—"}（${verdict}）`);
    }
    return lines.join("\n");
  }
  if (material.belief) {
    const belief = app.state.beliefs.find(item => item.id === material.belief);
    if (!belief) return `- 信念 ${material.belief}（已不存在）`;
    return `- 信念（${belief.status}）：${belief.text} [${belief.id}]`;
  }
  if (material.idea) {
    const idea = app.state.ideas.find(item => item.id === material.idea);
    if (!idea) return `- 想法 ${material.idea}（已不存在）`;
    return `- 研究起点：${idea.text}${idea.motivation ? `（${idea.motivation}）` : ""} [${idea.id}]`;
  }
  return "";
}

function materialPickerHtml(section) {
  const selected = new Set((section?.materials || []).map(materialKey));
  const batchOptions = app.state.batches.map(batch => {
    const key = `batch:${batch.id}`;
    return `<label class="material-option">
      <input type="checkbox" value="${esc(key)}" ${selected.has(key) ? "checked" : ""} />
      <span><b>${esc(batch.id)}</b> ${esc(batch.hypothesis.slice(0, 40))}${batch.hypothesis.length > 40 ? "…" : ""}</span>
    </label>`;
  }).join("");
  const beliefOptions = app.state.beliefs.map(belief => {
    const key = `belief:${belief.id}`;
    return `<label class="material-option">
      <input type="checkbox" value="${esc(key)}" ${selected.has(key) ? "checked" : ""} />
      <span><b>${esc(belief.id)}</b> ${esc(belief.text.slice(0, 40))}${belief.text.length > 40 ? "…" : ""}</span>
    </label>`;
  }).join("");
  const ideaOptions = app.state.ideas.filter(idea => !idea.discarded).map(idea => {
    const key = `idea:${idea.id}`;
    return `<label class="material-option">
      <input type="checkbox" value="${esc(key)}" ${selected.has(key) ? "checked" : ""} />
      <span><b>${esc(idea.id)}</b> ${esc(idea.text.slice(0, 40))}${idea.text.length > 40 ? "…" : ""}</span>
    </label>`;
  }).join("");

  const group = (label, options, emptyText) => options
    ? `<div class="material-group"><h5>${label}</h5>${options}</div>`
    : `<div class="material-group"><h5>${label}</h5><p class="muted" style="margin:4px 0">${emptyText}</p></div>`;

  return `<div class="material-picker">
    ${group("实验批次", batchOptions, "还没有批次")}
    ${group("信念", beliefOptions, "还没有信念")}
    ${group("想法", ideaOptions, "还没有想法")}
  </div>`;
}

function sectionCardHtml(draft, name, label) {
  const section = draft.sections.find(item => item.name === name);
  const saved = section?.saved_ts ? `上次保存 ${dateLabel(section.saved_ts)}` : "还没写过";
  return `<form class="card section-card" data-section="${esc(name)}" novalidate>
    <div class="form-head spread">
      <div><h3>${esc(label)} <span class="dirty-flag" hidden>未保存</span></h3><p>${esc(saved)}</p></div>
      <button type="button" class="btn ghost sm insert-materials">↧ 插入选中素材</button>
    </div>
    <div class="field">
      <textarea class="section-text" rows="${name === "abstract" ? 5 : 8}" placeholder="${esc(label)}……">${esc(section?.text || "")}</textarea>
    </div>
    <details class="material-details">
      <summary>素材引用（${(section?.materials || []).length}）</summary>
      ${materialPickerHtml(section)}
      ${(section?.materials || []).length
        ? `<div class="material-list">${section.materials.map(m =>
            `<span class="chip">${esc(materialLabel(m))}</span>`).join("")}</div>` : ""}
    </details>
    <div class="form-actions"><button type="submit" class="btn primary sm">保存这一节</button></div>
    <div class="form-error" hidden></div>
  </form>`;
}

function renderDraft() {
  const draftId = app.route.draft;
  const draft = app.state.drafts.find(item => item.id === draftId);
  const target = $("#draft-detail");

  if (!draft) {
    $("#page-title").textContent = "草稿不存在";
    $("#page-sub").textContent = "";
    target.innerHTML = emptyState({
      icon: "?", title: "找不到这份草稿",
      body: "它可能属于另一个研究目录。", cta: "回到论文列表", href: "#/paper",
    });
    return;
  }

  $("#page-title").textContent = draft.title;
  $("#page-sub").textContent = draft.venue || "未定目标期刊或会议";

  const statusOptions = DRAFT_STATUS_OPTIONS.map(([value, label]) =>
    `<option value="${esc(value)}" ${draft.status === label ? "selected" : ""}>${esc(label)}</option>`).join("");
  const savedSections = draft.sections.length;

  target.innerHTML = `
    <article class="card batch-head">
      <a class="crumb" href="#/paper">← 论文</a>
      <div class="batch-head-top">
        <div>
          <h2>${esc(draft.title)}</h2>
          <p class="batch-direction">${esc(draft.venue || "未定目标期刊或会议")} · ${savedSections}/${app.state.sections.length} 节已动笔</p>
        </div>
        <div class="head-badges">
          <select id="draft-status" class="status-select">${statusOptions}</select>
          <button type="button" class="btn ghost sm" id="export-draft">导出 Markdown</button>
        </div>
      </div>
      <div class="callout"><strong>素材自然沉淀</strong><span>引用批次与信念写下的每一段，都能追溯到证据来自哪次实验。</span></div>
    </article>
    <div id="section-list">
      ${app.state.sections.map(({ name, label }) => sectionCardHtml(draft, name, label)).join("")}
    </div>`;

  bindDraftPage(draft);
  restoreStashedDraft(draft.id);
}

function bindDraftPage(draft) {
  $("#draft-status").onchange = async event => {
    try {
      await api("/api/drafts/status", {
        method: "POST",
        body: JSON.stringify({ draft: draft.id, status: event.target.value }),
      });
      toast("草稿状态已更新");
      await refresh();
    } catch (error) {
      toast(error.message, true);
      await refresh();
    }
  };

  $("#export-draft").onclick = async () => {
    try {
      const result = await api("/api/drafts/export", {
        method: "POST",
        body: JSON.stringify({ draft: draft.id }),
      });
      const blob = new Blob([result.markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${draft.id}-${draft.title.slice(0, 24)}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast(error.message, true);
    }
  };

  $$("#draft-detail .section-card").forEach(form => {
    $(".section-text", form).addEventListener("input", () => markSectionDirty(form, true));

    $(".insert-materials", form).onclick = () => {
      const textarea = $(".section-text", form);
      const checked = $$(".material-option input:checked", form);
      if (!checked.length) {
        toast("先在「素材引用」里勾选要引用的批次或信念");
        return;
      }
      const references = checked.map(input => {
        const [kind, id] = input.value.split(":");
        return materialReferenceText({ [kind]: id });
      }).join("\n\n");
      textarea.value = textarea.value.trimEnd()
        ? `${textarea.value.trimEnd()}\n\n${references}\n`
        : `${references}\n`;
      markSectionDirty(form, true);
      textarea.focus();
      textarea.selectionStart = textarea.value.length;
    };

    form.onsubmit = async event => {
      event.preventDefault();
      const errorNode = $(".form-error", form);
      errorNode.hidden = true;
      const button = $("button[type=submit]", form);
      button.disabled = true;
      const materials = $$(".material-option input:checked", form).map(input => {
        const [kind, id] = input.value.split(":");
        return { [kind]: id };
      });
      try {
        await api("/api/drafts/section", {
          method: "POST",
          body: JSON.stringify({
            draft: draft.id,
            section: form.dataset.section,
            text: $(".section-text", form).value,
            materials,
          }),
        });
        markSectionDirty(form, false);
        toast("这一节已保存");
        await refresh();
      } catch (error) {
        formError(errorNode, error);
      } finally {
        button.disabled = false;
      }
    };
  });
}

function markSectionDirty(form, dirty) {
  form.classList.toggle("dirty", dirty);
  const flag = $(".dirty-flag", form);
  if (flag) flag.hidden = !dirty;
  if (dirty) app.dirtySections.add(form.dataset.section);
  else app.dirtySections.delete(form.dataset.section);
  const draftId = app.route.draft;
  if (!draftId) return;
  if (dirty) {
    try {
      localStorage.setItem(`ariadne-stash:${draftId}:${form.dataset.section}`, $(".section-text", form).value);
    } catch { /* 隐私模式等场景下暂存不可用，静默降级 */ }
  } else {
    try {
      localStorage.removeItem(`ariadne-stash:${draftId}:${form.dataset.section}`);
    } catch { /* 同上 */ }
  }
}

function restoreStashedDraft(draftId) {
  for (const form of $$("#draft-detail .section-card")) {
    let text = null;
    try {
      text = localStorage.getItem(`ariadne-stash:${draftId}:${form.dataset.section}`);
    } catch { text = null; }
    if (text === null) continue;
    $(".section-text", form).value = text;
    markSectionDirty(form, true);
  }
}

function captureDirtyDraft() {
  if (!app.dirtySections.size) return null;
  const forms = $$("#draft-detail .section-card");
  if (!forms.length) return null;
  const sections = {};
  for (const form of forms) {
    if (app.dirtySections.has(form.dataset.section)) {
      sections[form.dataset.section] = $(".section-text", form).value;
    }
  }
  return { draft: app.route.draft, sections };
}

function restoreDirtyDraft(snapshot) {
  if (!snapshot || app.route.view !== "draft" || app.route.draft !== snapshot.draft) return;
  for (const form of $$("#draft-detail .section-card")) {
    const text = snapshot.sections[form.dataset.section];
    if (text === undefined) continue;
    $(".section-text", form).value = text;
    markSectionDirty(form, true);
  }
}

/* ---------- 主题 ---------- */

const THEME_KEY = "ariadne-theme";

function initTheme() {
  let theme = null;
  try { theme = localStorage.getItem(THEME_KEY); } catch { theme = null; }
  if (theme !== "dark" && theme !== "light") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
  $("#theme-toggle").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_KEY, next); } catch { /* 隐私模式下不记忆，仅本次生效 */ }
  };
}

/* ---------- 命令面板 ---------- */

const PALETTE_PAGES = [
  { label: "工作台", sub: "总览与下一步", href: "#/" },
  { label: "想法", sub: "从念头到立项", href: "#/ideas" },
  { label: "新实验", sub: "设计批次并锁定预测", href: "#/new" },
  { label: "实验批次", sub: "全部批次", href: "#/experiments" },
  { label: "信念", sub: "信念账本", href: "#/beliefs" },
  { label: "论文", sub: "草稿列表", href: "#/paper" },
];

function paletteEntries() {
  const s = app.state;
  if (!s) return [];
  const entries = PALETTE_PAGES.map(page =>
    ({ type: "页面", text: page.label, sub: page.sub, href: page.href }));
  for (const idea of s.ideas) {
    entries.push({ type: "想法", text: idea.text, sub: `${idea.id} · ${idea.status}`, href: "#/ideas" });
  }
  for (const batch of s.batches) {
    entries.push({
      type: "批次", text: batch.hypothesis || batch.id,
      sub: `${batch.id} · ${batch.closed ? "已收口" : "进行中"} · ${batch.research_direction || ""}`,
      href: `#/batch/${batch.id}`,
    });
  }
  for (const belief of s.beliefs) {
    entries.push({ type: "信念", text: belief.text, sub: `${belief.id} · ${belief.status}`, href: "#/beliefs" });
  }
  for (const draft of s.drafts) {
    entries.push({ type: "论文", text: draft.title, sub: `${draft.id} · ${draft.status}`, href: `#/paper/${draft.id}` });
  }
  return entries;
}

const palette = { open: false, entries: [], selected: 0 };

function openPalette() {
  if (palette.open) return;
  palette.open = true;
  $("#palette-overlay").hidden = false;
  const input = $("#palette-input");
  input.value = "";
  renderPalette("");
  input.focus();
}

function closePalette() {
  palette.open = false;
  $("#palette-overlay").hidden = true;
}

function renderPalette(query) {
  const q = query.trim().toLowerCase();
  const all = paletteEntries();
  palette.entries = q
    ? all.filter(entry =>
        `${entry.text} ${entry.sub}`.toLowerCase().includes(q))
    : all.slice(0, 9);
  palette.selected = 0;

  const list = $("#palette-list");
  if (!palette.entries.length) {
    list.innerHTML = `<div class="palette-empty">没有匹配「${esc(query)}」的内容</div>`;
    return;
  }
  list.innerHTML = palette.entries.map((entry, index) => `
    <button type="button" class="palette-item ${index === 0 ? "selected" : ""}" data-index="${index}" role="option">
      <span class="palette-type">${esc(entry.type)}</span>
      <span class="palette-body">
        <span class="palette-text">${esc(entry.text)}</span>
        <span class="palette-sub">${esc(entry.sub)}</span>
      </span>
    </button>`).join("");
  $$("#palette-list .palette-item").forEach(item => {
    item.onclick = () => goPaletteEntry(Number(item.dataset.index));
  });
}

function movePaletteSelection(delta) {
  const count = palette.entries.length;
  if (!count) return;
  palette.selected = (palette.selected + delta + count) % count;
  $$("#palette-list .palette-item").forEach((item, index) =>
    item.classList.toggle("selected", index === palette.selected));
  const active = $(`#palette-list .palette-item[data-index="${palette.selected}"]`);
  if (active) active.scrollIntoView({ block: "nearest" });
}

function goPaletteEntry(index) {
  const entry = palette.entries[index];
  if (!entry) return;
  closePalette();
  go(entry.href);
}

function initPalette() {
  $("#open-palette").onclick = openPalette;
  $("#palette-overlay").addEventListener("mousedown", event => {
    if (event.target === $("#palette-overlay")) closePalette();
  });
  $("#palette-input").addEventListener("input", event => renderPalette(event.target.value));
  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      palette.open ? closePalette() : openPalette();
      return;
    }
    if (!palette.open) return;
    if (event.key === "Escape") { event.preventDefault(); closePalette(); }
    else if (event.key === "ArrowDown") { event.preventDefault(); movePaletteSelection(1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); movePaletteSelection(-1); }
    else if (event.key === "Enter") {
      event.preventDefault();
      goPaletteEntry(palette.selected);
    }
  });
}

/* ---------- 启动 ---------- */

function setup() {
  $("#mobile-menu").onclick = () => $("#sidebar").classList.toggle("open");
  $$(".nav-link, .brand, .sidebar-new").forEach(node => {
    node.addEventListener("click", () => $("#sidebar").classList.remove("open"));
  });
  $("#add-dimension").onclick = () => {
    $("#dimension-rows").insertAdjacentHTML("beforeend", dimensionRow());
    bindRows($("#dimension-rows"));
  };
  $("#add-metric").onclick = () => {
    $("#metric-rows").insertAdjacentHTML("beforeend", metricRow());
    bindRows($("#metric-rows"));
  };
  $("#preview-runs").onclick = previewRuns;
  $("#plan-form").onsubmit = submitPlan;
  $("#idea-form").onsubmit = async event => {
    event.preventDefault();
    const errorNode = $("#idea-error");
    errorNode.hidden = true;
    const button = $("button[type=submit]", $("#idea-form"));
    button.disabled = true;
    try {
      const result = await api("/api/ideas", {
        method: "POST",
        body: JSON.stringify({
          text: $("#idea-text").value,
          motivation: $("#idea-motivation").value,
        }),
      });
      toast(`想法 ${result.idea} 已入账本`);
      $("#idea-text").value = "";
      $("#idea-motivation").value = "";
      await refresh();
    } catch (error) {
      formError(errorNode, error);
    } finally {
      button.disabled = false;
    }
  };
  resetPlan();
  initTheme();
  initPalette();
  window.addEventListener("hashchange", onHashChange);
  window.addEventListener("beforeunload", event => {
    if (app.dirtySections.size) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  document.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
    const view = $("#view-draft.active");
    if (!view) return;
    const form = (event.target instanceof Element && event.target.closest(".section-card"))
      || $(".section-card.dirty", view)
      || $(".section-card", view);
    if (!form) return;
    event.preventDefault();
    form.requestSubmit();
  });
  app.route = parseHash();
  app.lastHash = location.hash;
  refresh();
}

let restoringHash = false;

function onHashChange() {
  if (restoringHash) {
    restoringHash = false;
    return;
  }
  if (app.dirtySections.size && !window.confirm("有未保存的章节，离开会丢掉刚写的内容。确定离开吗？")) {
    restoringHash = true;
    location.hash = app.lastHash || "#/paper";
    return;
  }
  app.lastHash = location.hash;
  render();
}

document.addEventListener("DOMContentLoaded", setup);

window.addEventListener("pywebviewready", () => {
  const button = $("#switch-project");
  button.hidden = false;
  button.onclick = async () => {
    try {
      const result = await window.pywebview.api.choose_project();
      if (!result.ok && !result.cancelled) toast(result.error || "无法打开这个目录", true);
    } catch (error) {
      toast(String(error), true);
    }
  };
});
