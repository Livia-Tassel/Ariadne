const app = {
  state: null,
  previewRuns: [],
  previewMetrics: [],
  view: "overview",
};

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
  toast.timer = setTimeout(() => node.className = "toast", 3200);
}

function showError(selector, error) {
  const node = $(selector);
  node.textContent = error?.message || String(error);
  node.hidden = false;
  node.scrollIntoView({ behavior: "smooth", block: "center" });
}

function clearError(selector) {
  const node = $(selector);
  node.hidden = true;
  node.textContent = "";
}

const viewMeta = {
  overview: ["实验总览", "把意外变成知识"],
  plan: ["实验设计", "在运行之前写下判断"],
  results: ["结果录入", "让数据与预测相遇"],
  reviews: ["实验复盘", "找到真正出错的假设"],
  beliefs: ["知识沉淀", "让每轮实验改变下一次判断"],
};

function navigate(view) {
  app.view = view;
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${view}`));
  $$(".nav-item").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  $("#page-eyebrow").textContent = viewMeta[view][0];
  $("#page-title").textContent = viewMeta[view][1];
  $(".sidebar").classList.remove("open");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function verdictBadge(verdict, closed = false) {
  const labels = {
    CONFIRMED: "符合预期", SURPRISE: "超出预期", NOISY: "噪声过大",
    NO_RESULT: "等待结果", UNVERIFIED: "待确认",
  };
  if (closed && verdict === "SURPRISE") return `<span class="badge closed">已复盘</span>`;
  return `<span class="badge ${esc(verdict)}">${esc(labels[verdict] || verdict)}</span>`;
}

function fmt(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number) >= 1000 || (Math.abs(number) > 0 && Math.abs(number) < .001)) return number.toExponential(3);
  return Number(number.toPrecision(5)).toString();
}

function fmtPrediction(value) {
  return Array.isArray(value) ? `${fmt(value[0])} ~ ${fmt(value[1])}` : fmt(value);
}

function metricLines(run, kind) {
  const prediction = run.prediction?.metrics || {};
  return `<div class="metric-lines">${Object.keys(prediction).map(name => {
    if (kind === "prediction") return `<span><b>${esc(name)}</b> ${esc(fmtPrediction(prediction[name]))}</span>`;
    const aggregate = run.aggregates?.[name];
    const actual = aggregate ? `${fmt(aggregate.mean)}${aggregate.sd === null ? "" : ` ± ${fmt(aggregate.sd)}`} <small>n=${aggregate.n}</small>` : "—";
    return `<span><b>${esc(name)}</b> ${actual}</span>`;
  }).join("")}</div>`;
}

function emptyState(icon, title, body, action = "", view = "plan") {
  return `<div class="empty-state"><div class="empty-icon">${icon}</div><h3>${esc(title)}</h3><p>${esc(body)}</p>${action ? `<button class="primary compact" data-go="${view}">${esc(action)}</button>` : ""}</div>`;
}

function renderOverview() {
  const state = app.state;
  $("#stat-batches").textContent = state.summary.batches;
  $("#stat-runs").textContent = state.summary.runs;
  $("#stat-reviews").textContent = state.summary.pending_reviews;
  $("#stat-beliefs").textContent = state.beliefs.length;
  const count = $("#review-count");
  count.textContent = state.summary.pending_reviews;
  count.hidden = !state.summary.pending_reviews;

  const target = $("#batch-list");
  if (!state.batches.length) {
    target.innerHTML = emptyState("⌁", "还没有实验批次", "从一个你真正关心的问题开始。设计变量与指标后，系统会生成预测表。", "设计第一个实验");
    bindGoButtons(target);
    return;
  }
  const alerts = [...state.parse_errors.map(item => `runs.jsonl 第 ${item.line_no} 行：${item.reason}`), ...state.warnings];
  target.innerHTML = (alerts.length ? `<div class="warning-box">${alerts.map(esc).join("<br>")}</div>` : "") + state.batches.map(batch => `
    <article class="batch-card">
      <header class="batch-head">
        <div>
          <span class="batch-direction">${esc(batch.research_direction || "未填写研究方向")}</span>
          <h3>${esc(batch.id)} · ${esc(batch.hypothesis)}</h3>
          <p>${Object.entries(batch.dimensions).map(([name, values]) => `${esc(name)} · ${values.length} 个取值`).join("　")}</p>
        </div>
        <div class="batch-meta">${batch.closed ? '<span class="badge closed">已收口</span>' : '<span class="badge NO_RESULT">进行中</span>'}</div>
      </header>
      <div class="batch-body">
        <div class="table-scroll"><table class="data-table">
          <thead><tr><th>Run</th><th>预测</th><th>实测</th><th>判定</th></tr></thead>
          <tbody>${batch.runs.map(run => `<tr>
            <td><span class="run-key">${esc(run.run)}</span>${run.revised ? '<br><small class="muted">预测已修订</small>' : ""}</td>
            <td>${metricLines(run, "prediction")}</td><td>${metricLines(run, "actual")}</td>
            <td>${verdictBadge(run.verdict, run.closed)}</td>
          </tr>`).join("")}</tbody>
        </table></div>
        ${batch.info_signal ? `<div class="batch-note">${esc(batch.info_signal)}</div>` : ""}
      </div>
    </article>`).join("");
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
  if (/acc|f1|auc|bleu/.test(lower)) return ["higher_better", "absolute", .005];
  if (/err/.test(lower)) return ["lower_better", "absolute", .005];
  if (/loss|ppl|perplexity/.test(lower)) return ["lower_better", "relative", .1];
  return ["higher_better", "relative", .1];
};

function metricRow(name = "", direction, compare, tolerance) {
  const defaults = defaultMetric(name);
  direction ??= defaults[0]; compare ??= defaults[1]; tolerance ??= defaults[2];
  return `<div class="input-row metric-row">
    <input class="metric-name" aria-label="指标名" placeholder="指标名，如 top1_acc" value="${esc(name)}" />
    <select class="metric-direction" aria-label="优化方向"><option value="higher_better" ${direction === "higher_better" ? "selected" : ""}>越大越好</option><option value="lower_better" ${direction === "lower_better" ? "selected" : ""}>越小越好</option></select>
    <select class="metric-compare" aria-label="比较方式"><option value="absolute" ${compare === "absolute" ? "selected" : ""}>绝对偏差</option><option value="relative" ${compare === "relative" ? "selected" : ""}>相对偏差</option></select>
    <input class="metric-tolerance" type="number" min="0" step="any" aria-label="判定容差" value="${esc(tolerance)}" />
    <button type="button" class="remove-row" aria-label="删除指标">×</button>
  </div>`;
}

function bindRows(container) {
  $$(".remove-row", container).forEach(button => button.onclick = () => button.parentElement.remove());
  $$(".metric-name", container).forEach(input => input.onchange = () => {
    const row = input.closest(".metric-row");
    const values = defaultMetric(input.value);
    $(".metric-direction", row).value = values[0];
    $(".metric-compare", row).value = values[1];
    $(".metric-tolerance", row).value = values[2];
  });
}

function collectDimensions() {
  return $$(".dimension-row").map(row => ({
    name: $(".dimension-name", row).value.trim(),
    values: $(".dimension-values", row).value.split(",").map(value => value.trim()).filter(Boolean),
  }));
}

function collectMetrics() {
  return $$(".metric-row").map(row => ({
    name: $(".metric-name", row).value.trim(),
    direction: $(".metric-direction", row).value,
    compare: $(".metric-compare", row).value,
    tolerance: $(".metric-tolerance", row).value,
  }));
}

async function previewRuns() {
  clearError("#plan-error");
  const direction = $("#research-direction").value.trim();
  const hypothesis = $("#hypothesis").value.trim();
  if (!direction || !hypothesis) return showError("#plan-error", new Error("请先填写研究方向和实验假设"));
  const metrics = collectMetrics();
  if (!metrics.length || metrics.some(item => !item.name)) return showError("#plan-error", new Error("请至少填写一个完整的指标名"));
  try {
    const result = await api("/api/runs/preview", { method: "POST", body: JSON.stringify({ dimensions: collectDimensions() }) });
    app.previewRuns = result.runs;
    app.previewMetrics = metrics.map(item => item.name);
    renderPredictionTable();
    $("#prediction-panel").hidden = false;
    $("#step-prediction").classList.add("active");
    $("#prediction-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showError("#plan-error", error); }
}

function renderPredictionTable() {
  $("#prediction-head").innerHTML = `<tr><th>Run</th>${app.previewMetrics.map(name => `<th>${esc(name)} 预测</th>`).join("")}<th>置信度</th><th>为什么这么预期</th></tr>`;
  $("#prediction-body").innerHTML = app.previewRuns.map(run => `<tr class="prediction-row" data-run="${esc(run)}">
    <td><span class="run-key">${esc(run)}</span></td>
    ${app.previewMetrics.map(name => `<td><input class="prediction-value" data-metric="${esc(name)}" placeholder="0.83 或 0.80 ~ 0.84" /></td>`).join("")}
    <td><select class="prediction-confidence"><option value="low">低</option><option value="medium" selected>中</option><option value="high">高</option></select></td>
    <td><input class="rationale-input" placeholder="影响这个判断的关键依据" /></td>
  </tr>`).join("");
}

async function submitPlan(event) {
  event.preventDefault(); clearError("#plan-error");
  if (!app.previewRuns.length) return previewRuns();
  const predictions = $$(".prediction-row").map(row => ({
    run: row.dataset.run,
    metrics: Object.fromEntries($$(".prediction-value", row).map(input => [input.dataset.metric, input.value.trim()])),
    confidence: $(".prediction-confidence", row).value,
    rationale: $(".rationale-input", row).value.trim(),
  }));
  const button = $("#plan-form button[type=submit]");
  button.disabled = true;
  try {
    const result = await api("/api/batches", { method: "POST", body: JSON.stringify({
      research_direction: $("#research-direction").value,
      hypothesis: $("#hypothesis").value,
      dimensions: collectDimensions(), metrics: collectMetrics(), predictions,
    }) });
    toast(`批次 ${result.batch} 已创建，${result.run_count} 条预测已锁定`);
    resetPlan(); await refresh(); navigate("overview");
  } catch (error) { showError("#plan-error", error); }
  finally { button.disabled = false; }
}

function resetPlan() {
  $("#plan-form").reset();
  $("#dimension-rows").innerHTML = dimensionRow("model", "base, large");
  $("#metric-rows").innerHTML = metricRow("top1_acc");
  bindRows($("#plan-form"));
  app.previewRuns = []; app.previewMetrics = [];
  $("#prediction-panel").hidden = true;
  $("#step-prediction").classList.remove("active");
  clearError("#plan-error");
}

function renderResults() {
  const select = $("#result-batch");
  const current = select.value;
  select.innerHTML = app.state.batches.length
    ? app.state.batches.map(batch => `<option value="${esc(batch.id)}">${esc(batch.id)} · ${esc(batch.research_direction || batch.hypothesis)}</option>`).join("")
    : '<option value="">还没有实验批次</option>';
  if (app.state.batches.some(batch => batch.id === current)) select.value = current;
  renderResultRuns();

  const recent = $("#recent-results");
  const withResults = app.state.batches.flatMap(batch => batch.runs.filter(run => Object.keys(run.aggregates).length).map(run => ({ ...run, batch: batch.id })));
  recent.innerHTML = withResults.length ? `<div class="section-heading sub"><div><p class="eyebrow">RECENT</p><h2>已有结果</h2></div></div>
    <article class="batch-card"><div class="batch-body"><div class="table-scroll"><table class="data-table"><thead><tr><th>批次 / Run</th><th>聚合实测</th><th>判定</th></tr></thead><tbody>
    ${withResults.slice(0, 12).map(run => `<tr><td><span class="run-key">${esc(run.batch)} / ${esc(run.run)}</span></td><td>${metricLines(run, "actual")}</td><td>${verdictBadge(run.verdict, run.closed)}</td></tr>`).join("")}</tbody></table></div></div></article>` : "";
}

function selectedBatch(id = $("#result-batch").value) { return app.state.batches.find(batch => batch.id === id); }
function renderResultRuns() {
  const batch = selectedBatch();
  const runSelect = $("#result-run");
  runSelect.innerHTML = batch ? batch.runs.map(run => `<option value="${esc(run.run)}">${esc(run.run)}</option>`).join("") : '<option value="">—</option>';
  renderResultFields();
}
function renderResultFields() {
  const batch = selectedBatch();
  const run = batch?.runs.find(item => item.run === $("#result-run").value);
  $("#result-metrics").innerHTML = batch ? batch.metrics.map(name => `<label>${esc(name)}<input class="result-metric" data-metric="${esc(name)}" inputmode="decimal" placeholder="实测值" required /></label>`).join("") : "";
  const used = run ? Object.values(run.samples || {}).flatMap(samples => Object.keys(samples).map(Number)) : [];
  $("#result-seed").value = used.length ? Math.max(...used) + 1 : 0;
}

async function submitResult(event) {
  event.preventDefault(); clearError("#result-error");
  const button = $("#result-form button[type=submit]"); button.disabled = true;
  try {
    const metrics = Object.fromEntries($$(".result-metric").map(input => [input.dataset.metric, input.value.trim()]));
    const result = await api("/api/results", { method: "POST", body: JSON.stringify({ batch: $("#result-batch").value, rows: [{ run: $("#result-run").value, seed: $("#result-seed").value, metrics }] }) });
    toast(`已保存 ${result.written} 条结果，判定已更新`); await refresh();
  } catch (error) { showError("#result-error", error); }
  finally { button.disabled = false; }
}

function beliefChangeFields(prefix) {
  const active = app.state.beliefs.filter(belief => !belief.refuted);
  if (!active.length) return "";
  return `<label>这次结果改变了哪些已有信念？</label><div class="belief-changes">${active.map(belief => `<div class="belief-change-row"><span>${esc(belief.text)} <small>${esc(belief.id)}</small></span><select data-belief="${esc(belief.id)}" class="${prefix}-belief-change"><option value="unchanged">没有改变</option><option value="reinforced">得到加强</option><option value="weakened">有所动摇</option><option value="refuted">被推翻</option></select></div>`).join("")}</div>`;
}

function renderReviews() {
  const list = $("#review-list");
  if (!app.state.pending_reviews.length) {
    list.innerHTML = emptyState("✓", "没有待复盘的 SURPRISE", "新的结果一旦超出预测范围，就会自动出现在这里。", app.state.batches.length ? "录入实验结果" : "设计第一个实验", app.state.batches.length ? "results" : "plan");
    bindGoButtons(list);
  } else {
    list.innerHTML = app.state.pending_reviews.map((item, index) => `<article class="panel review-card">
      <div class="review-context"><p class="eyebrow">SURPRISE · ${esc(item.batch)}</p><h3>${esc(item.run)}</h3><ul>${item.deviations.map(line => `<li>${esc(line)}</li>`).join("")}</ul>${item.rationale ? `<p class="rationale">当初的理由：${esc(item.rationale)}</p>` : ""}</div>
      <form class="review-form" data-batch="${esc(item.batch)}" data-run="${esc(item.run)}">
        <label>你认为为什么会这样？<textarea class="review-cause" rows="4" placeholder="如果还不知道，就写下准备如何排查。" required></textarea></label>
        <label>下一步准备做什么？<textarea class="review-next" rows="2" placeholder="可以留空"></textarea></label>
        <label>这次之后新相信了什么？<textarea class="review-beliefs" rows="2" placeholder="一行一条，可以留空"></textarea></label>
        ${beliefChangeFields(`review-${index}`)}
        <div class="form-error" hidden></div><button class="primary action-button" type="submit">保存复盘</button>
      </form></article>`).join("");
    $$(".review-form", list).forEach(form => form.onsubmit = submitReview);
  }
  renderCloseBatches();
}

async function submitReview(event) {
  event.preventDefault();
  const form = event.currentTarget, errorNode = $(".form-error", form), button = $("button[type=submit]", form);
  errorNode.hidden = true; button.disabled = true;
  const changes = Object.fromEntries($$("select[data-belief]", form).map(select => [select.dataset.belief, select.value]));
  try {
    await api("/api/reviews", { method: "POST", body: JSON.stringify({ batch: form.dataset.batch, run: form.dataset.run, cause: $(".review-cause", form).value, next: $(".review-next", form).value, beliefs_added: $(".review-beliefs", form).value, belief_changes: changes }) });
    toast("复盘已保存，这次意外已经进入知识记录"); await refresh();
  } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
  finally { button.disabled = false; }
}

function renderCloseBatches() {
  const target = $("#close-list");
  const open = app.state.batches.filter(batch => !batch.closed);
  if (!open.length) { target.innerHTML = emptyState("◌", "所有批次都已收口", "新批次创建后，会在这里显示它是否已经具备收口条件。"); return; }
  target.innerHTML = open.map((batch, index) => `<details class="panel close-card" ${batch.close_blockers.length ? "" : "open"}>
    <summary><span>${esc(batch.id)} · ${esc(batch.hypothesis)}</span>${batch.close_blockers.length ? '<span class="badge NO_RESULT">尚不可收口</span>' : '<span class="badge CONFIRMED">可以收口</span>'}</summary>
    ${batch.close_blockers.length ? `<p class="blocker-list">${batch.close_blockers.map(esc).join("；")}</p>` : `<form class="close-form" data-batch="${esc(batch.id)}">
      <label>这一批整体学到了什么？<textarea class="close-cause" rows="3" required></textarea></label>
      <label>下一批准备验证什么？<textarea class="close-next" rows="2" placeholder="可以留空"></textarea></label>
      <label>新增信念<textarea class="close-beliefs" rows="2" placeholder="一行一条，可以留空"></textarea></label>
      ${beliefChangeFields(`close-${index}`)}<div class="form-error" hidden></div><button class="primary action-button" type="submit">收口批次</button>
    </form>`}
  </details>`).join("");
  $$(".close-form", target).forEach(form => form.onsubmit = submitClose);
}

async function submitClose(event) {
  event.preventDefault();
  const form = event.currentTarget, errorNode = $(".form-error", form), button = $("button[type=submit]", form);
  errorNode.hidden = true; button.disabled = true;
  const changes = Object.fromEntries($$("select[data-belief]", form).map(select => [select.dataset.belief, select.value]));
  try {
    await api("/api/batches/close", { method: "POST", body: JSON.stringify({ batch: form.dataset.batch, cause: $(".close-cause", form).value, next: $(".close-next", form).value, beliefs_added: $(".close-beliefs", form).value, belief_changes: changes }) });
    toast(`批次 ${form.dataset.batch} 已收口`); await refresh(); navigate("overview");
  } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
  finally { button.disabled = false; }
}

function renderBeliefs() {
  const target = $("#belief-list");
  if (!app.state.beliefs.length) {
    target.innerHTML = emptyState("✦", "还没有形成信念", "复盘 SURPRISE 时写下的新判断会出现在这里，并随着后续实验被加强、动摇或推翻。", "去看待复盘", "reviews");
    bindGoButtons(target); return;
  }
  target.innerHTML = app.state.beliefs.map(belief => `<article class="belief-card ${belief.refuted ? "refuted" : ""}">
    <span class="badge ${belief.refuted ? "SURPRISE" : "CONFIRMED"}">${esc(belief.status)}</span>
    <h3>${esc(belief.text)}</h3><div class="belief-foot"><span class="belief-id">${esc(belief.id)}</span><span>${belief.batch ? `来自 ${esc(belief.batch)}` : ""}</span></div>
  </article>`).join("");
}

function bindGoButtons(root = document) {
  $$('[data-go]', root).forEach(button => button.onclick = () => navigate(button.dataset.go));
}

async function refresh() {
  try {
    app.state = await api("/api/state");
    $("#project-path").textContent = app.state.project.path;
    renderOverview(); renderResults(); renderReviews(); renderBeliefs();
    bindGoButtons();
  } catch (error) { toast(error.message, true); }
  finally { $("#loading").hidden = true; }
}

function setup() {
  $$(".nav-item").forEach(button => button.onclick = () => navigate(button.dataset.view));
  bindGoButtons();
  $("#mobile-menu").onclick = () => $(".sidebar").classList.toggle("open");
  $("#add-dimension").onclick = () => { $("#dimension-rows").insertAdjacentHTML("beforeend", dimensionRow()); bindRows($("#dimension-rows")); };
  $("#add-metric").onclick = () => { $("#metric-rows").insertAdjacentHTML("beforeend", metricRow()); bindRows($("#metric-rows")); };
  $("#preview-runs").onclick = previewRuns;
  $("#plan-form").onsubmit = submitPlan;
  $("#result-form").onsubmit = submitResult;
  $("#result-batch").onchange = renderResultRuns;
  $("#result-run").onchange = renderResultFields;
  resetPlan(); refresh();
}

document.addEventListener("DOMContentLoaded", setup);

window.addEventListener("pywebviewready", () => {
  const button = $("#switch-project");
  button.hidden = false;
  button.onclick = async () => {
    try {
      const result = await window.pywebview.api.choose_project();
      if (!result.ok && !result.cancelled) toast(result.error || "无法打开这个目录", true);
    } catch (error) { toast(String(error), true); }
  };
});
