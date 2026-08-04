import { useCallback, useEffect, useState } from "react";

import { fetchJson } from "./api.js?v=debug-log-1";

const EMPTY_PARAMETERS = { baseline: "{}", candidate: "{}" };

export const useRoutingAlgorithms = () => {
  const [catalog, setCatalog] = useState([]);
  const [selections, setSelections] = useState({ baseline: "", candidate: "" });
  const [parameterText, setParameterText] = useState(EMPTY_PARAMETERS);
  const [manifestPath, setManifestPath] = useState("");
  const [preflight, setPreflight] = useState({ compatible: false, message: "尚未预检" });
  const [error, setError] = useState("");

  const loadCatalog = useCallback(async () => {
    const payload = await fetchJson("/api/routing-algorithms");
    const algorithms = payload.algorithms || [];
    setCatalog(algorithms);
    setSelections((current) => ({
      baseline: current.baseline || algorithms[0]?.registration_id || "",
      candidate: current.candidate || algorithms[1]?.registration_id || "",
    }));
  }, []);

  useEffect(() => {
    loadCatalog().catch((exc) => setError(String(exc)));
  }, [loadCatalog]);

  const selectionPayload = useCallback((role) => {
    let parameters;
    try {
      parameters = JSON.parse(parameterText[role] || "{}");
    } catch (exc) {
      throw new Error(`${role} 参数不是合法 JSON：${exc}`);
    }
    if (!parameters || Array.isArray(parameters) || typeof parameters !== "object") {
      throw new Error(`${role} 参数必须是 JSON 对象`);
    }
    return { registration_id: selections[role], parameters };
  }, [parameterText, selections]);

  const preflightSelections = useCallback(async () => {
    setError("");
    setPreflight({ compatible: false, message: "正在预检" });
    try {
      const payloads = [selectionPayload("baseline"), selectionPayload("candidate")];
      if (payloads[0].registration_id === payloads[1].registration_id) {
        throw new Error("请选择两个不同版本的算法");
      }
      const results = await Promise.all(payloads.map((payload) => post(
        "/api/routing-algorithms/preflight", payload,
      )));
      setPreflight({ compatible: true, message: "2/2 算法兼容，参数有效" });
      return results.map((result) => result.selection);
    } catch (exc) {
      setError(String(exc));
      setPreflight({ compatible: false, message: "预检失败，未启动仿真" });
      throw exc;
    }
  }, [selectionPayload]);

  const register = useCallback(async () => {
    setError("");
    await post("/api/routing-algorithms/register", { manifest_path: manifestPath });
    await loadCatalog();
    setManifestPath("");
    setPreflight({ compatible: false, message: "已注册，请重新预检" });
  }, [loadCatalog, manifestPath]);

  const loadSelections = useCallback((items) => {
    if (!Array.isArray(items) || items.length !== 2) {
      throw new Error("实验计划必须包含两个算法");
    }
    setSelections({
      baseline: items[0].registration_id,
      candidate: items[1].registration_id,
    });
    setParameterText({
      baseline: JSON.stringify(items[0].parameters || {}, null, 2),
      candidate: JSON.stringify(items[1].parameters || {}, null, 2),
    });
    setPreflight({ compatible: false, message: "已导入算法配置，请兼容性预检" });
  }, []);

  const updateSelection = (role, value) => {
    setSelections({ ...selections, [role]: value });
    setPreflight({ compatible: false, message: "配置已变化，请重新预检" });
  };
  const updateParameters = (role, value) => {
    setParameterText({ ...parameterText, [role]: value });
    setPreflight({ compatible: false, message: "配置已变化，请重新预检" });
  };

  return {
    catalog,
    error,
    manifestPath,
    loadSelections,
    parameterText,
    preflight,
    preflightSelections,
    register,
    selections,
    setManifestPath,
    updateParameters,
    updateSelection,
  };
};

const post = (url, body) => fetchJson(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
