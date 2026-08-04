import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJson } from "./api.js?v=debug-log-1";

export const useComparisonJob = (setBusy, setError) => {
  const [job, setJob] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const pollJob = useCallback((jobId) => {
    const poll = async () => {
      try {
        const result = await fetchJson(`/api/comparisons/jobs/${encodeURIComponent(jobId)}`);
        setJob(result);
        if (["queued", "running"].includes(result.status)) {
          timerRef.current = window.setTimeout(poll, 500);
          return;
        }
        setBusy(false);
      } catch (exc) {
        setError(String(exc));
        setBusy(false);
      }
    };
    poll();
  }, [setBusy, setError]);

  return { job, pollJob, setJob };
};
