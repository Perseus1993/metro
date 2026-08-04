import { useCallback } from "react";

export const useAlgorithmActions = (algorithms, setBusy, setError) => {
  const execute = useCallback(async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [setBusy, setError]);

  const preflightAlgorithms = useCallback(
    () => execute(algorithms.preflightSelections),
    [algorithms.preflightSelections, execute],
  );
  const registerAlgorithm = useCallback(
    () => execute(algorithms.register),
    [algorithms.register, execute],
  );
  return { preflightAlgorithms, registerAlgorithm };
};
