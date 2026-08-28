/* 论文：草稿列表与新建。 */

"use strict";

import { $, html } from "../lib/dom.js";
import { post, submitting, toast } from "../lib/api.js";
import { dateLabel } from "../lib/fmt.js";
import { refresh, store } from "../lib/store.js";

function draftLine(draft) {
  const written = (draft.sections || []).filter((section) => section.text.trim()).length;
  const materials = (draft.sections || []).reduce(
    (sum, section) => sum + section.materials.length,
    0,
  );
  return html`<a class="batch-line" href="#/paper/${encodeURIComponent(draft.id)}">
    <span class="bid">${draft.id}</span>
    <span class="hyp">${draft.title} <em>${draft.venue || "未定目标期刊或会议"}</em></span>
    <span class="tally"
      >${written}/${store.state.sections.length} 节 · ${materials} 处引用 · ${dateLabel(draft.opened_ts)}</span
    >
  </a>`;
}

export function renderPaper() {
  const drafts = store.state.drafts;
  const ready = store.state.batches.some((batch) => batch.closed) || store.state.beliefs.length;

  $("#paper-body").innerHTML = html`
    ${drafts.length
      ? html`<div class="rule-head"><h2>草稿（${drafts.length}）</h2></div>
          ${drafts.map(draftLine)}`
      : html`<div class="blank">
          <h3>${ready ? "实验已收口，材料已备好。" : "还没有可引用的材料。"}</h3>
          <p>
            ${ready
              ? "批次的结论、意外的复盘与信念账本，就是 discussion 最原始的材料。开一份草稿，边写边引。"
              : "先跑一批实验并收口。过程里写下的每一句结论，之后都能在这里直接引用。"}
          </p>
        </div>`}

    <form id="draft-form" class="block">
      <h3>开一份新草稿</h3>
      <p>批次结论与信念账本会作为素材待引用——写作即整理。</p>
      <div class="field">
        <label for="d-title">论文标题<span class="hint">（工作标题即可）</span></label>
        <input id="d-title" placeholder="例如：小数据集上模型容量与数据增强的交互" required />
      </div>
      <div class="field">
        <label for="d-venue">目标期刊或会议<span class="hint">（可留空）</span></label>
        <input id="d-venue" placeholder="例如：NeurIPS / TMLR" />
      </div>
      <div class="err" hidden></div>
      <div class="acts left"><button type="submit" class="btn">创建草稿</button></div>
    </form>
  `;

  const form = $("#draft-form");
  form.onsubmit = async (event) => {
    event.preventDefault();
    let created = null;
    const ok = await submitting(form, async () => {
      created = await post("/api/drafts", {
        title: $("#d-title").value,
        venue: $("#d-venue").value,
      });
      toast(`草稿 ${created.draft} 已创建`);
    });
    if (!ok) return;
    await refresh();
    location.hash = `#/paper/${encodeURIComponent(created.draft)}`;
  };
}
