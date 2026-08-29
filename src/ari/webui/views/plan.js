/* 新批次。

   旧版第一屏就是 24 个输入框（方向+假设+维度名/值+指标名/方向/比较/容差
   +N×M 个预测格+每行置信度+每行理由），全在跑任何实验之前。第一次用的人
   在这里就走了。

   这一版把设计压成三样：假设、变量、指标。变量用一行紧凑语法，指标只要
   名字（方向与容差从名字推断，可改但不必填）。
*/

"use strict";

import { $, html } from "../lib/dom.js";
import { post, showError, submitting, toast } from "../lib/api.js";
import { refresh, store } from "../lib/store.js";

/** 指标名 → [方向, 比较方式, 容差]。让最常见的几种指标不必填这三项。 */
export function guessMetric(name) {
  const lower = name.toLowerCase();
  if (/acc|f1|auc|bleu|rouge/.test(lower)) return ["higher_better", "absolute", 0.005];
  if (/err|wer|cer/.test(lower)) return ["lower_better", "absolute", 0.005];
  if (/loss|ppl|perplexity|fid/.test(lower)) return ["lower_better", "relative", 0.1];
  return ["higher_better", "relative", 0.1];
}

/**
 * `model=base,large; aug=none,strong` → [{name, values}]
 * 分号或换行都可以分隔。写错了就地报错并保留原文，不清空。
 */
export function parseDimensions(text) {
  const dimensions = [];
  for (const chunk of text.split(/[;\n]/)) {
    const line = chunk.trim();
    if (!line) continue;
    const at = line.indexOf("=");
    if (at < 1) throw new Error(`变量「${line}」缺少 =，写成 model=base,large 这样`);
    const name = line.slice(0, at).trim();
    const values = line
      .slice(at + 1)
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    if (!values.length) throw new Error(`变量 ${name} 还没有取值`);
    dimensions.push({ name, values });
  }
  if (!dimensions.length) throw new Error("至少声明一个变量维度");
  return dimensions;
}

export function parseMetrics(text) {
  const metrics = text
    .split(/[,;\n]/)
    .map((name) => name.trim())
    .filter(Boolean)
    .map((name) => {
      const [direction, compare, tolerance] = guessMetric(name);
      return { name, direction, compare, tolerance };
    });
  if (!metrics.length) throw new Error("至少填写一个指标名");
  return metrics;
}

export function renderPlan() {
  const ideaId = store.route.params?.get("idea") || "";
  const idea = ideaId ? store.state.ideas.find((item) => item.id === ideaId) : null;
  if (idea) store.plan.idea = idea.id;

  $("#new-body").innerHTML = html`
    <a class="crumb" href="#/batches">← 批次</a>
    <h1 class="page">新批次</h1>
    <p class="page-sub">在开跑之前，先写下你对结果的判断。</p>

    <p class="steps">
      <span class="on" id="step-1">1 设计</span><i>——</i><span id="step-2">2 锁定预测</span>
    </p>

    <form id="plan-form">
      ${idea
        ? html`<div class="note">起于想法 <b>${idea.id}</b>：${idea.text}</div>`
        : ""}

      <div class="block">
        <h3>研究问题</h3>
        <p>写给三个月后的自己：方向提供上下文，假设必须能被这一批实验检验。</p>
        <div class="field">
          <label for="p-dir">研究方向</label>
          <input id="p-dir" placeholder="例如：小数据集上的视觉模型正则化" required />
        </div>
        <div class="field">
          <label for="p-hyp">这一轮的假设</label>
          <textarea id="p-hyp" class="prose" rows="3" required
            placeholder="例如：在同等训练预算下，更强的数据增强会改善 large 模型的泛化，但对 base 收益有限。">${idea ? idea.text : ""}</textarea>
        </div>
      </div>

      <div class="block">
        <h3>变量与指标</h3>
        <p>变量用一行写完，系统会生成全部组合。指标只要名字——方向与容差从名字推断，可改。</p>
        <div class="field">
          <label for="p-dims">变量维度</label>
          <input id="p-dims" class="mono" value="model=base,large" placeholder="model=base,large; aug=none,light,strong" />
        </div>
        <div class="field">
          <label for="p-metrics">观测指标<span class="hint">（逗号分隔）</span></label>
          <input id="p-metrics" class="mono" value="top1_acc" placeholder="top1_acc, val_loss" />
        </div>
        <div class="field">
          <label for="p-path">
            结果文件路径模板<span class="hint">（可留空，但填了才有「先看结果再补预测」的检查）</span>
          </label>
          <input id="p-path" class="mono" placeholder="logs/{model}/s{seed}/results.json" />
        </div>
      </div>

      <div class="err" id="plan-err" hidden></div>
      <div class="acts">
        <button type="button" class="btn ghost" id="open-bare">先开批次，预测稍后锁</button>
        <button type="button" class="btn" id="to-predictions">现在就填预测表 →</button>
      </div>

      <div id="predict-block" hidden>
        <div class="block">
          <h3>锁定你的预测</h3>
          <p>
            可以是点值（0.83）或区间（0.80 ~ 0.84）。理由必填——它决定复盘时能否找到真正出错的那个假设。
            保存后不会被覆盖：后续修订保留原值。留空的行会跳过，之后在批次页逐个锁也行。
          </p>
          <table class="ledger">
            <thead id="p-head"></thead>
            <tbody id="p-body"></tbody>
          </table>
        </div>
        <div class="acts"><button type="submit" class="btn">锁定预测并开批次</button></div>
      </div>
    </form>
  `;

  bindPlan();
}

function bindPlan() {
  const errorNode = $("#plan-err");

  $("#to-predictions").onclick = async () => {
    errorNode.hidden = true;
    try {
      if (!$("#p-dir").value.trim() || !$("#p-hyp").value.trim()) {
        throw new Error("请先填写研究方向和实验假设");
      }
      const dimensions = parseDimensions($("#p-dims").value);
      const metrics = parseMetrics($("#p-metrics").value);
      const result = await post("/api/runs/preview", { dimensions });
      store.plan.runs = result.runs;
      store.plan.metrics = metrics;
      renderPredictionTable();
      $("#predict-block").hidden = false;
      $("#step-1").className = "done";
      $("#step-2").className = "on";
      $("#predict-block").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showError(errorNode, error);
    }
  };

  // 先开批次、预测稍后锁。约束是逐 run 的，不必在跑任何实验之前填完 N×M 格。
  $("#open-bare").onclick = async () => {
    errorNode.hidden = true;
    try {
      if (!$("#p-dir").value.trim() || !$("#p-hyp").value.trim()) {
        throw new Error("请先填写研究方向和实验假设");
      }
      await submitBatch(parseMetrics($("#p-metrics").value), []);
    } catch (error) {
      showError(errorNode, error);
    }
  };

  async function submitBatch(metrics, predictions) {
    const result = await post("/api/batches", {
      research_direction: $("#p-dir").value,
      hypothesis: $("#p-hyp").value,
      dimensions: parseDimensions($("#p-dims").value),
      metrics,
      result_path: $("#p-path").value,
      predictions,
      idea: store.plan.idea || "",
    });
    toast(
      predictions.length
        ? `批次 ${result.batch} 已开，${predictions.length} 条预测已锁定`
        : `批次 ${result.batch} 已开，${result.run_count} 个 run 待锁预测`,
    );
    store.plan = { runs: [], metrics: [], idea: "" };
    await refresh();
    location.hash = `#/batch/${encodeURIComponent(result.batch)}`;
  }

  $("#plan-form").onsubmit = async (event) => {
    event.preventDefault();
    if (!store.plan.runs.length) return;
    const form = $("#plan-form");
    const predictions = [];
    for (const row of document.querySelectorAll("#p-body tr")) {
      const values = [...row.querySelectorAll(".pv")];
      if (values.every((input) => !input.value.trim())) continue; // 留空 = 之后再锁
      predictions.push({
        run: row.dataset.run,
        metrics: Object.fromEntries(
          values.map((input) => [input.dataset.metric, input.value.trim()]),
        ),
        confidence: row.querySelector(".pc").value,
        rationale: row.querySelector(".pr").value.trim(),
      });
    }

    await submitting(form, () => submitBatch(store.plan.metrics, predictions));
  };
}

function renderPredictionTable() {
  const names = store.plan.metrics.map((metric) => metric.name);
  $("#p-head").innerHTML = html`<tr>
    <th>run</th>
    ${names.map((name) => html`<th>${name} 预测</th>`)}
    <th class="col-conf">置信度</th>
    <th class="col-why">为什么这么预期</th>
  </tr>`;
  $("#p-body").innerHTML = html`${store.plan.runs.map(
    (run) => html`<tr data-run="${run}">
      <td>${run}</td>
      ${names.map(
        (name) => html`<td><input class="pv mono" data-metric="${name}" placeholder="0.83 或 0.80 ~ 0.84" /></td>`,
      )}
      <td>
        <select class="pc">
          <option value="low">低</option>
          <option value="medium" selected>中</option>
          <option value="high">高</option>
        </select>
      </td>
      <td><input class="pr" placeholder="影响这个判断的关键依据" /></td>
    </tr>`,
  )}`;
}
