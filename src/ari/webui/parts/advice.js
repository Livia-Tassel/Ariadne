/* AI 那一层的两个触点。

   整层可选。不配 config.toml、不设 API key、断网，界面行为都不变——只是
   少了 AI 那一段：不报错、不阻断、不需要加任何 flag。

   锚定效应是硬约束：「看 AI 的判断」只在至少锁定一个 run 的预测之后才
   出现。先看到 AI 的判断，你自己的预测就失去了独立性——而独立性正是这套
   机制价值的来源。所以不是「先算好、晚点再显示」，是那时候根本还没算。

   输出只以 note 事件存档，绝不参与判定。
*/

"use strict";

import { $, html } from "../lib/dom.js";
import { post, toast } from "../lib/api.js";
import { refresh } from "../lib/store.js";

/* ---------- 批次：AI 的定性判断 ---------- */

export function adviceSectionHtml(batch) {
  const locked = batch.runs.filter((run) => run.prediction).length;
  if (!locked) return ""; // 一个预测都没锁，现在问就是锚定

  return html`<div class="rule-head">
      <h2>AI 的判断</h2>
      <span class="tally">只给方向，不给数值</span>
    </div>
    <div id="advice-box">${adviceBody(batch)}</div>`;
}

function adviceBody(batch) {
  if (!batch.advice) {
    return html`<div class="scan-line">
      <span class="seeds">
        你的预测已经落盘，现在可以看一份独立判断了：预期排序、各变量的影响方向、
        你可能没考虑到的混淆因素。<b>不给任何数值</b>——通用模型对你的私有数据集
        没有有效先验，编出来的数字看似精确实则是猜的。
      </span>
      <button type="button" class="btn sm" id="ask-advice">看 AI 的判断</button>
    </div>`;
  }

  const { ranking, directions, confounders } = batch.advice;
  // 实测排序要看指标方向：loss 越小越好，排在前面的是小的那个。
  const metric = batch.metrics[0];
  const lowerBetter = batch.metric_specs?.[metric]?.direction === "lower_better";
  const yours = [...batch.runs]
    .filter((run) => run.aggregates?.[metric])
    .sort((a, b) => {
      const gap = a.aggregates[metric].mean - b.aggregates[metric].mean;
      return lowerBetter ? gap : -gap;
    })
    .map((run) => run.run);

  return html`<div class="advice">
    <div class="advice-block">
      <h4>预期排序（好 → 差）</h4>
      <ol class="rank">
        ${(ranking || []).map(
          (run, index) => html`<li class="${yours.length && yours[index] !== run ? "off" : ""}">${run}</li>`,
        )}
      </ol>
      ${yours.length
        ? html`<p class="seeds">
            实测排序：${yours.join(" › ")}。<b>不一致的地方本身就是有信息量的信号</b>。
          </p>`
        : ""}
    </div>
    ${directions?.length
      ? html`<div class="advice-block">
          <h4>变量的影响</h4>
          ${directions.map((item) => html`<p class="quote">${item.variable}：${item.effect}</p>`)}
        </div>`
      : ""}
    ${confounders?.length
      ? html`<div class="advice-block">
          <h4>可能没考虑到的混淆因素</h4>
          <ul class="blockers">
            ${confounders.map((item) => html`<li>${item}</li>`)}
          </ul>
        </div>`
      : ""}
    <p class="seeds">这份判断只作为 note 存档，不参与任何判定。</p>
  </div>`;
}

export function bindAdvice(batch) {
  const button = $("#ask-advice");
  if (!button) return;
  button.onclick = async () => {
    button.disabled = true;
    button.textContent = "问一次…";
    try {
      const result = await post("/api/advice", { batch: batch.id });
      if (!result.available) {
        // 降级不是错误：说清楚为什么没有，然后照常用。
        $("#advice-box").innerHTML = html`<div class="note">
          这次没有 AI 的那份判断：${result.reason}<br />
          <span class="seeds">整层都是可选的——其余功能不受影响。</span>
        </div>`;
        return;
      }
      await refresh();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
      button.textContent = "看 AI 的判断";
    }
  };
}

/* ---------- 复盘：一条有针对性的追问 ---------- */

export function probeHtml(run) {
  if (run.probe) {
    return html`<div class="ask">
      <span class="q">AI 的追问</span>
      <p>${run.probe.question || run.probe}</p>
    </div>`;
  }
  return html`<div class="scan-line">
    <span class="seeds">它会先检索本项目历史上相似的意外与当时的结论，再问一个具体的问题。</span>
    <button type="button" class="btn ghost sm probe-btn" data-run="${run.run}">要一条追问</button>
  </div>`;
}

export function bindProbe(batch, root = document) {
  for (const button of root.querySelectorAll(".probe-btn")) {
    button.onclick = async () => {
      button.disabled = true;
      button.textContent = "问一次…";
      try {
        const result = await post("/api/probe", { batch: batch.id, run: button.dataset.run });
        if (!result.available) {
          toast(`这次没有 AI 的追问：${result.reason}`);
          button.disabled = false;
          button.textContent = "要一条追问";
          return;
        }
        await refresh();
      } catch (error) {
        toast(error.message, true);
        button.disabled = false;
        button.textContent = "要一条追问";
      }
    };
  }
}
