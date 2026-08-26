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
  plan: { runs: [], metrics: [] },
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
  const parts = raw.split("/").filter(Boolean).map(decodeURIComponent);
  if (!parts.length) return { view: "dashboard" };
  if (parts[0] === "experiments") return { view: "experiments" };
  if (parts[0] === "beliefs") return { view: "beliefs" };
  if (parts[0] === "new") return { view: "new" };
  if (parts[0] === "batch" && parts[1]) {
    return { view: "batch", batch: parts[1], run: parts[2] === "run" ? parts[3] : null };
  }
  return { view: "dashboard" };
}

function go(hash) { location.hash = hash; }

const PAGE_META = {
  dashboard: ["工作台", "先预测，再验证——把意外变成知识"],
  experiments: ["实验批次", "每一个批次是一次假设的检验"],
  new: ["新实验", "在开跑之前，先写下你对结果的判断"],
  beliefs: ["信念账本", "实验会结束，能指导下一次预测的判断会留下来"],
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
  const navKey = view === "batch" ? "experiments" : view;
  $$(".nav-link").forEach(node => node.classList.toggle("active", node.dataset.nav === navKey));
  $("#sidebar").classList.remove("open");

  if (view === "dashboard") renderDashboard();
  else if (view === "experiments") renderExperiments();
  else if (view === "batch") renderBatch();
  else if (view === "new") renderPlanView();
  else if (view === "beliefs") renderBeliefs();
}

async function refresh() {
  try {
    app.state = await api("/api/state");
    $("#project-path").textContent = app.state.project.path;
    renderCurrentView();
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
    <div class="stat"><span>实验批次</span><strong>${s.summary.batches}</strong><small>已设计</small></div>
    <div class="stat"><span>Run</span><strong>${s.summary.runs}</strong><small>预测已锁定</small></div>
    <div class="stat accent"><span>待复盘</span><strong>${s.summary.pending_reviews}</strong><small>最有信息量</small></div>
    <div class="stat"><span>信念</span><strong>${s.beliefs.length}</strong><small>持续演化</small></div>`;

  const target = $("#dash-batches");
  if (!s.batches.length) {
    target.innerHTML = emptyState({
      icon: "⌁",
      title: "从一个你真正关心的问题开始",
      body: "写下假设、设计变量与指标，Ariadne 会生成预测表。开跑前锁定预测，实验的差异才会变成知识。",
      cta: "设计第一个实验",
      href: "#/new",
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
  const specChips = Object.entries(batch.metric_specs || {})
    .map(([name, spec]) => `<span class="chip"><b>${esc(name)}</b> ${DIRECTION_LABEL[spec.direction] || spec.direction} · ${COMPARE_LABEL[spec.compare] || spec.compare} ${fmt(spec.tolerance)}</span>`).join("");

  target.innerHTML = `
    <article class="card batch-head">
      <a class="crumb" href="#/experiments">← 实验批次</a>
      <div class="batch-head-top">
        <div>
          <h2>${esc(batch.hypothesis)}</h2>
          <p class="batch-direction">${esc(batch.research_direction || "")}</p>
          <div class="batch-chips">${dimChips}${specChips}</div>
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
  if (!app.plan.runs.length) {
    $("#prediction-panel").hidden = true;
    setPlanStep("design");
  }
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
  app.plan = { runs: [], metrics: [] };
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
  resetPlan();
  window.addEventListener("hashchange", render);
  app.route = parseHash();
  refresh();
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
