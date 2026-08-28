/* DOM 与 HTML 拼装的最小工具。这里只放没有领域知识的东西。 */

"use strict";

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const esc = (value = "") =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

/**
 * 默认转义的模板串。`html`${untrusted}`` 是安全的。
 *
 * 返回的是带 toString 的标记对象，不是裸字符串：这样嵌套的
 * html`` 结果在外层插值时才不会被二次转义，而 `.innerHTML = html``` 与
 * `[...].join("")` 又都能通过 toString 正常取到文本。
 */
export function html(strings, ...values) {
  return raw(
    strings.reduce((out, chunk, index) => {
      if (index === 0) return chunk;
      return out + render(values[index - 1]) + chunk;
    }, ""),
  );
}

const RAW = Symbol("raw");

/** 显式标注「这段已经是 HTML，不要再转义」。让这个判断在调用处可见。 */
export function raw(value) {
  const text = String(value ?? "");
  return { [RAW]: text, toString: () => text };
}

function render(value) {
  if (value === null || value === undefined || value === false) return "";
  if (Array.isArray(value)) return value.map(render).join("");
  if (typeof value === "object" && RAW in value) return value[RAW];
  return esc(value);
}

/** 把已经是 HTML 的片段列表拼成一段 raw，供 html`` 插值。 */
export const join = (parts) => raw(parts.join(""));
