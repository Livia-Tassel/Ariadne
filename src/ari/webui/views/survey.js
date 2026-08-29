/* 领域调研。

   两栏之分不是视觉分组，是**注意力分配**：里程碑那几篇你亲自读，长尾由
   AI 摘要、你只扫一眼。这一层真正的风险不是幻觉，是读了 40 篇摘要之后
   记成自己调研过——所以「你的收获」与「AI 摘要」在界面上分得很开，在事件
   类型上更是两回事（paper_read vs note）。

   调研以一句瓶颈陈述结束。不落到那句话上，前面读的全白读。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { post, showError, submitting, toast } from "../lib/api.js";
import { dateLabel } from "../lib/fmt.js";
import { refresh, store } from "../lib/store.js";

const findSurvey = (id) => store.state.surveys.find((s) => s.id === id);

/* 长尾默认只露一小截。四十条全铺开正好和「替你分配注意力」背道而驰——
   已摘要的排在前面（它们有真内容），其余收在展开里。 */
const TAIL_PREVIEW = 8;
let tailOpen = false;

/* ---------- 列表与新建 ---------- */

function surveyLine(survey) {
  const tally = [
    `${survey.milestones.length} 里程碑`,
    `${survey.followups.length} 长尾`,
    survey.closed ? "已收口" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return html`<a class="batch-line ${survey.closed ? "shut" : ""}" href="#/survey/${encodeURIComponent(survey.id)}">
    <span class="bid">${survey.id}</span>
    <span class="hyp">${survey.topic} <em>${survey.query}</em></span>
    <span class="tally"
      >${tally}${survey.unread_milestones ? html`　<b>${survey.unread_milestones} 待精读</b>` : ""}</span
    >
  </a>`;
}

export function renderSurveys() {
  const surveys = store.state.surveys;
  $("#surveys-body").innerHTML = html`
    ${surveys.length
      ? html`<div class="rule-head"><h2>调研（${surveys.length}）</h2></div>
          ${surveys.map(surveyLine)}`
      : html`<div class="blank">
          <h3>还没有调研。</h3>
          <p>
            进一个新领域时，先花十分钟搞清楚它的地基是什么。系统按引用图算出该你亲自读的
            那几篇，其余交给 AI 摘要——你的注意力只够精读十来篇，花在哪几篇上是个可以算的问题。
          </p>
        </div>`}

    <form id="survey-form" class="block">
      <h3>开一个调研</h3>
      <p>给一句话主题。检索式可以让 AI 拟，你改完再存——它会连同结果一起存档，半年后能原样重跑。</p>
      <div class="field">
        <label for="sv-topic">研究主题</label>
        <input id="sv-topic" placeholder="例如：小数据集上的正则化，容量与数据增强的交互" required />
      </div>
      <div class="field">
        <label for="sv-question">想回答的问题<span class="hint">（可留空）</span></label>
        <input id="sv-question" placeholder="例如：强增强到底是在正则化，还是在制造欠拟合？" />
      </div>
      <div class="field">
        <label for="sv-query">OpenAlex 检索式<span class="hint">（英文关键词，三到六个）</span></label>
        <div class="scan-line">
          <input id="sv-query" class="mono" placeholder="data augmentation regularization small dataset" required />
          <button type="button" class="btn ghost sm" id="sv-ai-query">让 AI 拟一个</button>
        </div>
      </div>
      <div class="err" hidden></div>
      <div class="acts left"><button type="submit" class="btn">开调研并抓取</button></div>
    </form>
  `;
  bindSurveyForm();
}

function bindSurveyForm() {
  const form = $("#survey-form");
  if (!form) return;

  $("#sv-ai-query").onclick = async () => {
    const topic = $("#sv-topic").value.trim();
    if (!topic) return showError($(".err", form), new Error("先写下研究主题"));
    const button = $("#sv-ai-query");
    button.disabled = true;
    button.textContent = "想一下…";
    try {
      const result = await post("/api/surveys/query", {
        topic,
        question: $("#sv-question").value,
      });
      if (!result.available) toast(`这次没有 AI 的检索式：${result.reason}`);
      else {
        $("#sv-query").value = result.query;
        toast(result.rationale || "检索式已填入，你可以改");
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "让 AI 拟一个";
    }
  };

  form.onsubmit = async (event) => {
    event.preventDefault();
    let sid = null;
    const ok = await submitting(form, async () => {
      const created = await post("/api/surveys", {
        topic: $("#sv-topic").value,
        question: $("#sv-question").value,
        query: $("#sv-query").value,
      });
      sid = created.survey;
      const run = await post("/api/surveys/run", { survey: sid, k: 40 });
      toast(
        run.available
          ? `抓到 ${run.found} 篇，其中 ${run.milestones} 篇里程碑`
          : `调研已开，但这次没抓到：${run.reason}`,
      );
    });
    if (!ok) return;
    await refresh();
    location.hash = `#/survey/${encodeURIComponent(sid)}`;
  };
}

/* ---------- 详情 ---------- */

function milestoneHtml(survey, paper) {
  return html`<div class="entry paper ${paper.read ? "done" : ""}" data-work="${paper.work}">
    <span class="eid">${paper.in_set} 引用</span>
    <span class="txt">
      <b>${paper.title}</b>
      <small>${paper.year || "年份不详"} · ${paper.venue || "未知来源"} · 总被引 ${paper.cited_by}</small>
      ${paper.read
        ? html`<span class="took">我拿走的：${paper.takeaway}</span>`
        : html`<form class="read-form" data-work="${paper.work}">
            <div class="field gap-top">
              <label>读完了？写一句你从这篇拿走了什么<span class="hint">（必填——不写下来等于没读）</span></label>
              <input class="tk" placeholder="例如：dropout 的等价解释是模型平均，不是噪声注入" />
            </div>
            <span class="entry-acts">
              <button type="submit" class="btn sm">记下收获</button>
              <button type="button" class="btn ghost sm demote" data-work="${paper.work}">移到长尾</button>
              ${paper.doi
                ? html`<a class="link" href="https://doi.org/${paper.doi}" target="_blank" rel="noreferrer">原文</a>`
                : ""}
            </span>
            <div class="err" hidden></div>
          </form>`}
    </span>
    <span class="st">${paper.read ? "已精读" : "待精读"}</span>
  </div>`;
}

function followupHtml(paper) {
  const s = paper.summary;
  return html`<div class="entry paper" data-work="${paper.work}">
    <span class="eid">${paper.year || "—"}</span>
    <span class="txt">
      <b>${paper.title}</b>
      ${s
        ? html`<span class="changed">改了什么：${s.changed}</span>
            <small class="${s.worth_reading ? "worth" : ""}">
              ${s.worth_reading ? "值得精读" : "不必精读"}——${s.why}
            </small>`
        : html`<small>${paper.venue || "未知来源"} · 总被引 ${paper.cited_by} · 还没有摘要</small>`}
      <span class="entry-acts">
        <button type="button" class="btn ghost sm promote" data-work="${paper.work}">提为里程碑</button>
        <button type="button" class="btn ghost sm drop-paper" data-work="${paper.work}">跳过</button>
      </span>
    </span>
    <span class="st">${s ? "已摘要" : "未摘要"}</span>
  </div>`;
}

function tailHtml(survey) {
  if (!survey.followups.length) return html`<p class="todo-empty">长尾是空的。</p>`;
  // 已摘要的排前面：它们有「改了什么」，是真能扫的内容。
  const rows = [...survey.followups].sort((a, b) => Number(!!b.summary) - Number(!!a.summary));
  const shown = tailOpen ? rows : rows.slice(0, TAIL_PREVIEW);
  return html`${shown.map(followupHtml)}
    ${rows.length > TAIL_PREVIEW
      ? html`<button type="button" class="tail-toggle" id="tail-toggle">
          ${tailOpen ? "收起" : `展开其余 ${rows.length - TAIL_PREVIEW} 篇`}
        </button>`
      : ""}`;
}

function bottleneckHtml(survey) {
  const ai = survey.ai_bottleneck;
  return html`<div class="rule-head">
      <h2>瓶颈</h2>
      <span class="tally">${survey.ready_for_bottleneck ? "里程碑都读完了" : "读完里程碑再写"}</span>
    </div>
    ${survey.bottleneck
      ? html`<p class="lede">${survey.bottleneck}</p>
          ${ai
            ? html`<div class="advice">
                <div class="advice-block">
                  <h4>AI 的独立判断${ai.agrees ? "（与你一致）" : "（与你不同）"}</h4>
                  <p class="quote">${ai.bottleneck}</p>
                </div>
                ${ai.unexamined?.length
                  ? html`<div class="advice-block">
                      <h4>这批工作共同没有检验的假设</h4>
                      <ul class="blockers">${ai.unexamined.map((x) => html`<li>${x}</li>`)}</ul>
                    </div>`
                  : ""}
              </div>`
            : html`<div class="scan-line">
                <span class="seeds">你的判断已经落盘，现在可以看一份独立的了。不一致的地方就是信号。</span>
                <button type="button" class="btn sm" id="ask-bottleneck">看 AI 的判断</button>
              </div>`}
          ${survey.closed
            ? ""
            : html`<div class="acts left">
                <button type="button" class="btn" id="to-idea">立为想法</button>
                <button type="button" class="btn ghost" id="close-survey">收口调研</button>
              </div>`}`
      : html`<form id="bn-form" class="inline-form">
          <div class="field">
            <label>读完之后，你认为这个领域现在卡在哪？</label>
            <textarea class="bn prose" rows="3" placeholder="例如：所有工作都把容量和正则一起动，没人分开量过各自的贡献。" required></textarea>
          </div>
          <p class="seeds">写完才能看 AI 的判断——先看会让你的分析失去独立性。</p>
          <div class="acts left"><button type="submit" class="btn">写下瓶颈</button></div>
          <div class="err" hidden></div>
        </form>`}`;
}

export function renderSurvey() {
  const survey = findSurvey(store.route.survey);
  const body = $("#survey-body");

  if (!survey) {
    body.innerHTML = html`<a class="crumb" href="#/surveys">← 调研</a>
      <div class="blank"><h3>找不到这个调研。</h3><p>它可能属于另一个研究目录。</p></div>`;
    return;
  }

  const unsummarized = survey.followups.filter((p) => !p.summary).length;

  body.innerHTML = html`
    <a class="crumb" href="#/surveys">← 调研</a>
    <div class="batch-doc">
      <p class="no">
        <span>调研 ${survey.id} · ${survey.milestones.length + survey.followups.length} 篇 · ${survey.closed ? "已收口" : "进行中"}</span>
        <span class="when">${dateLabel(survey.opened_at)}</span>
      </p>
      <h2>${survey.topic}</h2>
      <p class="dir">${survey.question || ""}</p>
    </div>
    <p class="facts">
      <span>检索式 <b>${survey.query}</b></span>
      <span>来源 <b>OpenAlex</b></span>
      ${survey.budget?.limit
        ? html`<span>额度 <b>${survey.budget.remaining}/${survey.budget.limit}</b></span>`
        : ""}
      ${survey.skipped ? html`<span>已跳过 <b>${survey.skipped}</b></span>` : ""}
    </p>
    ${survey.closed
      ? ""
      : html`<div class="scan-line">
          <span class="seeds">
            再抓一批是「补充」不是「重来」：已经在账本里的论文不会被覆盖，人工改���的分层也保留。
          </span>
          <button type="button" class="btn ghost sm" id="refetch">再抓一批</button>
        </div>`}

    <div class="rule-head">
      <h2>里程碑 —— 这几篇你该亲自读</h2>
      <span class="tally">按「本领域近期工作里有几篇引了它」排序</span>
    </div>
    ${survey.milestones.length
      ? survey.milestones.map((p) => milestoneHtml(survey, p))
      : html`<p class="todo-empty">还没有过线的里程碑。种子集可能太小，或这个主题太新。</p>`}

    <div class="rule-head">
      <h2>长尾（${survey.followups.length}）—— AI 摘要，先不精读</h2>
      ${unsummarized
        ? html`<button type="button" class="btn ghost sm" id="summarize">摘要 ${Math.min(unsummarized, 12)} 篇</button>`
        : html`<span class="tally">都摘要过了</span>`}
    </div>
    ${tailHtml(survey)}

    ${bottleneckHtml(survey)}
  `;

  bindSurvey(survey);
}

function bindSurvey(survey) {
  const act = async (path, payload, message) => {
    try {
      const result = await post(path, { survey: survey.id, ...payload });
      if (result.available === false) toast(`这次没有 AI 那一段：${result.reason}`);
      else if (message) toast(typeof message === "function" ? message(result) : message);
      await refresh();
    } catch (error) {
      toast(error.message, true);
    }
  };

  for (const form of $$("#survey-body .read-form")) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      const ok = await submitting(form, async () => {
        await post("/api/surveys/read", {
          survey: survey.id,
          work: form.dataset.work,
          takeaway: $(".tk", form).value,
        });
        toast("收获已记下");
      });
      if (ok) await refresh();
    };
  }

  for (const b of $$("#survey-body .promote"))
    b.onclick = () => act("/api/surveys/tier", { work: b.dataset.work, tier: "milestone" }, "已提为里程碑");
  for (const b of $$("#survey-body .demote"))
    b.onclick = () => act("/api/surveys/tier", { work: b.dataset.work, tier: "followup" }, "已移到长尾");
  for (const b of $$("#survey-body .drop-paper"))
    b.onclick = () => act("/api/surveys/skip", { work: b.dataset.work }, "已跳过");

  const summarize = $("#summarize");
  if (summarize) {
    summarize.onclick = async () => {
      summarize.disabled = true;
      summarize.textContent = "摘要中…";
      await act("/api/surveys/summarize", {}, (r) =>
        r.summarized ? `已摘要 ${r.summarized} 篇` : `没能摘要：${r.reason}`,
      );
    };
  }

  const bnForm = $("#bn-form");
  if (bnForm) {
    bnForm.onsubmit = async (event) => {
      event.preventDefault();
      const ok = await submitting(bnForm, async () => {
        await post("/api/surveys/bottleneck", { survey: survey.id, text: $(".bn", bnForm).value });
        toast("瓶颈已写下——现在可以看 AI 的判断了");
      });
      if (ok) await refresh();
    };
  }

  const ask = $("#ask-bottleneck");
  if (ask)
    ask.onclick = async () => {
      ask.disabled = true;
      ask.textContent = "问一次…";
      await act("/api/surveys/bottleneck/ai", {});
    };

  const toIdea = $("#to-idea");
  if (toIdea)
    toIdea.onclick = async () => {
      try {
        const result = await post("/api/surveys/idea", { survey: survey.id });
        toast(`想法 ${result.idea} 已入账本`);
        await refresh();
        location.hash = `#/ledger`;
      } catch (error) {
        toast(error.message, true);
      }
    };

  const refetch = $("#refetch");
  if (refetch)
    refetch.onclick = async () => {
      refetch.disabled = true;
      refetch.textContent = "抓取中…";
      await act("/api/surveys/run", { k: 40 }, (r) =>
        r.found ? `补进 ${r.found} 篇` : "没有新的论文——这个检索式已经抓完了",
      );
    };

  const toggle = $("#tail-toggle");
  if (toggle)
    toggle.onclick = () => {
      tailOpen = !tailOpen;
      renderSurvey();
    };

  const close = $("#close-survey");
  if (close) close.onclick = () => act("/api/surveys/close", {}, "调研已收口");
}
