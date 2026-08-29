/* 渐进锁定：逐个 run 锁预测。

   约束只有一条，而且是逐 run 的——某个 run 的预测必须先于它的结果。所以
   不需要在跑任何实验之前把 N×M 个格子填完；先跑两个 run 也完全合法。

   锁晚了不会被拒绝，但投影层会永久记下 prediction_after_result。工具的
   立场是：不阻止你事后补预测，但那条记录会一直带着这个标记。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { post, showError, submitting, toast } from "../lib/api.js";
import { refresh } from "../lib/store.js";

export function lockSectionHtml(batch) {
  const unlocked = batch.unlocked || [];
  if (batch.closed || !unlocked.length) return "";

  const withResult = new Set(
    batch.runs.filter((run) => Object.keys(run.aggregates || {}).length).map((run) => run.run),
  );
  const late = unlocked.filter((run) => withResult.has(run));

  return html`<div class="rule-head">
      <h2>锁定预测</h2>
      <span class="tally">${unlocked.length} 个 run 还没有预测</span>
    </div>
    ${late.length
      ? html`<div class="note hot">
          这 ${late.length} 个 run 的结果已经在库了。现在补写的预测会被永久标记为
          <b>事后补写</b>——数据不会被拒绝，但这条记录以后一直带着这个标记。
        </div>`
      : ""}
    <form id="lock-form" class="inline-form">
      <p class="seeds">
        预测可以是点值（0.83）或区间（0.80 ~ 0.84）。理由必填——它决定复盘时能否找到
        真正出错的那个假设。留空的行会跳过，不必一次锁完。
      </p>
      <table class="ledger">
        <thead>
          <tr>
            <th>run</th>
            ${batch.metrics.map((name) => html`<th>${name} 预测</th>`)}
            <th class="col-conf">置信度</th>
            <th class="col-why">为什么这么预期</th>
          </tr>
        </thead>
        <tbody>
          ${unlocked.map(
            (run) => html`<tr class="lock-row ${withResult.has(run) ? "v-UNVERIFIED" : ""}" data-run="${run}">
              <td>${run}${withResult.has(run) ? html`<br /><span class="verdict">结果已在库</span>` : ""}</td>
              ${batch.metrics.map(
                (name) => html`<td><input class="lk-val mono" data-metric="${name}" placeholder="0.83 或 0.80 ~ 0.84" /></td>`,
              )}
              <td>
                <select class="lk-conf">
                  <option value="low">低</option>
                  <option value="medium" selected>中</option>
                  <option value="high">高</option>
                </select>
              </td>
              <td><input class="lk-why" placeholder="影响这个判断的关键依据" /></td>
            </tr>`,
          )}
        </tbody>
      </table>
      <div class="acts left"><button type="submit" class="btn">锁定</button></div>
      <div class="err" hidden></div>
    </form>`;
}

export function bindLock(batch) {
  const form = $("#lock-form");
  if (!form) return;

  form.onsubmit = async (event) => {
    event.preventDefault();
    const predictions = [];
    for (const row of $$(".lock-row", form)) {
      const values = $$(".lk-val", row);
      if (values.every((input) => !input.value.trim())) continue; // 整行留空 = 这次不锁它
      predictions.push({
        run: row.dataset.run,
        metrics: Object.fromEntries(
          values.map((input) => [input.dataset.metric, input.value.trim()]),
        ),
        confidence: $(".lk-conf", row).value,
        rationale: $(".lk-why", row).value.trim(),
      });
    }
    if (!predictions.length) {
      showError($(".err", form), new Error("没有填写任何一行"));
      return;
    }
    const ok = await submitting(form, async () => {
      const result = await post("/api/predictions", { batch: batch.id, predictions });
      toast(`已锁定 ${result.locked} 条预测`);
    });
    if (ok) await refresh();
  };
}
