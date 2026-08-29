/* 批次详情：一页台账。文档头 → 一句话结论 → 图 → 明细表 → 收口。 */

"use strict";

import { $, $$, html, raw } from "../lib/dom.js";
import {
  COMPARE,
  CONFIDENCE,
  DIRECTION,
  INTEGRITY,
  VERDICT,
  dateLabel,
  fmt,
  fmtActualAt,
  fmtDeviation,
  fmtPredictionAt,
  decimalsFor,
  runSeeds,
} from "../lib/fmt.js";
import { findBatch, store } from "../lib/store.js";
import { chartsHtml } from "../parts/chart.js";
import { bindForms, closeHtml, resultFormHtml, reviewFormHtml } from "../parts/forms.js";
import { bindResults, resultsSectionHtml } from "../parts/results.js";

/** 一句话说清这一批发生了什么。计数器说不出「假设被推翻了」。 */
function ledeHtml(batch) {
  const runs = batch.runs;
  const judged = runs.filter((run) => ["CONFIRMED", "SURPRISE"].includes(run.verdict));
  const surprises = runs.filter((run) => run.verdict === "SURPRISE");
  const suspect = runs.filter((run) => run.integrity?.length);

  if (suspect.length) {
    return html`<p class="lede">
      有 <b>${suspect.length} 个 run 带着完整性标记</b>——这一批的结论在解释清楚之前不该被引用。
    </p>`;
  }
  if (!judged.length) {
    const locked = runs.filter((run) => run.prediction).length;
    return html`<p class="lede">
      ${locked} 个 run 已锁定预测，还没有可判定的结果。跑完回来录入，判定会自动更新。
    </p>`;
  }
  if (!surprises.length) {
    return html`<p class="lede">
      ${judged.length} 个 run 全部落在预期内。${batch.info_signal
        ? raw("<b>没有任何起伏的一批，信息量最低</b>——下次把变量跨度拉大些。")
        : ""}
    </p>`;
  }

  const worst = surprises
    .map((run) => {
      const deviations = Object.values(run.judgements || {})
        .map((judgement) => Number(judgement.deviation))
        .filter(Number.isFinite);
      return { run, size: deviations.length ? Math.max(...deviations.map(Math.abs)) : 0 };
    })
    .sort((a, b) => b.size - a.size)[0];

  const flipped = batch.ranking?.real_flips?.length;
  return html`<p class="lede">
    ${judged.length} 个 run 里有 <b>${surprises.length} 个超出预期</b>，最大的落差在
    <b>${worst.run.run}</b>。${flipped ? raw("相对排序也与预期相反——<b>假设本身被结果推翻了</b>。") : ""}
  </p>`;
}

function runRowHtml(batch, run, open) {
  const names = Object.keys(run.prediction?.metrics || {});
  const lead = names[0];
  const dp = decimalsFor(batch.metric_specs?.[lead]);
  const judgement = run.judgements?.[lead];
  const label = run.closed && run.verdict === "SURPRISE" ? "已复盘" : VERDICT[run.verdict] || run.verdict;

  return html`<tr class="expandable v-${run.verdict} ${run.closed ? "done" : ""} ${open ? "open" : ""}" data-run="${run.run}">
      <td>${run.run}${run.revised ? html`<br /><span class="verdict">预测已修订</span>` : ""}</td>
      <td>${names.length ? fmtPredictionAt(run.prediction.metrics[lead], dp) : "—"}</td>
      <td>${fmtActualAt(run.aggregates?.[lead], dp)}</td>
      <td>${run.aggregates?.[lead] ? `n=${run.aggregates[lead].n}` : "—"}</td>
      <td class="dev">${judgement ? fmtDeviation(judgement.deviation) : "—"}</td>
      <td><span class="verdict">${label}</span></td>
    </tr>
    ${open ? html`<tr class="detail"><td colspan="6">${panelHtml(batch, run)}</td></tr>` : ""}`;
}

function panelHtml(batch, run) {
  const names = Object.keys(run.prediction?.metrics || {});
  const detail = names.length
    ? html`<div>
        <h4>指标明细</h4>
        <table class="mini">
          <thead>
            <tr><th>指标</th><th>预测</th><th>实测</th><th>偏差</th><th>判定</th></tr>
          </thead>
          <tbody>
            ${names.map((name) => {
              const judgement = run.judgements?.[name];
              const deviation = judgement
                ? judgement.deviation === null || judgement.deviation === undefined
                  ? judgement.note || "—"
                  : fmtDeviation(judgement.deviation)
                : "—";
              const dp = decimalsFor(batch.metric_specs?.[name]);
              return html`<tr>
                <td>${name}</td>
                <td>${fmtPredictionAt(run.prediction.metrics[name], dp)}</td>
                <td>${fmtActualAt(run.aggregates?.[name], dp)}</td>
                <td>${deviation}</td>
                <td>${judgement ? VERDICT[judgement.verdict] || judgement.verdict : "未判定"}</td>
              </tr>`;
            })}
          </tbody>
        </table>
      </div>`
    : "";

  const seeds = runSeeds(run);
  const integrity = run.integrity?.length
    ? html`<div class="note hot">
        ${run.integrity.map((flag) => html`<div>${INTEGRITY[flag] || flag}</div>`)}
      </div>`
    : "";

  const rationale = run.prediction?.rationale
    ? html`<div>
        <h4>当初的理由</h4>
        <p class="quote">
          ${run.prediction.rationale}
          <span class="meta">置信度 ${CONFIDENCE[run.prediction.confidence] || run.prediction.confidence || "—"}</span>
        </p>
      </div>`
    : "";

  const reflection =
    run.closed && run.reflection
      ? html`<div>
          <h4>复盘记录</h4>
          <p class="quote">
            ${run.reflection.cause || ""}
            ${run.reflection.next ? html`<span class="meta">下一步：${run.reflection.next}</span>` : ""}
          </p>
        </div>`
      : "";

  let action = "";
  if (run.verdict === "SURPRISE" && !run.closed) action = reviewFormHtml(run);
  else if (run.verdict === "NOISY") {
    // 补 seed 是针对这一个 run 的动作，就地做。整批录入走批次级那张表。
    action = resultFormHtml(batch, run);
  }

  return html`<div class="panel">
    ${integrity}${detail}
    <p class="seeds">
      ${seeds.length ? html`已录入 seed <b>${seeds.join("、")}</b>` : "还没有结果——实验跑完后在这里录入。"}
    </p>
    ${rationale}${action}${reflection}
  </div>`;
}

export function renderBatch() {
  const { batch: batchId, run: runKey } = store.route;
  const batch = findBatch(batchId);
  const body = $("#batch-body");

  if (!batch) {
    body.innerHTML = html`<a class="crumb" href="#/batches">← 批次</a>
      <div class="blank">
        <h3>找不到这个批次。</h3>
        <p>它可能已被移动，或属于另一个研究目录。</p>
        <a class="btn ghost" href="#/">回到今天</a>
      </div>`;
    return;
  }

  const runs = batch.runs;
  const withResults = runs.filter((run) => Object.keys(run.aggregates || {}).length).length;
  const pending = runs.filter((run) => run.verdict === "SURPRISE" && !run.closed).length;
  const hit = runs.filter((run) => run.verdict === "CONFIRMED").length;
  const judged = runs.filter((run) => ["CONFIRMED", "SURPRISE"].includes(run.verdict)).length;

  const facts = [
    ...Object.entries(batch.dimensions || {}).map(
      ([name, values]) => html`<span>${name} <b>${values.length}</b> 取值</span>`,
    ),
    ...Object.entries(batch.metric_specs || {}).map(
      ([name, spec]) =>
        html`<span
          ><b>${name}</b> ${DIRECTION[spec.direction] || ""} · ${COMPARE[spec.compare] || ""}容差
          ${fmt(spec.tolerance)}</span
        >`,
    ),
    batch.result_path ? html`<span>结果模板 <b>${batch.result_path}</b></span>` : null,
    batch.idea ? html`<span><a href="#/ledger">起于想法 ${batch.idea}</a></span>` : null,
  ].filter(Boolean);

  const ranking = batch.ranking
    ? html`<div class="note ${batch.ranking.verdict === "SURPRISE" ? "hot" : ""}">
        相对排序判定：${VERDICT[batch.ranking.verdict] || batch.ranking.verdict}
        ${[...batch.ranking.real_flips, ...batch.ranking.noisy_flips].length
          ? html`<ul>
              ${batch.ranking.real_flips.map(
                (pair) => html`<li>预期 ${pair[0]} 优于 ${pair[1]}，实测相反</li>`,
              )}
              ${batch.ranking.noisy_flips.map(
                (pair) => html`<li>预期 ${pair[0]} 优于 ${pair[1]}，差异落在噪声内</li>`,
              )}
            </ul>`
          : ""}
      </div>`
    : "";

  body.innerHTML = html`
    <a class="crumb" href="#/batches">← 批次</a>
    <div class="batch-doc">
      <p class="no">
        <span>批次 ${batch.id} · RUNS ${runs.length} · ${batch.closed ? "已收口" : "进行中"}</span>
        <span class="when">${dateLabel(batch.opened_at)}</span>
      </p>
      <h2>${batch.hypothesis}</h2>
      <p class="dir">${batch.research_direction || ""}</p>
    </div>

    ${ledeHtml(batch)}
    ${facts.length ? html`<p class="facts">${facts}</p>` : ""}
    <p class="tally-line">
      <span>命中 <b>${hit}/${judged || 0}</b></span>
      <span>有结果 <b>${withResults}/${runs.length}</b></span>
      <span class="${pending ? "hot" : ""}">待复盘 <b>${pending}</b></span>
    </p>
    ${ranking}
    ${batch.warnings?.length
      ? html`<div class="note">${batch.warnings.map((line) => html`<div>${line}</div>`)}</div>`
      : ""}

    ${chartsHtml(batch)}

    <table class="ledger gap-top">
      <caption>预测 / 实测 / 偏差 —— 点一行看明细</caption>
      <thead>
        <tr><th>run</th><th>预测</th><th>实测</th><th>n</th><th>偏差</th><th class="col-verdict">判定</th></tr>
      </thead>
      <tbody id="runs-body">
        ${runs.map((run) => runRowHtml(batch, run, run.run === runKey))}
      </tbody>
    </table>

    ${resultsSectionHtml(batch)}
    ${closeHtml(batch)}
  `;

  for (const row of $$("#runs-body tr.expandable")) {
    row.onclick = (event) => {
      if (event.target.closest("form, a, button, input, textarea, select")) return;
      const key = row.dataset.run;
      location.hash =
        store.route.run === key
          ? `#/batch/${encodeURIComponent(batch.id)}`
          : `#/batch/${encodeURIComponent(batch.id)}/run/${encodeURIComponent(key)}`;
    };
  }
  bindForms(batch.id);
  bindResults(batch);

  if (store.scrollTo) {
    const row = $(`#runs-body tr.expandable[data-run="${CSS.escape(store.scrollTo)}"]`);
    if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
    store.scrollTo = null;
  }
}
