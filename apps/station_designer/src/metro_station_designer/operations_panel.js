import React from "react";

import { PassengerAssetPreview } from "./passenger_asset_preview.js?v=ops-config-1";
import { QuaterniusGlbPreview } from "./quaternius_glb_preview.js?v=ops-config-1";

const h = React.createElement;
const integerFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const decimalFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });

export function OperationsPanel({ onOperationChange, operations, schema }) {
  if (!schema?.length) {
    return null;
  }
  return h("section", { className: "section" }, [
    h("h2", { key: "title", className: "section__title" }, "客流与仿真参数"),
    h(PassengerMixPreview, { key: "passengerMix", operations }),
    h(
      "div",
      { key: "groups", className: "operation-groups" },
      schema.map((group) =>
        h("div", { key: group.id, className: "operation-group" }, [
          h("div", { key: "label", className: "operation-group__label" }, group.label),
          h(
            "div",
            { key: "fields", className: "operation-fields" },
            (group.fields || []).map((field) =>
              h(OperationField, {
                key: field.id,
                field,
                onOperationChange,
                value: operations?.[field.id],
              }),
            ),
          ),
        ]),
      ),
    ),
  ]);
}

function PassengerMixPreview({ operations }) {
  const stats = passengerMixStats(operations);
  return h("div", { className: "passenger-config", "aria-label": "乘客配置摘要" }, [
    h("div", { key: "header", className: "passenger-config__header" }, [
      h("strong", { key: "title" }, "乘客配置"),
      h(
        "span",
        { key: "total" },
        `${formatInteger(stats.totalPersons)} 人 / ${formatInteger(stats.totalDots)} 个小人`,
      ),
    ]),
    h(PassengerAssetPreview, { key: "assetPreview", stats }),
    h(QuaterniusGlbPreview, { key: "quaterniusPreview" }),
    h(
      "div",
      { key: "rows", className: "passenger-config__rows" },
      stats.rows.map((row) =>
        h("div", { key: row.id, className: `passenger-config-row passenger-config-row--${row.id}` }, [
          h("div", { key: "label", className: "passenger-config-row__label" }, [
            h("b", { key: "name" }, row.label),
            h("span", { key: "count" }, `${formatInteger(row.persons)} 人`),
          ]),
          h("div", { key: "bar", className: "passenger-config-row__bar" }, [
            h("i", { key: "fill", style: { width: `${Math.round(row.share * 100)}%` } }),
          ]),
          h("div", { key: "meta", className: "passenger-config-row__meta" }, [
            h("span", { key: "share" }, formatPercent(row.share)),
            h("span", { key: "dots" }, `${formatInteger(row.dots)} 小人`),
          ]),
        ]),
      ),
    ),
    h("div", { key: "metrics", className: "passenger-config__metrics" }, [
      h(PassengerConfigMetric, {
        key: "minutes",
        label: "模拟时长",
        value: `${formatNumber(stats.minutes)} min`,
      }),
      h(PassengerConfigMetric, {
        key: "rate",
        label: "平均流量",
        value: `${formatNumber(stats.personsPerMinute)} 人/min`,
      }),
      h(PassengerConfigMetric, {
        key: "group",
        label: "每个小人",
        value: `${formatInteger(stats.groupSize)} 人`,
      }),
    ]),
  ]);
}

function PassengerConfigMetric({ label, value }) {
  return h("div", { className: "passenger-config-metric" }, [
    h("span", { key: "label" }, label),
    h("strong", { key: "value" }, value),
  ]);
}

function OperationField({ field, onOperationChange, value }) {
  return h("label", { className: "operation-field" }, [
    h("span", { key: "label", className: "operation-field__label" }, field.label),
    h("span", { key: "control", className: "operation-field__control" }, [
      h("input", {
        key: "input",
        "data-testid": `operation-${field.id}`,
        className: "operation-field__input",
        type: "number",
        inputMode: field.kind === "integer" ? "numeric" : "decimal",
        min: field.min,
        max: field.max,
        step: field.step,
        value: value ?? field.default ?? "",
        onChange: (event) => onOperationChange(field.id, event.target.value),
      }),
      h("span", { key: "unit", className: "operation-field__unit" }, field.unit),
    ]),
  ]);
}

function passengerMixStats(operations) {
  const minutes = Math.max(1, numericOperation(operations, "minutes", 1));
  const groupSize = Math.max(1, Math.round(numericOperation(operations, "group_size", 1)));
  const entryRate = Math.max(0, numericOperation(operations, "entry_count_hour", 0));
  const exitRate = Math.max(0, numericOperation(operations, "exit_count_hour", 0));
  const transferRate = Math.max(0, numericOperation(operations, "transfer_count_hour", 0));
  const entryPersons = Math.round((entryRate * minutes) / 60);
  const exitPersons = Math.round((exitRate * minutes) / 60);
  const transferPersons = Math.round((transferRate * minutes) / 60);
  const entryDots = Math.max(0, Math.round(entryPersons / groupSize));
  const exitDots = Math.max(0, Math.round(exitPersons / groupSize));
  const transferDots = Math.max(0, Math.round(transferPersons / groupSize));
  const totalPersons = entryPersons + exitPersons + transferPersons;
  const totalDots = entryDots + exitDots + transferDots;
  const rows = [
    {
      id: "entry",
      label: "进站上车",
      persons: entryPersons,
      dots: entryDots,
      share: totalPersons ? entryPersons / totalPersons : 0,
    },
    {
      id: "exit",
      label: "下车出站",
      persons: exitPersons,
      dots: exitDots,
      share: totalPersons ? exitPersons / totalPersons : 0,
    },
    {
      id: "transfer",
      label: "站内换乘",
      persons: transferPersons,
      dots: transferDots,
      share: totalPersons ? transferPersons / totalPersons : 0,
    },
  ];
  return {
    minutes,
    groupSize,
    personsPerMinute: totalPersons / minutes,
    totalPersons,
    totalDots,
    rows,
  };
}

function numericOperation(operations, key, fallback) {
  const value = Number(operations?.[key] ?? fallback);
  return Number.isFinite(value) ? value : fallback;
}

function formatInteger(value) {
  return integerFormatter.format(Math.max(0, Math.round(value)));
}

function formatNumber(value) {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? formatInteger(rounded) : decimalFormatter.format(rounded);
}

function formatPercent(value) {
  return `${Math.round(value * 100)}%`;
}
