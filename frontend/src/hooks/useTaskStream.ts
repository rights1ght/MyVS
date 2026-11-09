import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { TaskInfo } from "../api/types";

const terminal = new Set(["completed", "failed", "cancelled"]);

export function useTaskStream(taskId: string | null): {
  task: TaskInfo | null;
  error: string | null;
  refresh: () => void;
} {
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | undefined>(undefined);
  const wsRef = useRef<WebSocket | null>(null);
  const doneRef = useRef(false);

  const refresh = () => {
    if (!taskId) return;
    api<TaskInfo>(`/api/tasks/${taskId}`)
      .then((value) => {
        setTask(value);
        if (terminal.has(value.status)) doneRef.current = true;
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      return;
    }
    setError(null);
    doneRef.current = false;
    let disposed = false;

    const startPolling = () => {
      if (pollRef.current) return;
      refresh();
      pollRef.current = window.setInterval(() => {
        if (doneRef.current) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = undefined;
          return;
        }
        refresh();
      }, 1000);
    };

    refresh();
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    try {
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/tasks/${taskId}`);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as TaskInfo & { type?: string };
          if (payload.type === "error") {
            setError((payload as unknown as { message?: string }).message ?? "Задача недоступна");
            startPolling();
            return;
          }
          const next = { ...payload };
          delete (next as { type?: string }).type;
          setTask(next);
          if (terminal.has(next.status)) {
            doneRef.current = true;
            ws.close();
          }
        } catch {
          // ignore malformed frame
        }
      };
      ws.onerror = () => {
        startPolling();
      };
      ws.onclose = () => {
        if (!disposed && !doneRef.current) startPolling();
      };
    } catch {
      startPolling();
    }

    return () => {
      disposed = true;
      wsRef.current?.close();
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = undefined;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  return { task, error, refresh };
}
