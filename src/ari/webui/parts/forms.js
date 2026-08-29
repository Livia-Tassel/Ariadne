/* 批次里的三种就地表单：录结果、写复盘、收口。

   都不跳页、不开弹窗——填写发生在你看着数据的地方。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { post, submitting, toast } from "../lib/api.js";
import { decimalsFor, fmtFixed, nextSeed, runSeeds } from "../lib/fmt.js";
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

/* ---------- 修订预测 ---------- */

export function reviseFormHtml(batch, run) {
  const dp = decimalsFor(batch.metric_specs?.[batch.metrics[0]]);
  const hasResult = Object.keys(run.aggregates || {}).length > 0;
  return html`<details class="revise">
    <summary>修订这条预测</summary>
    <form class="inline-form revise-form" data-run="${run.run}">
      ${hasResult
        ? html`<div class="note hot">
            结果已经在库了。改预测本身合法，但这条记录会永久带上「看到结果之后改过」——
            那正是这个工具要防的那件事。原值也会保留。
          </div>`
        : html`<p class="seeds">原值会保留在账本里，不会被覆盖。</p>`}
      <div class="inline-grid">
        ${batch.metrics.map(
          (name) => html`<div class="field">
            <label>${name} 新预测</label>
            <input class="rv-val mono" data-metric="${name}" placeholder="${fmtFixed(0, dp)} 或区间" required />
          </div>`,
        )}
        <div class="field narrow">
          <label>置信度</label>
          <select class="rv-conf">
            <option value="low">低</option>
            <option value="medium" selected>中</option>
            <option value="high">高</option>
          </select>
        </div>
      </div>
      <div class="field">
        <label>为什么要改？<span class="hint">（必填——三个月后你会想知道）</span></label>
        <input class="rv-why" placeholder="例如：看错了 baseline 的数据集划分" required />
      </div>
      <div class="acts left"><button type="submit" class="btn sm">修订</button></div>
      <div class="err" hidden></div>
    </form>
  </details>`;
}

/* ---------- 预期排序 ---------- */

export function rankingFormHtml(batch) {
  if (batch.closed) return "";
  const runs = [...batch.runs.map((r) => r.run), ...(batch.unlocked || [])];
  if (runs.length < 2) return "";
  const current = batch.expected_ranking;
  return html`<details class="revise">
    <summary>${current ? "改预期排序" : "声明预期排序（可选）"}</summary>
    <form class="inline-form ranking-form">
      <p class="seeds">
        除了每个 run 的数值，你还可以预先声明「谁会赢」。排序判定独立于数值判定——
        数值全落在容差内、但相对顺序反了，同样是意外。一行一个 run，从好到差。
      </p>
      <div class="inline-grid">
        <div class="field">
          <label>指标</label>
          <select class="rk-metric">
            ${batch.metrics.map((name) => html`<option value="${name}">${name}</option>`)}
          </select>
        </div>
      </div>
      <div class="field">
        <label>预期顺序<span class="hint">（一行一个，从好到差；可只列你有把握的几个）</span></label>
        <textarea class="rk-order mono" rows="${Math.min(runs.length, 6)}"
          placeholder="${runs.slice(0, 2).join("\n")}">${(current?.order || []).join("\n")}</textarea>
      </div>
      <div class="acts left"><button type="submit" class="btn sm">保存预期排序</button></div>
      <div class="err" hidden></div>
    </form>
  </details>`;
}

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

  for (const form of $$("#batch-body form.revise-form")) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      const ok = await submitting(form, async () => {
        await post("/api/predictions/revise", {
          batch: batchId,
          run: form.dataset.run,
          metrics: Object.fromEntries(
            $$(".rv-val", form).map((input) => [input.dataset.metric, input.value.trim()]),
          ),
          confidence: $(".rv-conf", form).value,
          rationale: $(".rv-why", form).value,
        });
        toast("预测已修订，原值保留在账本里");
      });
      if (ok) await refresh();
    };
  }

  const rankingForm = $("#batch-body form.ranking-form");
  if (rankingForm) {
    rankingForm.onsubmit = async (event) => {
      event.preventDefault();
      const order = $(".rk-order", rankingForm)
        .value.split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const ok = await submitting(rankingForm, async () => {
        await post("/api/batches/meta", {
          batch: batchId,
          expected_ranking: { metric: $(".rk-metric", rankingForm).value, order },
        });
        toast("预期排序已声明");
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
