import { useEffect } from "react";
import { api } from "../api/client";
import type { Snapshot } from "../api/types";
import { useMonitorStore } from "../store/monitor";

export function useMonitorSocket(): void {
  const setSnapshot = useMonitorStore((state) => state.setSnapshot);
  const setConnected = useMonitorStore((state) => state.setConnected);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let disposed = false;

    api<Snapshot>("/api/monitor/snapshot")
      .then((snapshot) => {
        if (!disposed) setSnapshot(snapshot);
      })
      .catch(() => undefined);

    const connect = () => {
      if (disposed) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${window.location.host}/ws/monitor`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as Snapshot;
          if (payload && typeof payload.seq === "number") setSnapshot(payload);
        } catch {
          // ignore malformed frame
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!disposed) retry = window.setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      disposed = true;
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, [setConnected, setSnapshot]);
}
