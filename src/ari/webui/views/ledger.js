/* 账本：想法与信念。

   合并成一页不是为了省一个导航位。这两者在旧代码里共用同一个
   `.belief-grid`、同一套卡片、同一种「一行文本 + 一个 ID + 一个状态」的
   数据形状——它们本来就是同一种台账条目，只是处在管线的两端：
   左边是还没验证的念头，右边是验证之后留下的判断。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { post, submitting, toast } from "../lib/api.js";
import { refresh, store } from "../lib/store.js";

function ideaHtml(idea) {
  const refs = idea.batches.length
    ? html`<span class="refs"
        >${idea.batches.map(
          (id) => html`<a href="#/batch/${encodeURIComponent(id)}">${id}</a>`,
        )}</span
      >`
    : "";
  return html`<div class="entry ${idea.discarded ? "gone" : ""}" data-idea="${idea.id}">
    <span class="eid">${idea.id}</span>
    <span class="txt">
      ${idea.text}
      ${idea.motivation ? html`<small>${idea.motivation}</small>` : ""}
      ${idea.discarded && idea.discard_reason ? html`<small>放弃原因：${idea.discard_reason}</small>` : ""}
      ${refs}
      ${idea.discarded
        ? ""
        : html`<span class="entry-acts">
            <a class="btn sm" href="#/new?idea=${encodeURIComponent(idea.id)}">立项为批次</a>
            <button type="button" class="btn ghost sm drop">放弃</button>
          </span>`}
      <form class="drop-form" hidden>
        <div class="field gap-top">
          <label>为什么放弃？<span class="hint">（可留空，留给以后的自己）</span></label>
          <input class="why" placeholder="例如：文献里已有系统比较" />
        </div>
        <span class="entry-acts">
          <button type="submit" class="btn warn sm">确认放弃</button>
          <button type="button" class="btn ghost sm cancel">再想想</button>
        </span>
        <div class="err" hidden></div>
      </form>
    </span>
    <span class="st">${idea.status}</span>
  </div>`;
}

function beliefHtml(belief) {
  return html`<div class="entry ${belief.refuted ? "gone" : ""}">
    <span class="eid">${belief.id}</span>
    <span class="txt">
      ${belief.text}
      ${belief.batch
        ? html`<span class="refs"
            ><a href="#/batch/${encodeURIComponent(belief.batch)}"
              >${belief.batch}${belief.run ? ` / ${belief.run}` : ""}</a
            ></span
          >`
        : ""}
    </span>
    <span class="st">${belief.status}</span>
  </div>`;
}

export function renderLedger() {
  const { ideas, beliefs } = store.state;
  const live = ideas.filter((idea) => !idea.discarded);
  const dropped = ideas.filter((idea) => idea.discarded);
  const held = beliefs.filter((belief) => !belief.refuted);
  const refuted = beliefs.filter((belief) => belief.refuted);

  $("#ledger-body").innerHTML = html`
    <form id="idea-form" class="block">
      <h3>记下一个想法</h3>
      <p>阅读、讨论、散步时冒出来的念头都值得先留住——不着急判断值不值得做。</p>
      <div class="field">
        <label for="i-text">这个想法是什么？</label>
        <textarea id="i-text" class="prose" rows="2" placeholder="例如：large 模型在小数据集上可能更受益于数据增强" required></textarea>
      </div>
      <div class="field">
        <label for="i-why">为什么值得追？<span class="hint">（可留空）</span></label>
        <input id="i-why" placeholder="例如：容量与正则化的交互还没人系统比较过" />
      </div>
      <div class="err" hidden></div>
      <div class="acts left"><button type="submit" class="btn">记进账本</button></div>
    </form>

    <div class="rule-head"><h2>在追的想法（${live.length}）</h2></div>
    ${live.length ? live.map(ideaHtml) : html`<p class="todo-empty">还没有在追的想法。</p>`}

    ${dropped.length
      ? html`<div class="rule-head"><h2>已放弃（${dropped.length}）</h2></div>
          ${dropped.map(ideaHtml)}`
      : ""}

    <div class="rule-head"><h2>在册的信念（${held.length}）</h2></div>
    ${held.length
      ? held.map(beliefHtml)
      : html`<p class="todo-empty">复盘意外时写下的判断会出现在这里，并随后续实验被加强、动摇或推翻。</p>`}

    ${refuted.length
      ? html`<div class="rule-head"><h2>已推翻（${refuted.length}）</h2></div>
          <p class="seeds pad-y">
            被推翻的信念不删除。一条被证伪的判断，连同证伪它的那次实验，正是 discussion 里最有价值的段落。
          </p>
          ${refuted.map(beliefHtml)}`
      : ""}
  `;

  bindLedger();
}

function bindLedger() {
  const form = $("#idea-form");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const ok = await submitting(form, async () => {
      const result = await post("/api/ideas", {
        text: $("#i-text").value,
        motivation: $("#i-why").value,
      });
      toast(`想法 ${result.idea} 已入账本`);
      $("#i-text").value = "";
      $("#i-why").value = "";
    });
    if (ok) await refresh();
  };

  for (const button of $$("#ledger-body .drop")) {
    button.onclick = () => {
      const entry = button.closest(".entry");
      $(".entry-acts", entry).hidden = true;
      $(".drop-form", entry).hidden = false;
      $(".why", entry).focus();
    };
  }
  for (const button of $$("#ledger-body .cancel")) {
    button.onclick = () => {
      const entry = button.closest(".entry");
      $(".drop-form", entry).hidden = true;
      $(".entry-acts", entry).hidden = false;
    };
  }
  for (const dropForm of $$("#ledger-body .drop-form")) {
    dropForm.onsubmit = async (event) => {
      event.preventDefault();
      const ok = await submitting(dropForm, async () => {
        await post("/api/ideas/discard", {
          idea: dropForm.closest(".entry").dataset.idea,
          reason: $(".why", dropForm).value,
        });
        toast("想法已移入「已放弃」——不是删除，以后还能翻到");
      });
      if (ok) await refresh();
    };
  }
}
