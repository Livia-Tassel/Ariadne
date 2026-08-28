/* 与本地服务的全部通信，以及给人看的反馈。 */

"use strict";

import { $ } from "./dom.js";

export async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let body;
  try {
    body = await response.json();
  } catch {
    body = { error: "服务返回了无法读取的内容" };
  }
  if (!response.ok) throw new Error(body.error || `请求失败（${response.status}）`);
  return body;
}

export const post = (path, payload) =>
  api(path, { method: "POST", body: JSON.stringify(payload) });

let toastTimer = null;

export function toast(message, bad = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast on${bad ? " bad" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.className = "toast";
  }, 3400);
}

export function showError(node, error) {
  node.textContent = error?.message || String(error);
  node.hidden = false;
}

/**
 * 表单提交的统一外壳：禁用按钮、清错误、出错就地显示。
 * 每个表单各写一遍 try/finally 迟早会漏掉一处 finally，按钮就永久禁用了。
 */
export async function submitting(form, work) {
  const errorNode = form.querySelector(".err");
  const button = form.querySelector("button[type=submit]");
  if (errorNode) errorNode.hidden = true;
  if (button) button.disabled = true;
  try {
    await work();
    return true;
  } catch (error) {
    if (errorNode) showError(errorNode, error);
    else toast(error.message, true);
    return false;
  } finally {
    if (button) button.disabled = false;
  }
}
