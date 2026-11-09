import clsx from "clsx";
import { ListOrdered, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { QueuePayload } from "../api/types";
import { ResourceDecision } from "../components/TaskDecision";
import { TaskTimer } from "../components/TaskPanel";
import { Badge, EmptyState, ErrorBox, PageHeader, Panel } from "../components/ui";

export function QueuePage() {
  const [data, setData] = useState<QueuePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api<QueuePayload>("/api/queue").then(setData).catch((err: Error) => setError(err.message));
  useEffect(() => {
    load();
    const timer = window.setInterval(load, 1000);
    return () => window.clearInterval(timer);
  }, []);
  const tasks = data?.tasks ?? [];
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Scheduler" title="Очередь" description="GPU-задачи по приоритету, CPU-задачи параллельно. Один воркер на модель." actions={<button className="btn" onClick={load}><RefreshCw size={15} /> Обновить</button>} />
      {error && <ErrorBox message={error} onClose={() => setError(null)} />}
      <div className="grid gap-4 sm:grid-cols-3">
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">В очереди</div><div className="mt-1 text-3xl font-semibold tabular-nums">{data?.counts.queued ?? 0}</div></Panel>
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Выполняется</div><div className="mt-1 text-3xl font-semibold tabular-nums text-[var(--accent)]">{data?.counts.running ?? 0}</div></Panel>
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Ждут решения</div><div className="mt-1 text-3xl font-semibold tabular-nums text-amber-500">{data?.counts.awaiting ?? 0}</div></Panel>
      </div>
      {tasks.length === 0 ? <EmptyState icon={<ListOrdered size={24} />} title="Очередь пуста" text="Запустите STT, TTS или тест голоса." /> : (
        <div className="space-y-4">
          {tasks.map((task) => (
            <Panel key={task.id} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2"><Badge tone={task.type === "stt" ? "blue" : "accent"}>{task.type.toUpperCase()}</Badge><span className="text-sm font-medium">{task.model_id || "модель не выбрана"}</span><Badge tone={task.status === "awaiting_decision" ? "accent" : task.status === "running" ? "mint" : "neutral"}>{task.status}</Badge></div>
                  <div className="mt-1 line-clamp-1 max-w-2xl text-xs text-[var(--muted)]">{task.text || task.id}</div>
                </div>
                <div className="flex gap-2">
                  {!["completed", "failed", "cancelled"].includes(task.status) && <button className="btn px-2.5 py-1.5 text-xs" onClick={() => api(`/api/tasks/${task.id}/cancel`, { method: "POST" }).then(load).catch((err) => setError((err as Error).message))}><XCircle size={13} /> {task.status === "running" ? "Остановить" : "Отменить"}</button>}
                  <Link to={`/history?task=${task.id}`} className="btn px-2.5 py-1.5 text-xs">Детали</Link>
                </div>
              </div>
              <div className="mt-3"><TaskTimer task={task} /></div>
              {task.status === "awaiting_decision" && <div className="mt-3"><ResourceDecision task={task} onResolved={load} /></div>}
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
