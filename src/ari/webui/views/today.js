/* 首屏：一列排好序的待办。不放计数瓦片。

   排序即优先级，且顺序有依据：
   1 待复盘的意外 —— 信息量最大，且唯一会随时间衰减（隔一周你就想不起
     当时为什么那么预期）。
   2 预测缺席但结果已在库 —— 这是本工具要防的那件事。
   3 补 seed / 等结果 / 可收口 —— 按批次归并，不逐 run 罗列。
*/

"use strict";

import { $, html } from "../lib/dom.js";
import { CONFIDENCE, decimalsFor, fmtDeviation, fmtFixed, leadMetric } from "../lib/fmt.js";
import { hitRate, store, todos } from "../lib/store.js";

const link = (batch, run) =>
  run
    ? `#/batch/${encodeURIComponent(batch)}/run/${encodeURIComponent(run)}`
    : `#/batch/${encodeURIComponent(batch)}`;

/** 一句话说清这个 run 上发生了什么，让人不用点进去就能判断要不要现在处理。 */
function movement(run, batch) {
  const name = leadMetric(run);
  const predicted = run.prediction?.metrics?.[name];
  const agg = run.aggregates?.[name];
  const judgement = run.judgements?.[name];
  if (predicted === undefined || !agg) return null;
  const dp = decimalsFor(batch?.metric_specs?.[name]);
  const point = Array.isArray(predicted)
    ? `${fmtFixed(predicted[0], dp)}~${fmtFixed(predicted[1], dp)}`
    : fmtFixed(predicted, dp);
  const deviation = judgement ? fmtDeviation(judgement.deviation) : "";
  return html`<span class="move"
    >${point} → <b>${fmtFixed(agg.mean, dp)}</b>${deviation && deviation !== "—" ? html`　<b>${deviation}</b>` : ""}</span
  >`;
}

function rowHtml(item) {
  const { kind, batch, run, act, hot, count } = item;

  if (!run) {
    const what =
      kind === "等结果"
        ? html`<small>${count} 个 run 还没跑完</small>`
        : html`<small>结果齐了、意外已复盘，可以写批次结论</small>`;
    return html`<a class="todo-row" href="${link(batch.id)}">
      <span class="todo-kind">${kind}</span>
      <span class="todo-where">${batch.id}</span>
      <span class="todo-what">${what}</span>
      <span class="todo-go">${act ? `${act} →` : ""}</span>
    </a>`;
  }

  const move = movement(run, batch);
  const what =
    kind === "预测缺席"
      ? html`<small>结果已在库，没有预测可比对，无法判定</small>`
      : kind === "补 seed"
        ? html`<small>${noiseNote(run)}</small>`
        : move || html`<small>等结果</small>`;

  return html`<a class="todo-row ${hot ? "hot" : ""}" href="${link(batch.id, run.run)}">
    <span class="todo-kind">${kind}</span>
    <span class="todo-where">${batch.id}</span>
    <span class="todo-what"><span class="run">${run.run}</span>${what}</span>
    <span class="todo-go">${act} →</span>
  </a>`;
}

function noiseNote(run) {
  for (const judgement of Object.values(run.judgements || {})) {
    if (judgement.verdict === "NOISY" && judgement.note) return judgement.note;
  }
  return "seed 间方差已超过判定分辨率";
}

/* 校准记录：这个工具存在的理由。
   不是记账，是让你看见自己的判断在哪个方向上系统性地偏。 */
function calibrationHtml() {
  const cal = store.state.calibration;
  if (!cal || !cal.judged) return "";

  // 带符号偏差：一直高估和一直低估是两种毛病，取绝对值会把它们抵消掉。
  const bias =
    cal.bias === null
      ? null
      : html`你平均<b>${cal.bias > 0 ? "低估" : "高估"}了 ${fmtDeviation(Math.abs(cal.bias)).slice(1)}</b>`;

  const levels = cal.by_confidence.filter((row) => row.judged);
  // 说「高」时的命中率不高于说「低」时，这个字段就是噪声。
  const high = levels.find((row) => row.level === "high");
  const low = levels.find((row) => row.level === "low");
  const useless =
    high && low && high.judged >= 3 && low.judged >= 3 && high.hit / high.judged <= low.hit / low.judged;

  return html`<div class="rule-head"><h2>校准记录</h2><span class="tally">你自己准不准</span></div>
    <p class="tally-line">
      <span>命中 <b>${cal.hit}/${cal.judged}</b></span>
      ${bias ? html`<span>${bias}</span>` : ""}
    </p>
    ${levels.length > 1
      ? html`<table class="ledger gap-top">
            <caption>按你当时写下的置信度分档</caption>
            <thead>
              <tr><th>置信度</th><th>已判定</th><th>命中</th><th>命中率</th></tr>
            </thead>
            <tbody>
              ${levels.map(
                (row) => html`<tr>
                  <td>${CONFIDENCE[row.level] || row.level}</td>
                  <td>${row.judged}</td>
                  <td>${row.hit}</td>
                  <td>${Math.round((row.hit / row.judged) * 100)}%</td>
                </tr>`,
              )}
            </tbody>
          </table>
          ${useless
            ? html`<div class="note hot">
                你说「高」的时候并不比说「低」时更准——这个置信度字段目前是噪声。
              </div>`
            : ""}`
      : ""}
    ${cal.recent.length
      ? html`<p class="spread-strip">
          <span class="lbl">最近的落差</span>
          ${cal.recent.map(
            (row) => html`<s class="${row.hot ? "hot" : ""}" title="${row.batch} ${row.run} · ${row.metric}"
              >${fmtDeviation(row.deviation)}</s
            >`,
          )}
        </p>`
      : ""}`;
}

function blankProject() {
  return html`<div class="blank">
    <h3>先写下你以为会发生什么。</h3>
    <p>
      开一个批次只要三样：一句能被这批实验检验的假设、要变的变量、要看的指标。
      预测可以等到某个 run 真要开跑之前再锁——但必须先于它的结果。
    </p>
    <a class="btn" href="#/new">开第一个批次</a>
    <a class="link side" href="#/ledger">还只是个念头，先记进账本</a>
  </div>`;
}

export function renderToday() {
  const s = store.state;
  const items = todos();
  const { hit, judged } = hitRate();

  $("#today-sub").textContent = judged
    ? `已判定 ${judged} 个 run，命中 ${hit} 个。负结果和正结果一样值钱，最没价值的是没有起伏的一批。`
    : "先预测，再验证——把意外变成知识。";

  const notices = [
    ...s.parse_errors.map((item) => `runs.jsonl 第 ${item.line_no} 行：${item.reason}`),
    ...s.warnings,
  ];

  if (!s.batches.length) {
    $("#today-body").innerHTML = blankProject();
    return;
  }

  $("#today-body").innerHTML = html`
    ${notices.length ? html`<div class="note hot">${notices.map((line) => html`<div>${line}</div>`)}</div>` : ""}
    <div class="todo">
      ${items.length
        ? items.map(rowHtml)
        : html`<p class="todo-empty">没有需要立刻处理的事。去跑实验吧——回来录入结果，判定会自动更新。</p>`}
    </div>
    ${calibrationHtml()}
    <div class="rule-head"><h2>最近的批次</h2><a href="#/batches">查看全部</a></div>
    ${s.batches.slice(-5).reverse().map(batchLine)}
  `;
}

export function batchLine(batch) {
  const runs = batch.runs;
  const withResults = runs.filter((run) => Object.keys(run.aggregates || {}).length).length;
  const pending = runs.filter((run) => run.verdict === "SURPRISE" && !run.closed).length;
  const tally = [
    `${runs.length} run`,
    withResults ? `${withResults} 有结果` : null,
    batch.closed ? "已收口" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return html`<a class="batch-line ${batch.closed ? "shut" : ""}" href="#/batch/${encodeURIComponent(batch.id)}">
    <span class="bid">${batch.id}</span>
    <span class="hyp">${batch.hypothesis} <em>${batch.research_direction || ""}</em></span>
    <span class="tally">${tally}${pending ? html`　<b>${pending} 待复盘</b>` : ""}</span>
  </a>`;
}
