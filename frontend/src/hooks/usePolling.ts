import { useEffect, useRef } from "react";

/**
 * Calls `callback` every `intervalMs` while the tab is visible.
 * Hidden tabs stop polling (no wasted requests/re-renders) and refresh immediately when shown again.
 */
export function usePolling(callback: () => void, intervalMs: number, enabled = true): void {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    if (!enabled) return undefined;
    let timer: number | undefined;
    const start = () => {
      if (timer === undefined) timer = window.setInterval(() => saved.current(), intervalMs);
    };
    const stop = () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
        timer = undefined;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        saved.current();
        start();
      }
    };
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, enabled]);
}
