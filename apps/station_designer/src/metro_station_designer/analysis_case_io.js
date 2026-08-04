import { fetchJson } from "./api.js?v=debug-log-1";

export function downloadAnalysisCase(analysisCase, filename = "analysis-case.json") {
  const body = `${JSON.stringify(analysisCase, null, 2)}\n`;
  downloadBlob(new Blob([body], { type: "application/json;charset=utf-8" }), filename);
}

export async function importAnalysisCase(file) {
  const source = await file.text();
  let analysisCase;
  try {
    analysisCase = JSON.parse(source);
  } catch (exc) {
    throw new Error(`案例 JSON 无法解析：${exc.message}`);
  }
  const result = await fetchJson("/api/analysis-cases/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case: analysisCase }),
  });
  return result.case;
}

export async function importExperimentPlan(file) {
  const plan = await parseJsonFile(file, "实验计划");
  const result = await fetchJson("/api/experiment-plans/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
  return result.plan;
}

export function downloadComparisonBundle(jobId) {
  const link = document.createElement("a");
  link.href = `/api/comparisons/jobs/${encodeURIComponent(jobId)}/export`;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function parseJsonFile(file, label) {
  try {
    return JSON.parse(await file.text());
  } catch (exc) {
    throw new Error(`${label} JSON 无法解析：${exc.message}`);
  }
}
