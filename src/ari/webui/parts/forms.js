/* 批次里的三种就地表单：录结果、写复盘、收口。

   都不跳页、不开弹窗——填写发生在你看着数据的地方。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { post, submitting, toast } from "../lib/api.js";
import { nextSeed, runSeeds } from "../lib/fmt.js";
import { refresh, store } from "../lib/store.js";

/* ---------- 录结果 ---------- */

export function resultFormHtml(batch, run) {
  const seeds = runSeeds(run);
  return html`<form class="inline-form result-form" data-run="${run.run}">
    <div>
      <h4>录入这个 run 的结果</h4>
      <div class="inline-grid">
        <div class="field narrow">
          <label>seed</label>
          <input class="seed-in mono" type="number" step="1" value="${nextSeed(run)}" required />
        </div>
        ${batch.metrics.map(
          (name) => html`<div class="field">
            <label>${name}</label>
            <input class="metric-in mono" data-metric="${name}" inputmode="decimal" placeholder="实测值" required />
          </div>`,
        )}
        <button class="btn sm" type="submit">保存</button>
      </div>
    </div>
    <p class="seeds">
      ${seeds.length ? `已录入 seed ${seeds.join("、")}；已有的不会被覆盖。` : "保存后自动重新判定。"}
    </p>
    <div class="err" hidden></div>
  </form>`;
}

/* ---------- 复盘 ---------- */

function beliefRowsHtml() {
  const active = store.state.beliefs.filter((belief) => !belief.refuted);
  if (!active.length) return "";
  return html`<div>
    <h4>这次结果改变了哪些已有信念？</h4>
    ${active.map(
      (belief) => html`<div class="entry belief-change">
        <span class="txt">${belief.text} <small>${belief.id}</small></span>
        <select data-belief="${belief.id}">
          <option value="unchanged">没有改变</option>
          <option value="reinforced">得到加强</option>
          <option value="weakened">有所动摇</option>
          <option value="refuted">被推翻</option>
        </select>
      </div>`,
    )}
  </div>`;
}

export function reviewFormHtml(run) {
  return html`<form class="inline-form review-form" data-run="${run.run}">
    <div>
      <h4>写下复盘</h4>
      <div class="field">
        <label>你认为为什么会这样？</label>
        <textarea class="r-cause prose" rows="3" placeholder="如果还不知道，就写下准备如何排查。" required></textarea>
      </div>
      <div class="field">
        <label>下一步准备做什么？<span class="hint">（可留空）</span></label>
        <textarea class="r-next prose" rows="2"></textarea>
      </div>
      <div class="field">
        <label>这次之后你新相信了什么？<span class="hint">（一行一条，可留空）</span></label>
        <textarea class="r-beliefs prose" rows="2"></textarea>
      </div>
    </div>
    ${beliefRowsHtml()}
    <div class="acts left"><button class="btn sm" type="submit">存下这次复盘</button></div>
    <div class="err" hidden></div>
  </form>`;
}

/* ---------- 收口 ---------- */

export function closeHtml(batch) {
  if (batch.closed) {
    return html`<div class="rule-head"><h2>批次收口</h2></div>
      <p class="seeds pad-y">已写下批次级结论，这个批次的闭环完成。</p>`;
  }
  if (batch.close_blockers.length) {
    return html`<div class="rule-head"><h2>批次收口</h2></div>
      <div class="note">
        还差这几件事：
        <ul>
          ${batch.close_blockers.map((item) => html`<li>${item}</li>`)}
        </ul>
      </div>`;
  }
  return html`<div class="rule-head"><h2>批次收口</h2></div>
    <form class="inline-form close-form" data-batch="${batch.id}">
      <div class="field">
        <label>这一批整体学到了什么？</label>
        <textarea class="c-cause prose" rows="3" required></textarea>
      </div>
      <div class="field">
        <label>下一批准备验证什么？<span class="hint">（可留空）</span></label>
        <textarea class="c-next prose" rows="2"></textarea>
      </div>
      <div class="field">
        <label>新增信念<span class="hint">（一行一条，可留空）</span></label>
        <textarea class="c-beliefs prose" rows="2"></textarea>
      </div>
      ${beliefRowsHtml()}
      <div class="acts left"><button class="btn" type="submit">收口批次</button></div>
      <div class="err" hidden></div>
    </form>`;
}

/* ---------- 接线 ---------- */

const changesIn = (form) =>
  Object.fromEntries(
    $$("select[data-belief]", form).map((select) => [select.dataset.belief, select.value]),
  );

export function bindForms(batchId) {
  for (const form of $$("#batch-body form.result-form")) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      const metrics = Object.fromEntries(
        $$(".metric-in", form).map((input) => [input.dataset.metric, input.value.trim()]),
      );
      const ok = await submitting(form, async () => {
        const result = await post("/api/results", {
          batch: batchId,
          rows: [{ run: form.dataset.run, seed: $(".seed-in", form).value, metrics }],
        });
        toast(`已保存 ${result.written} 条结果，判定已更新`);
      });
      if (ok) await refresh();
    };
  }

  for (const form of $$("#batch-body form.review-form")) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      const ok = await submitting(form, async () => {
        await post("/api/reviews", {
          batch: batchId,
          run: form.dataset.run,
          cause: $(".r-cause", form).value,
          next: $(".r-next", form).value,
          beliefs_added: $(".r-beliefs", form).value,
          belief_changes: changesIn(form),
        });
        toast("复盘已存下，这次意外进了知识记录");
      });
      if (ok) await refresh();
    };
  }

  const closeForm = $("#batch-body form.close-form");
  if (closeForm) {
    closeForm.onsubmit = async (event) => {
      event.preventDefault();
      const ok = await submitting(closeForm, async () => {
        await post("/api/batches/close", {
          batch: batchId,
          cause: $(".c-cause", closeForm).value,
          next: $(".c-next", closeForm).value,
          beliefs_added: $(".c-beliefs", closeForm).value,
          belief_changes: changesIn(closeForm),
        });
        toast(`批次 ${batchId} 已收口`);
      });
      if (ok) await refresh();
    };
  }
}
