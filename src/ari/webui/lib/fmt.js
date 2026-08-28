/* 数值与领域词汇的显示形式。判定的文案只在这里定义一次。 */

"use strict";

export const VERDICT = {
  CONFIRMED: "符合",
  SURPRISE: "意外",
  NOISY: "噪声",
  NO_RESULT: "待录",
  UNVERIFIED: "存疑",
};

export const DIRECTION = { higher_better: "越大越好", lower_better: "越小越好" };
export const COMPARE = { absolute: "绝对", relative: "相对" };
export const CONFIDENCE = { low: "低", medium: "中", high: "高" };

/** 完整性标记的人话。这些是工具最该说清楚的几句话，不能只给英文标识。 */
export const INTEGRITY = {
  result_predates_prediction:
    "结果文件的修改时间早于预测写入时间——这次记录存在「先看结果再写预测」的嫌疑。",
  result_without_prediction:
    "这个 run 有实测值却没有预测，无法判定。补写的预测会被永久标记。",
  prediction_after_result:
    "预测是在结果已经入库之后才写下的。数据保留，但这条记录永远带着这个标记。",
};

export function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number) >= 1000 || (Math.abs(number) > 0 && Math.abs(number) < 0.0001)) {
    return number.toExponential(3);
  }
  return Number(number.toPrecision(5)).toString();
}

/**
 * 小量（偏差、标准差）的写法：两位有效数字，且不用科学计数法。
 * 台账上 `5.774e-4` 没法和上一行的 `0.001` 对齐着读，而读者要的
 * 恰恰是"这一行比那一行大还是小"。
 */
export function fmtSmall(value) {
  const number = Math.abs(Number(value));
  if (!Number.isFinite(number)) return "—";
  if (number === 0) return "0";
  if (number >= 1) return Number(number.toPrecision(4)).toString();
  const digits = Math.min(8, Math.max(2, Math.ceil(-Math.log10(number)) + 1));
  return number.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}

/** 偏差带正负号：方向本身是信息，"低了 0.051" 和 "高了 0.051" 是两件事。 */
export function fmtDeviation(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  const sign = number > 0 ? "+" : number < 0 ? "−" : "±";
  return sign + fmtSmall(number);
}

/**
 * 一列数字用同一个小数位。
 *
 * 台账的规矩是列要对得齐：`0.712` 和 `0.74633` 并排放，眼睛没法直接比
 * 大小，得先数小数点后有几位。小数位由该指标的容差决定——容差是这个
 * 实验能分辨的最小差异，比它更细的位数是噪声，没有展示价值。
 */
export function decimalsFor(spec) {
  const tolerance = Number(spec?.tolerance);
  if (!Number.isFinite(tolerance) || tolerance <= 0) return 4;
  if (spec?.compare === "relative") return 4;
  return Math.min(8, Math.max(2, Math.ceil(-Math.log10(tolerance)) + 1));
}

export function fmtFixed(value, decimals) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Math.abs(number) >= 1000) return number.toExponential(3);
  return number.toFixed(decimals);
}

export const fmtPredictionAt = (value, decimals) =>
  Array.isArray(value)
    ? `${fmtFixed(value[0], decimals)} ~ ${fmtFixed(value[1], decimals)}`
    : fmtFixed(value, decimals);

export function fmtActualAt(agg, decimals) {
  if (!agg) return "—";
  const spread = agg.sd === null || agg.sd === undefined ? "" : ` ± ${fmtSmall(agg.sd)}`;
  return `${fmtFixed(agg.mean, decimals)}${spread}`;
}

export const fmtPrediction = (value) =>
  Array.isArray(value) ? `${fmt(value[0])} ~ ${fmt(value[1])}` : fmt(value);

export function fmtActual(agg) {
  if (!agg) return "—";
  const spread = agg.sd === null || agg.sd === undefined ? "" : ` ± ${fmtSmall(agg.sd)}`;
  return `${fmt(agg.mean)}${spread}`;
}

export function dateLabel(ts) {
  if (!ts) return "";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function runSeeds(run) {
  const seeds = new Set();
  for (const samples of Object.values(run.samples || {})) {
    for (const seed of Object.keys(samples)) seeds.add(Number(seed));
  }
  return [...seeds].sort((a, b) => a - b);
}

export function nextSeed(run) {
  const seeds = runSeeds(run);
  return seeds.length ? Math.max(...seeds) + 1 : 0;
}

/** run 在这个批次里第一个指标上的偏差，用于清单行的一句话概括。 */
export function leadMetric(run) {
  const names = Object.keys(run.prediction?.metrics || {});
  return names[0] || Object.keys(run.aggregates || {})[0] || "";
}
