/* 批次列表。开进行中的在前，已收口的在后——收口的是档案，不是待办。 */

"use strict";

import { $, html } from "../lib/dom.js";
import { store } from "../lib/store.js";
import { batchLine } from "./today.js";

export function renderBatches() {
  const batches = store.state.batches;
  const body = $("#batches-body");

  if (!batches.length) {
    body.innerHTML = html`<div class="blank">
      <h3>还没有实验批次。</h3>
      <p>批次是一次假设检验的完整记录：设计、预测、结果与复盘，全都留在同一条时间线上。</p>
      <a class="btn" href="#/new">开第一个批次</a>
    </div>`;
    return;
  }

  const live = batches.filter((batch) => !batch.closed).reverse();
  const shut = batches.filter((batch) => batch.closed).reverse();

  body.innerHTML = html`
    <div class="acts left gap-bottom"><a class="btn" href="#/new">＋ 新批次</a></div>
    ${live.length
      ? html`<div class="rule-head"><h2>进行中（${live.length}）</h2></div>
          ${live.map(batchLine)}`
      : ""}
    ${shut.length
      ? html`<div class="rule-head"><h2>已收口（${shut.length}）</h2></div>
          ${shut.map(batchLine)}`
      : ""}
  `;
}
