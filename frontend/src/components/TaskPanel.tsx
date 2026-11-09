import clsx from "clsx";
import { CheckCircle2, Clock3, Download, Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import type { TaskInfo } from "../api/types";
import { Badge, MetricBar, Panel } from "./ui";

const terminal = new Set(["completed", "failed", "cancelled"]);

function sec(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0.0s";
  return `${(ms / 1000).toFixed(1)}s`;
}

function elapsed(task: TaskInfo): number {
  if (task.finished_at) return task.total_ms;
  const start = task.queued_at ? new Date(task.queued_at).getTime() : Date.now();
  return Date.now() - start;
}

export function TaskTimer({ task }: { task: TaskInfo }) {
  const [, force] = useState(0);
  useEffect(() => {
    if (terminal.has(task.status)) return;
    const timer = window.setInterval(() => force((value) => value + 1), 250);
    return () => window.clearInterval(timer);
  }, [task.status]);
  const total = elapsed(task);
  const queue = task.queue_ms || (task.started_at ? new Date(task.started_at).getTime() - new Date(task.queued_at ?? task.started_at).getTime() : total);
  const load = task.load_ms || (task.progress?.load_ms as number | undefined) || 0;
  const infer = task.infer_ms || 0;
  const post = task.post_ms || 0;
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--panel-2)] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-medium">
          {task.status === "completed" ? <CheckCircle2 size={15} className="text-mint-400" /> : task.status === "failed" ? <TriangleAlert size={15} className="text-red-400" /> : <Loader2 size={15} className="animate-spin text-[var(--accent)]" />}
          {task.status === "awaiting_decision" ? "Ожидает решения" : task.status === "completed" ? "Готово" : task.status === "failed" ? "Ошибка" : task.status === "queued" ? "В очереди" : "В работе"}
        </div>
        <div className="font-mono text-sm font-semibold tabular-nums text-[var(--accent)]">{sec(total)}</div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-[11px] text-[var(--muted)] sm:grid-cols-4">
        <div><div className="uppercase tracking-wider">очередь</div><div className="mt-1 font-mono text-sm text-[var(--text)]">{sec(queue)}</div></div>
        <div><div className="uppercase tracking-wider">загрузка</div><div className="mt-1 font-mono text-sm text-[var(--text)]">{sec(load)}</div></div>
        <div><div className="uppercase tracking-wider">инференс</div><div className="mt-1 font-mono text-sm text-[var(--text)]">{sec(infer)}</div></div>
        <div><div className="uppercase tracking-wider">постобработка</div><div className="mt-1 font-mono text-sm text-[var(--text)]">{sec(post)}</div></div>
      </div>
      <div className="mt-3"><MetricBar value={terminal.has(task.status) ? 100 : task.status === "running" ? 65 : 20} tone={task.status === "failed" ? "danger" : task.status === "completed" ? "mint" : "accent"} /></div>
      {task.status === "failed" && task.error_message && <div className="mt-3 rounded-lg border border-red-400/25 bg-red-400/5 p-3 text-xs text-red-600 dark:text-red-300">{task.error_message}</div>}
    </div>
  );
}

export function TaskStats({ task }: { task: TaskInfo }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Panel className="p-4"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Общее время</div><div className="mt-1 text-xl font-semibold tabular-nums">{sec(task.total_ms)}</div></Panel>
      <Panel className="p-4"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">RTF инференса</div><div className="mt-1 text-xl font-semibold tabular-nums">{task.rtf_infer ? task.rtf_infer.toFixed(3) : "—"}</div></Panel>
      <Panel className="p-4"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Аудио</div><div className="mt-1 text-xl font-semibold tabular-nums">{task.audio_duration_sec ? `${task.audio_duration_sec.toFixed(1)}s` : "—"}</div></Panel>
      <Panel className="p-4"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Пик VRAM</div><div className="mt-1 text-xl font-semibold tabular-nums">{task.peak_vram_mb ? `${(task.peak_vram_mb / 1024).toFixed(1)} GB` : "—"}</div></Panel>
    </div>
  );
}

export function TaskAudio({ task, compact = false }: { task: TaskInfo; compact?: boolean }) {
  if (task.status !== "completed" || !task.output_paths.some((path) => path.endsWith(".wav"))) return null;
  return (
    <div className={clsx("rounded-2xl border border-[var(--border)] bg-[var(--panel-2)] p-4", compact && "p-3")}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-medium"><Clock3 size={14} className="text-[var(--muted)]" /> Результат синтеза</div>
        <Badge tone={task.warnings.some((warning) => warning.toLowerCase().includes("watermark")) ? "accent" : "mint"}>
          {task.warnings.some((warning) => warning.toLowerCase().includes("watermark")) ? "watermark" : "готово"}
        </Badge>
      </div>
      <audio controls src={`/api/tasks/${task.id}/audio`} className="w-full" />
      <div className="mt-2 flex flex-wrap gap-2">
        <a className="btn" href={`/api/tasks/${task.id}/audio?format=wav`}><Download size={14} /> WAV</a>
        <a className="btn" href={`/api/tasks/${task.id}/audio?format=mp3`}><Download size={14} /> MP3</a>
      </div>
      {task.warnings.length > 0 && <div className="mt-3 space-y-1 text-[11px] text-amber-600 dark:text-amber-300">{task.warnings.map((warning) => <div key={warning}>• {warning}</div>)}</div>}
    </div>
  );
}
