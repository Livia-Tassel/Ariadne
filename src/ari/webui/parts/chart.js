/* 预测区间 vs 实测点。一个指标一张图，共用一条横轴。

   这张图回答「偏在哪、偏多少、方向对不对」，所以实测点会有一条线连回
   预测区间的边缘：偏差因此是一段可见的长度，而不是要靠读两个数字自己减。

   用 SVG 而不是绝对定位的 <i>：服务端的 CSP 是 `style-src 'self'` 且没有
   `unsafe-inline`，`style="left:12%"` 会被浏览器静默丢掉，图会整个塌在
   同一个 x 上。SVG 的 x / cx 是**属性**不是样式，CSP 不拦；而且不设
   viewBox、直接用百分比坐标，圆点不会被 preserveAspectRatio 拉变形。
*/

"use strict";

import { html } from "../lib/dom.js";
import { COMPARE, DIRECTION, decimalsFor, fmt, fmtFixed } from "../lib/fmt.js";

const H = 26; // 行高，与 .chart-row 的 CSS 一致
const MID = H / 2;

function scaleOf(runs, name) {
  let lo = Infinity;
  let hi = -Infinity;
  const push = (value) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return;
    lo = Math.min(lo, number);
    hi = Math.max(hi, number);
  };
  for (const run of runs) {
    const predicted = run.prediction?.metrics?.[name];
    if (Array.isArray(predicted)) predicted.forEach(push);
    else push(predicted);
    if (run.aggregates?.[name]) push(run.aggregates[name].mean);
    for (const value of Object.values(run.samples?.[name] || {})) push(value);
  }
  if (lo === Infinity) return null;
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.1;
  return { lo: lo - pad, hi: hi + pad };
}

const clamp = (value) => Math.min(Math.max(value, 0), 100);
const pct = (value) => `${clamp(value).toFixed(2)}%`;

function trackHtml(run, name, at, dp) {
  const predicted = run.prediction?.metrics?.[name];
  const agg = run.aggregates?.[name];
  const verdict = run.judgements?.[name]?.verdict || run.verdict;
  const miss = verdict === "SURPRISE" || verdict === "UNVERIFIED";

  const marks = [25, 50, 75].map(
    (x) => html`<line class="grid" x1="${x}%" x2="${x}%" y1="2" y2="${H - 2}" />`,
  );

  let bandLo = null;
  let bandHi = null;
  if (predicted !== undefined && predicted !== null) {
    const [low, high] = Array.isArray(predicted) ? predicted : [predicted, predicted];
    bandLo = clamp(at(low));
    bandHi = clamp(at(high));
    if (bandHi - bandLo < 0.4) {
      // 点预测：画一根竖线，不画零宽的矩形。
      marks.push(html`<line class="edge" x1="${pct(bandLo)}" x2="${pct(bandLo)}" y1="7" y2="${H - 7}" />`);
    } else {
      marks.push(
        html`<rect class="band" x="${pct(bandLo)}" y="8" width="${(bandHi - bandLo).toFixed(2)}%" height="${H - 16}" />`,
        html`<line class="edge" x1="${pct(bandLo)}" x2="${pct(bandLo)}" y1="7" y2="${H - 7}" />`,
        html`<line class="edge" x1="${pct(bandHi)}" x2="${pct(bandHi)}" y1="7" y2="${H - 7}" />`,
      );
    }
  }

  if (agg) {
    const mean = clamp(at(agg.mean));
    if (miss && bandLo !== null) {
      const from = Math.min(mean, bandLo);
      const to = Math.max(mean, bandHi);
      marks.push(html`<line class="gap" x1="${pct(from)}" x2="${pct(to)}" y1="${MID}" y2="${MID}" />`);
    }
    for (const value of Object.values(run.samples?.[name] || {})) {
      marks.push(html`<circle class="seed" cx="${pct(at(value))}" cy="${MID}" r="1.5" />`);
    }
    marks.push(html`<circle class="dot ${miss ? "miss" : ""}" cx="${pct(mean)}" cy="${MID}" r="3.5" />`);
  }

  const predictedText = Array.isArray(predicted)
    ? `${fmtFixed(predicted[0], dp)}~${fmtFixed(predicted[1], dp)}`
    : fmtFixed(predicted, dp);

  return html`<div class="chart-row ${miss ? "miss" : ""}">
    <span class="lb" title="${run.run}">${run.run}</span>
    <svg
      class="trk"
      width="100%"
      height="${H}"
      role="img"
      aria-label="${run.run} 的 ${name}：预测 ${predictedText}，实测 ${agg ? fmtFixed(agg.mean, dp) : "尚无"}"
      >${marks}</svg
    >
    <span class="val">${predictedText} → <b>${agg ? fmtFixed(agg.mean, dp) : "—"}</b></span>
  </div>`;
}

function chartHtml(batch, name) {
  const scale = scaleOf(batch.runs, name);
  if (!scale) return "";
  const span = scale.hi - scale.lo;
  const at = (value) => ((Number(value) - scale.lo) / span) * 100;
  const spec = batch.metric_specs?.[name] || {};
  const dp = decimalsFor(spec);
  const specText = [
    DIRECTION[spec.direction],
    spec.compare ? `${COMPARE[spec.compare]}容差 ${fmt(spec.tolerance)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return html`<div class="chart">
    <div class="chart-head">
      <b>${name}</b><span>${specText}</span>
      <span class="legend">
        <svg width="34" height="10" aria-hidden="true">
          <rect class="band" x="2" y="1" width="30" height="8" />
          <line class="edge" x1="2" x2="2" y1="0" y2="10" />
          <line class="edge" x1="32" x2="32" y1="0" y2="10" />
        </svg>
        预测区间
        <svg width="10" height="10" aria-hidden="true"><circle class="dot" cx="5" cy="5" r="3.5" /></svg>
        实测均值
      </span>
    </div>
    ${batch.runs.map((run) => trackHtml(run, name, at, dp))}
    <div class="chart-axis">
      <span>${fmtFixed(scale.lo, dp)}</span><span>${fmtFixed((scale.lo + scale.hi) / 2, dp)}</span
      ><span>${fmtFixed(scale.hi, dp)}</span>
    </div>
  </div>`;
}

export function chartsHtml(batch) {
  const names = new Set();
  for (const run of batch.runs) {
    for (const name of Object.keys(run.prediction?.metrics || {})) names.add(name);
  }
  if (!names.size) return "";
  return [...names].map((name) => chartHtml(batch, name));
}
