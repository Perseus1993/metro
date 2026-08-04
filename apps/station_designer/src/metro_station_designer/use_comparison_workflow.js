import { useCallback, useState } from "react";
import {
  downloadAnalysisCase,
  downloadComparisonBundle,
  importAnalysisCase,
  importExperimentPlan,
} from "./analysis_case_io.js?v=analysis-case-1";
import { useControlPlanEditor } from "./use_control_plan_editor.js?v=control-plan-1";
import {
  DEFAULT_CONTROLS,
  algorithmTemplateControls,
  caseRequest,
  controlsFromCase,
  post,
} from "./comparison_workflow_controls.js?v=algorithm-experiment-1";
import { useComparisonJob } from "./use_comparison_job.js?v=algorithm-experiment-1";
import { useAlgorithmActions } from "./use_algorithm_actions.js?v=algorithm-experiment-1";
import { useRoutingAlgorithms } from "./use_routing_algorithms.js?v=algorithm-experiment-1";

export function useComparisonWorkflow(analysisDraft, controlCatalog) {
  const [baseline, setBaseline] = useState(null);
  const [candidate, setCandidate] = useState(null);
  const [differences, setDifferences] = useState([]);
  const [controls, setControls] = useState(DEFAULT_CONTROLS);
  const [decision, setDecision] = useState({
    recommendation: "more_evidence",
    rationale: "需要结合更多种子和现场证据再决策。",
    analyst: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [comparisonMode, setComparisonMode] = useState("case");
  const controlPlan = useControlPlanEditor(controlCatalog, controls);
  const algorithms = useRoutingAlgorithms();
  const { job, pollJob, setJob } = useComparisonJob(setBusy, setError);
  const { preflightAlgorithms, registerAlgorithm } = useAlgorithmActions(
    algorithms, setBusy, setError,
  );

  const saveBaseline = useCallback(async () => {
    if (!controlPlan.validation.valid) {
      setError(controlPlan.validation.errors[0] || "管控时间轴校验失败");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await post(
        "/api/analysis-cases/baseline",
        caseRequest(analysisDraft, controls, controlPlan.serializedPlan),
      );
      setBaseline(result.case);
      setCandidate(null);
      setDifferences([]);
      setJob(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [analysisDraft, controlPlan.serializedPlan, controlPlan.validation, controls]);

  const loadBaseline = useCallback(async (file) => {
    setBusy(true);
    setError("");
    try {
      const imported = await importAnalysisCase(file);
      setBaseline(imported);
      setCandidate(null);
      setDifferences([]);
      setJob(null);
      setControls(controlsFromCase(imported));
      controlPlan.loadFromCase(imported);
      setComparisonMode(imported.simulation?.scenario_mode === "evacuation" ? "algorithm" : "case");
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [controlPlan.loadFromCase]);

  const saveCandidate = useCallback(async () => {
    if (!baseline) return;
    setBusy(true);
    setError("");
    try {
      const result = await post("/api/analysis-cases/candidate", {
        ...analysisDraft,
        baseline,
        case_name: "Candidate",
      });
      setCandidate(result.case);
      setDifferences(result.differences || []);
      setJob(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [analysisDraft, baseline]);

  const runComparison = useCallback(async () => {
    if (!baseline || (comparisonMode === "case" && !candidate)) return;
    setBusy(true);
    setError("");
    try {
      const body = comparisonMode === "algorithm"
        ? {
            comparison_axis: "evacuation_routing",
            template_id: "evacuation-routing-comparison",
            analysis_case: baseline,
            algorithms: await algorithms.preflightSelections(),
          }
        : { baseline, candidate };
      const result = await post("/api/comparisons", body);
      setJob(result);
      pollJob(result.job_id);
    } catch (exc) {
      setError(String(exc));
      setBusy(false);
    }
  }, [algorithms.preflightSelections, baseline, candidate, comparisonMode, pollJob]);

  const loadAlgorithmTemplate = useCallback(() => {
    setComparisonMode("algorithm");
    setControls(algorithmTemplateControls());
    setBaseline(null);
    setCandidate(null);
    setDifferences([]);
    setJob(null);
    setError("");
  }, []);

  const loadExperimentPlan = useCallback(async (file) => {
    setBusy(true);
    setError("");
    try {
      const plan = await importExperimentPlan(file);
      setComparisonMode("algorithm");
      setBaseline(plan.analysis_case);
      setCandidate(null);
      setDifferences([]);
      setJob(null);
      setControls(controlsFromCase(plan.analysis_case));
      controlPlan.loadFromCase(plan.analysis_case);
      algorithms.loadSelections(plan.algorithms);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [algorithms.loadSelections, controlPlan.loadFromCase, setJob]);

  const saveDecision = useCallback(async () => {
    if (!job?.job_id || !job?.report) return;
    setBusy(true);
    setError("");
    try {
      const result = await post(`/api/comparisons/jobs/${job.job_id}/decision`, decision);
      setJob(result);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [decision, job]);

  return {
    baseline,
    algorithms,
    busy,
    candidate,
    controls,
    comparisonMode,
    controlPlan,
    decision,
    differences,
    error,
    job,
    exportBaseline: () => baseline && downloadAnalysisCase(baseline, "baseline.analysis-case.json"),
    exportReport: () => job?.job_id && downloadComparisonBundle(job.job_id),
    loadBaseline,
    loadAlgorithmTemplate,
    loadExperimentPlan,
    preflightAlgorithms,
    registerAlgorithm,
    runComparison,
    saveBaseline,
    saveCandidate,
    saveDecision,
    setControls,
    setDecision,
  };
}
