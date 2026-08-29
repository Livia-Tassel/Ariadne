/* 录结果。

   主路径是自动发现：结果形态是每个 run 一个 JSON/YAML，路径能套模板。
   抽到的先给人看一眼——「抽到了这些，对吗？」——确认后才落盘。CLI 一直
   是这么做的，GUI 此前完全没有。

   这不只是省敲键盘：project._check_integrity 靠结果文件的 mtime 判断
   「先看结果再补预测」，而 mtime 只存在于文件发现这条路上。手敲没有
   mtime，也就没有这个检查。

   手工录入保留为退路，但改成整批一张表：6 run × 3 seed 原本要展开-填-
   提交 18 轮，现在是一张表一次提交。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { post, showError, submitting, toast } from "../lib/api.js";
import { decimalsFor, fmtFixed, nextSeed } from "../lib/fmt.js";
import { refresh } from "../lib/store.js";

/** 待确认的发现结果。只活在内存里，刷新即弃。 */
let scan = null;

export function resultsSectionHtml(batch) {
  const missing = batch.runs.filter((run) => !Object.keys(run.aggregates || {}).length).length;
  if (batch.closed) return "";

  return html`<div class="rule-head">
      <h2>录入结果</h2>
      <span class="tally">${missing ? `${missing} 个 run 还没有结果` : "全部 run 都有结果"}</span>
    </div>
    <div id="results-box">
      ${batch.result_path
        ? html`<div class="scan-line">
            <span class="seeds">结果模板 <b>${batch.result_path}</b></span>
            <button type="button" class="btn sm" id="scan">扫描结果文件</button>
            <button type="button" class="btn ghost sm" id="to-manual">改为手工录入</button>
          </div>`
        : html`<form id="path-form" class="inline-form">
            <div class="field">
              <label for="rp">
                结果文件路径模板
                <span class="hint">
                  填了才能自动扫描，也才有「先看结果再补预测」的检查——手敲没有文件时间戳。
                </span>
              </label>
              <input id="rp" class="mono" placeholder="logs/{model}/s{seed}/results.json" />
            </div>
            <div class="acts left">
              <button type="submit" class="btn sm">保存模板</button>
              <button type="button" class="btn ghost sm" id="to-manual">先手工录入</button>
            </div>
            <div class="err" hidden></div>
          </form>`}
    </div>`;
}

/* ---------- 「抽到了这些，对吗？」 ---------- */

function confirmHtml(batch) {
  const dp = decimalsFor(batch.metric_specs?.[batch.metrics[0]]);
  const usable = scan.found.filter((row) => !row.existing && !row.missing.length);

  return html`<div class="inline-form">
    <h4>抽到了这些，对吗？</h4>
    ${scan.found.length
      ? html`<table class="ledger pick-table">
          <thead>
            <tr>
              <th class="col-pick"></th>
              <th>run</th>
              <th>seed</th>
              ${batch.metrics.map((name) => html`<th>${name}</th>`)}
              <th class="col-src">来源文件</th>
            </tr>
          </thead>
          <tbody>
            ${scan.found.map((row, index) => {
              const blocked = row.existing || row.missing.length > 0;
              const why = row.existing
                ? "已录过这个 seed"
                : row.missing.length
                  ? `文件里没有 ${row.missing.join("、")}`
                  : "";
              return html`<tr class="${blocked ? "v-NO_RESULT" : ""}">
                <td class="col-pick">
                  <input type="checkbox" class="pick-row" data-at="${index}" ${blocked ? "" : "checked"} ${blocked ? "disabled" : ""} />
                </td>
                <td>${row.run}</td>
                <td>${row.seed}</td>
                ${batch.metrics.map(
                  (name) =>
                    html`<td>${row.metrics[name] === undefined ? "—" : fmtFixed(row.metrics[name], dp)}</td>`,
                )}
                <td class="col-src">${row.source.path}${why ? html` <span class="verdict">${why}</span>` : ""}</td>
              </tr>`;
            })}
          </tbody>
        </table>`
      : html`<p class="seeds">
          按模板 <b>${batch.result_path}</b> 没找到结果文件。实验跑完了吗？或者改用手工录入。
        </p>`}

    ${scan.unmatched.length
      ? html`<div class="note">
          这些文件对得上模板，但不属于本批次的任何 run——模板写错了？还是跑了计划外的配置？
          <ul>
            ${scan.unmatched.map((path) => html`<li>${path}</li>`)}
          </ul>
        </div>`
      : ""}
    ${scan.errors.length
      ? html`<div class="note hot">
          这些文件读不了：
          <ul>
            ${scan.errors.map((item) => html`<li>${item.path}：${item.reason}</li>`)}
          </ul>
        </div>`
      : ""}

    <form id="confirm-form">
      <div class="acts left">
        <button type="submit" class="btn" ${usable.length ? "" : "disabled"}>
          写入选中的 ${usable.length} 条
        </button>
        <button type="button" class="btn ghost" id="cancel-scan">取消</button>
        <button type="button" class="btn ghost" id="to-manual">改为手工录入</button>
      </div>
      <div class="err" hidden></div>
    </form>
  </div>`;
}

/* ---------- 整批一张表 ---------- */

function manualHtml(batch) {
  const dp = decimalsFor(batch.metric_specs?.[batch.metrics[0]]);
  return html`<form id="manual-form" class="inline-form">
    <h4>整批录入</h4>
    <p class="seeds">
      一张表填完一次提交。同一配置跑了多个 seed 就点「再加一组 seed」——seed
      之间的离散程度就是噪声基线，只跑一个 seed 时判定无法校准。留空的行会跳过。
    </p>
    <table class="ledger">
      <thead>
        <tr>
          <th>run</th>
          <th>seed</th>
          ${batch.metrics.map((name) => html`<th>${name}</th>`)}
          <th>已录入</th>
        </tr>
      </thead>
      <tbody id="manual-body">
        ${batch.runs.map((run) => manualRowHtml(batch, run, nextSeed(run), dp))}
      </tbody>
    </table>
    <div class="acts left">
      <button type="submit" class="btn">写入</button>
      <button type="button" class="btn ghost" id="add-seed">＋ 再加一组 seed</button>
      ${batch.result_path ? html`<button type="button" class="btn ghost" id="back-scan">改回自动扫描</button>` : ""}
    </div>
    <div class="err" hidden></div>
  </form>`;
}

function manualRowHtml(batch, run, seed, dp) {
  const done = Object.values(run.samples || {})[0];
  return html`<tr class="manual-row" data-run="${run.run}">
    <td>${run.run}</td>
    <td><input class="m-seed mono" type="number" step="1" value="${seed}" /></td>
    ${batch.metrics.map(
      (name) => html`<td><input class="m-val mono" data-metric="${name}" inputmode="decimal" placeholder="${fmtFixed(0, dp)}" /></td>`,
    )}
    <td class="verdict">${done ? Object.keys(done).sort((a, b) => a - b).join("、") : "—"}</td>
  </tr>`;
}

/* ---------- 接线 ---------- */

export function bindResults(batch) {
  const box = $("#results-box");
  if (!box) return;

  const render = (content) => {
    box.innerHTML = content;
    wire();
  };

  const showManual = () => {
    scan = null;
    render(manualHtml(batch));
  };

  function wire() {
    const scanBtn = $("#scan", box);
    if (scanBtn) {
      scanBtn.onclick = async () => {
        scanBtn.disabled = true;
        scanBtn.textContent = "扫描中…";
        try {
          scan = await post("/api/results/discover", { batch: batch.id });
          render(confirmHtml(batch));
        } catch (error) {
          toast(error.message, true);
          scanBtn.disabled = false;
          scanBtn.textContent = "扫描结果文件";
        }
      };
    }

    for (const button of $$("#to-manual", box)) button.onclick = showManual;
    const back = $("#back-scan", box);
    if (back) back.onclick = () => render(resultsInner(batch));
    const cancel = $("#cancel-scan", box);
    if (cancel)
      cancel.onclick = () => {
        scan = null;
        render(resultsInner(batch));
      };

    const pathForm = $("#path-form", box);
    if (pathForm) {
      pathForm.onsubmit = async (event) => {
        event.preventDefault();
        const ok = await submitting(pathForm, async () => {
          await post("/api/batches/meta", { batch: batch.id, result_path: $("#rp", box).value });
          toast("结果模板已保存");
        });
        if (ok) await refresh();
      };
    }

    const confirmForm = $("#confirm-form", box);
    if (confirmForm) {
      confirmForm.onsubmit = async (event) => {
        event.preventDefault();
        const rows = $$(".pick-row:checked", box).map((input) => scan.found[Number(input.dataset.at)]);
        if (!rows.length) {
          showError($(".err", confirmForm), new Error("没有选中任何一条"));
          return;
        }
        const ok = await submitting(confirmForm, async () => {
          const result = await post("/api/results", { batch: batch.id, rows });
          toast(`已写入 ${result.written} 条结果，判定已更新`);
          scan = null;
        });
        if (ok) await refresh();
      };
    }

    const manualForm = $("#manual-form", box);
    if (manualForm) {
      $("#add-seed", box).onclick = () => {
        const body = $("#manual-body", box);
        const dp = decimalsFor(batch.metric_specs?.[batch.metrics[0]]);
        const bump = new Map();
        for (const row of $$(".manual-row", body)) {
          const key = row.dataset.run;
          bump.set(key, Math.max(bump.get(key) ?? -1, Number($(".m-seed", row).value)));
        }
        for (const run of batch.runs) {
          body.insertAdjacentHTML(
            "beforeend",
            String(manualRowHtml(batch, run, (bump.get(run.run) ?? -1) + 1, dp)),
          );
        }
      };

      manualForm.onsubmit = async (event) => {
        event.preventDefault();
        const rows = [];
        for (const row of $$(".manual-row", box)) {
          const values = $$(".m-val", row);
          if (values.every((input) => !input.value.trim())) continue; // 整行留空 = 跳过
          rows.push({
            run: row.dataset.run,
            seed: $(".m-seed", row).value,
            metrics: Object.fromEntries(
              values.map((input) => [input.dataset.metric, input.value.trim()]),
            ),
          });
        }
        if (!rows.length) {
          showError($(".err", manualForm), new Error("没有填写任何一行"));
          return;
        }
        const ok = await submitting(manualForm, async () => {
          const result = await post("/api/results", { batch: batch.id, rows });
          toast(`已写入 ${result.written} 条结果，判定已更新`);
        });
        if (ok) await refresh();
      };
    }
  }

  wire();
}

/** 未展开任何面板时的默认内容——与 resultsSectionHtml 的内层保持一致。 */
function resultsInner(batch) {
  return html`<div class="scan-line">
    <span class="seeds">结果模板 <b>${batch.result_path}</b></span>
    <button type="button" class="btn sm" id="scan">扫描结果文件</button>
    <button type="button" class="btn ghost sm" id="to-manual">改为手工录入</button>
  </div>`;
}
