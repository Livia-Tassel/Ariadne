/* 设置：API key 与用户级选项。

   **密钥不进项目目录。** config.toml 与 runs.jsonl 都会进 git——把 key
   写进去就等于把它提交进仓库。所以存在应用数据目录，权限 0600。这也更
   符合事实：key 是你的，不是某个项目的，一次填好所有项目都能用。

   界面永远只拿到掩码，密钥只进不出。
*/

"use strict";

import { $, $$, html } from "../lib/dom.js";
import { api, post, submitting, toast } from "../lib/api.js";

const LABELS = {
  ANTHROPIC_API_KEY: ["Anthropic", "锁定预测后的定性判断、复盘追问、调研摘要"],
  OPENAI_API_KEY: ["OpenAI", "同上，取决于 config.toml 的 [roles] 配了哪家"],
};

export async function renderSettings() {
  let data;
  try {
    data = await api("/api/settings");
  } catch (error) {
    $("#settings-body").innerHTML = html`<div class="note hot">读不到设置：${error.message}</div>`;
    return;
  }

  $("#settings-body").innerHTML = html`
    <div class="rule-head"><h2>API Key</h2><span class="tally">整层可选，不填也能用</span></div>
    <p class="seeds pad-y">
      不配也能用：GUI 与全部非 AI 功能的行为都不变，只是少了 AI 那一段——不报错、不阻断。
      填了之后，锁定预测后的定性判断、复盘追问、调研的检索式与摘要才会出现。
    </p>

    <form id="secret-form" class="inline-form">
      ${data.secrets.map((row) => {
        const [name, use] = LABELS[row.env] || [row.env, ""];
        return html`<div class="field">
          <label for="k-${row.env}">
            ${name}
            <span class="hint">
              ${use}${row.set ? `　·　当前 ${row.masked}` : "　·　未设置"}
            </span>
          </label>
          ${row.from_env
            ? html`<div class="note">
                这个 key 来自环境变量 <b>${row.env}</b>，优先级高于这里填的值——那是 CI 与
                自动化的显式路径。要改就去改环境变量。
              </div>`
            : html`<input
                id="k-${row.env}"
                class="mono"
                type="password"
                data-env="${row.env}"
                autocomplete="off"
                placeholder="${row.set ? "已设置，留空则不改；填「-」清除" : "粘贴 API key"}"
              />`}
        </div>`;
      })}
      <div class="acts left"><button type="submit" class="btn">保存密钥</button></div>
      <div class="err" hidden></div>
    </form>

    <div class="rule-head"><h2>第三方中转</h2><span class="tally">可选，用中转或非官方模型时填</span></div>
    <p class="seeds pad-y">
      一次设置，所有项目生效——不用每个项目改一遍 config.toml。
      这里填写的模型和 Base URL 会覆盖项目配置；清空后才使用项目里的配置或默认值。
    </p>
    <form id="relay-form" class="inline-form">
      <div class="field">
        <label for="s-reason-model">
          推理模型<span class="hint">（格式：provider:model，例如 anthropic:claude-opus-5 或 openai:deepseek-v4-pro）</span>
        </label>
        <input id="s-reason-model" class="mono" value="${data.reason_model || ""}" placeholder="anthropic:claude-opus-5" />
      </div>
      <div class="field">
        <label for="s-anthropic-url">
          Anthropic Base URL<span class="hint">（留空则用官方 API）</span>
        </label>
        <input id="s-anthropic-url" class="mono" value="${data.anthropic_base_url}" placeholder="https://api.anthropic.com" />
      </div>
      <div class="field">
        <label for="s-openai-url">
          OpenAI Base URL<span class="hint">（留空则用官方 API）</span>
        </label>
        <input id="s-openai-url" class="mono" value="${data.openai_base_url}" placeholder="https://api.openai.com/v1" />
      </div>
      <div class="acts left"><button type="submit" class="btn">保存</button></div>
      <div class="err" hidden></div>
    </form>

    <div class="rule-head"><h2>OpenAlex</h2><span class="tally">领域调研的数据源</span></div>
    <form id="mailto-form" class="inline-form">
      <div class="field">
        <label for="s-mailto">
          联系邮箱<span class="hint">（可留空——填了只是进入 OpenAlex 的礼貌池，不填也能用；不需要 API key）</span>
        </label>
        <input id="s-mailto" class="mono" value="${data.openalex_mailto}" placeholder="me@lab.edu" />
      </div>
      <div class="acts left"><button type="submit" class="btn">保存</button></div>
      <div class="err" hidden></div>
    </form>

    <div class="rule-head"><h2>存在哪</h2></div>
    <p class="seeds pad-y">
      <b>${data.store}</b><br />
      不在项目目录里，权限 0600。<code>config.toml</code> 与 <code>runs.jsonl</code> 都会进
      版本库，密钥写进去就等于提交进仓库——所以它们分开放。这也意味着换一个研究目录，
      key 不用重填。
    </p>
  `;

  bindSettings();
}

function bindSettings() {
  const secretForm = $("#secret-form");
  secretForm.onsubmit = async (event) => {
    event.preventDefault();
    const secrets = {};
    for (const input of $$("input[data-env]", secretForm)) {
      const value = input.value.trim();
      if (!value) continue; // 留空 = 不改
      secrets[input.dataset.env] = value === "-" ? "" : value; // 「-」= 清除
    }
    if (!Object.keys(secrets).length) {
      toast("没有改动");
      return;
    }
    const ok = await submitting(secretForm, async () => {
      await post("/api/settings", { secrets });
      toast("密钥已保存");
    });
    if (ok) await renderSettings();
  };

  const relayForm = $("#relay-form");
  relayForm.onsubmit = async (event) => {
    event.preventDefault();
    const ok = await submitting(relayForm, async () => {
      await post("/api/settings", {
        settings: {
          reason_model: $("#s-reason-model").value,
          anthropic_base_url: $("#s-anthropic-url").value,
          openai_base_url: $("#s-openai-url").value,
        },
      });
      toast("已保存");
    });
    if (ok) await renderSettings();
  };

  const mailtoForm = $("#mailto-form");
  mailtoForm.onsubmit = async (event) => {
    event.preventDefault();
    const ok = await submitting(mailtoForm, async () => {
      await post("/api/settings", { settings: { openalex_mailto: $("#s-mailto").value } });
      toast("已保存");
    });
    if (ok) await renderSettings();
  };
}
