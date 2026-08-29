/* 草稿详情：分节写作，素材可引用。

   未保存保护有两层：localStorage 暂存（刷新/崩溃）+ 离开前确认（切页面）。
   两层都要，因为它们防的是不同的事故。
*/

"use strict";

import { $, $$, html, raw } from "../lib/dom.js";
import { post, submitting, toast } from "../lib/api.js";
import { dateLabel } from "../lib/fmt.js";
import { refresh, store } from "../lib/store.js";

const STASH = (draftId, section) => `ariadne-stash:${draftId}:${section}`;

const DRAFT_STATUS = [
  ["writing", "撰写中"],
  ["submitted", "已投稿"],
  ["published", "已发表"],
];

function materialKey(material) {
  if (material.survey) return `survey:${material.survey}`;
  if (material.batch) return `batch:${material.batch}`;
  if (material.belief) return `belief:${material.belief}`;
  if (material.idea) return `idea:${material.idea}`;
  return "unknown";
}

function materialLabel(material) {
  if (material.survey) {
    const survey = store.state.surveys.find((item) => item.id === material.survey);
    return `调研 ${material.survey}：${survey ? survey.topic : "（已不存在）"}`;
  }
  if (material.batch) {
    const batch = store.state.batches.find((item) => item.id === material.batch);
    return `批次 ${material.batch}：${batch ? batch.hypothesis : "（已不存在）"}`;
  }
  if (material.belief) {
    const belief = store.state.beliefs.find((item) => item.id === material.belief);
    return `信念 ${material.belief}：${belief ? belief.text : "（已不存在）"}`;
  }
  if (material.idea) {
    const idea = store.state.ideas.find((item) => item.id === material.idea);
    return `想法 ${material.idea}：${idea ? idea.text : "（已不存在）"}`;
  }
  return "未知素材";
}

function pickerHtml(section) {
  const chosen = new Set((section?.materials || []).map(materialKey));
  const group = (label, rows, blank) =>
    html`<div>
      <h5>${label}</h5>
      ${rows.length ? rows : html`<p class="seeds">${blank}</p>`}
    </div>`;
  const option = (key, id, text) =>
    html`<label class="pick"
      ><input type="checkbox" value="${key}" ${chosen.has(key) ? raw("checked") : ""} /><span
        ><b>${id}</b> ${text.length > 42 ? `${text.slice(0, 42)}…` : text}</span
      ></label
    >`;

  return html`<div class="picker">
    ${group(
      "领域调研",
      store.state.surveys.map((survey) => option(`survey:${survey.id}`, survey.id, survey.topic)),
      "还没有调研",
    )}
    ${group(
      "实验批次",
      store.state.batches.map((batch) => option(`batch:${batch.id}`, batch.id, batch.hypothesis)),
      "还没有批次",
    )}
    ${group(
      "信念",
      store.state.beliefs.map((belief) => option(`belief:${belief.id}`, belief.id, belief.text)),
      "还没有信念",
    )}
    ${group(
      "想法",
      store.state.ideas
        .filter((idea) => !idea.discarded)
        .map((idea) => option(`idea:${idea.id}`, idea.id, idea.text)),
      "还没有想法",
    )}
  </div>`;
}

function sectionHtml(draft, name, label) {
  const section = draft.sections.find((item) => item.name === name);
  const saved = section?.saved_ts ? `上次保存 ${dateLabel(section.saved_ts)}` : "还没写过";
  const materials = section?.materials || [];
  return html`<form class="sec" data-section="${name}">
    <div class="block-head">
      <div>
        <h3>${label}<span class="flag" hidden>未保存</span></h3>
        <p>${saved}</p>
      </div>
    </div>
    <div class="field">
      <textarea class="body prose" rows="${name === "abstract" ? 5 : 9}" placeholder="${label}……">${section?.text || ""}</textarea>
    </div>
    <details>
      <summary>素材引用（${materials.length}）</summary>
      ${materials.length
        ? html`<ul class="refs">${materials.map((material) => html`<li>${materialLabel(material)}</li>`)}</ul>`
        : ""}
      ${pickerHtml(section)}
    </details>
    <div class="acts left"><button type="submit" class="btn sm">保存这一节</button></div>
    <div class="err" hidden></div>
  </form>`;
}

export function renderDraft() {
  const draft = store.state.drafts.find((item) => item.id === store.route.draft);
  const body = $("#draft-body");

  if (!draft) {
    body.innerHTML = html`<a class="crumb" href="#/paper">← 论文</a>
      <div class="blank"><h3>找不到这份草稿。</h3><p>它可能属于另一个研究目录。</p></div>`;
    return;
  }

  const written = draft.sections.filter((section) => section.text.trim()).length;

  body.innerHTML = html`
    <a class="crumb" href="#/paper">← 论文</a>
    <div class="batch-doc">
      <p class="no">
        <span>草稿 ${draft.id} · ${written}/${store.state.sections.length} 节已动笔</span>
        <span class="when">${dateLabel(draft.opened_ts)}</span>
      </p>
      <h2>${draft.title}</h2>
      <p class="dir">${draft.venue || "未定目标期刊或会议"}</p>
    </div>
    <p class="tally-line">
      <select id="d-status" class="inline-w">
        ${DRAFT_STATUS.map(
          ([value, label]) =>
            html`<option value="${value}" ${draft.status === label ? raw("selected") : ""}>${label}</option>`,
        )}
      </select>
      <button type="button" class="btn ghost sm" id="d-export">导出 Markdown</button>
    </p>
    <div id="sections">${store.state.sections.map(({ name, label }) => sectionHtml(draft, name, label))}</div>
  `;

  bindDraft(draft);
  restoreStash(draft.id);
}

function bindDraft(draft) {
  $("#d-status").onchange = async (event) => {
    try {
      await post("/api/drafts/status", { draft: draft.id, status: event.target.value });
      toast("草稿状态已更新");
    } catch (error) {
      toast(error.message, true);
    }
    await refresh();
  };

  $("#d-export").onclick = async () => {
    try {
      const result = await post("/api/drafts/export", { draft: draft.id });
      const url = URL.createObjectURL(new Blob([result.markdown], { type: "text/markdown;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${draft.id}-${draft.title.slice(0, 24)}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast(error.message, true);
    }
  };

  for (const form of $$("#sections .sec")) {
    $(".body", form).addEventListener("input", () => markDirty(form, true));

    form.onsubmit = async (event) => {
      event.preventDefault();
      const materials = $$(".pick input:checked", form).map((input) => {
        const [kind, id] = input.value.split(":");
        return { [kind]: id };
      });
      const ok = await submitting(form, async () => {
        await post("/api/drafts/section", {
          draft: draft.id,
          section: form.dataset.section,
          text: $(".body", form).value,
          materials,
        });
        markDirty(form, false);
        toast("这一节已保存");
      });
      if (ok) await refresh();
    };
  }
}

function markDirty(form, dirty) {
  form.classList.toggle("dirty", dirty);
  const flag = $(".flag", form);
  if (flag) flag.hidden = !dirty;
  const section = form.dataset.section;
  if (dirty) store.dirty.add(section);
  else store.dirty.delete(section);

  const draftId = store.route.draft;
  if (!draftId) return;
  try {
    if (dirty) localStorage.setItem(STASH(draftId, section), $(".body", form).value);
    else localStorage.removeItem(STASH(draftId, section));
  } catch {
    /* 隐私模式等场景下暂存不可用，静默降级——离开前的确认仍然生效。 */
  }
}

function restoreStash(draftId) {
  for (const form of $$("#sections .sec")) {
    let text = null;
    try {
      text = localStorage.getItem(STASH(draftId, form.dataset.section));
    } catch {
      text = null;
    }
    if (text === null) continue;
    $(".body", form).value = text;
    markDirty(form, true);
  }
}

/** 刷新数据会重渲染整页；先把没保存的文字抠出来，渲染完再放回去。 */
export function captureDirty() {
  if (!store.dirty.size) return null;
  const forms = $$("#sections .sec");
  if (!forms.length) return null;
  const sections = {};
  for (const form of forms) {
    if (store.dirty.has(form.dataset.section)) sections[form.dataset.section] = $(".body", form).value;
  }
  return { draft: store.route.draft, sections };
}

export function restoreDirty(snapshot) {
  if (!snapshot || store.route.view !== "draft" || store.route.draft !== snapshot.draft) return;
  for (const form of $$("#sections .sec")) {
    const text = snapshot.sections[form.dataset.section];
    if (text === undefined) continue;
    $(".body", form).value = text;
    markDirty(form, true);
  }
}
