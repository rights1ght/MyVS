import clsx from "clsx";
import { Download, History as HistoryIcon, RefreshCw, RotateCcw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ModelInfo, TaskInfo } from "../api/types";
import { Modal } from "../components/Modal";
import { TaskAudio, TaskStats, TaskTimer } from "../components/TaskPanel";
import { Badge, EmptyState, ErrorBox, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const statusTone: Record<string, "mint" | "danger" | "accent" | "blue" | "neutral"> = {
  completed: "mint",
  failed: "danger",
  cancelled: "neutral",
  running: "accent",
  queued: "blue",
  awaiting_decision: "accent",
};

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const tasks = useAsync(() => api<TaskInfo[]>("/api/tasks?limit=200"), []);
  const models = useAsync(() => api<ModelInfo[]>("/api/models"), []);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [modelId, setModelId] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const modelNames = useMemo(() => Object.fromEntries((models.data ?? []).map((model) => [model.id, model.name])), [models.data]);

  useEffect(() => {
    const id = params.get("task");
    if (id) {
      api<TaskInfo>(`/api/tasks/${id}`).then(setSelected).catch(() => undefined);
    }
  }, [params]);

  const list = (tasks.data ?? []).filter((task) => {
    if (type && task.type !== type) return false;
    if (status && task.status !== status) return false;
    if (modelId && task.model_id !== modelId) return false;
    if (query && !`${task.id} ${task.text} ${task.model_id}`.toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });
  const completed = (tasks.data ?? []).filter((task) => task.status === "completed");
  const avgRtf = completed.length ? completed.reduce((sum, task) => sum + task.rtf_infer, 0) / completed.length : 0;
  const failures = (tasks.data ?? []).filter((task) => task.status === "failed").length;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="History & stats" title="История" description="Таймеры, RTF, пики CPU/GPU/VRAM/RAM и результаты задач." actions={<button className="btn" onClick={tasks.reload}><RefreshCw size={15} /> Обновить</button>} />
      {error && <ErrorBox message={error} onClose={() => setError(null)} />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Всего задач</div><div className="mt-1 text-3xl font-semibold">{tasks.data?.length ?? 0}</div></Panel>
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Завершено</div><div className="mt-1 text-3xl font-semibold text-mint-400">{completed.length}</div></Panel>
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Средний RTF</div><div className="mt-1 text-3xl font-semibold tabular-nums">{avgRtf.toFixed(3)}</div></Panel>
        <Panel className="p-5"><div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Ошибки</div><div className="mt-1 text-3xl font-semibold text-red-400">{failures}</div></Panel>
      </div>
      <Panel className="p-4">
        <div className="flex flex-wrap gap-2">
          <div className="relative min-w-[200px] flex-1"><Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" /><input className="input pl-9" placeholder="Поиск по ID, модели, тексту…" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <select className="select w-auto" value={type} onChange={(event) => setType(event.target.value)}><option value="">Все типы</option><option value="stt">STT</option><option value="tts">TTS</option><option value="preview">Preview</option></select>
          <select className="select w-auto" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Все статусы</option><option value="completed">completed</option><option value="failed">failed</option><option value="running">running</option><option value="queued">queued</option></select>
          <select className="select w-auto" value={modelId} onChange={(event) => setModelId(event.target.value)}><option value="">Все модели</option>{(models.data ?? []).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select>
        </div>
      </Panel>
      {list.length === 0 ? <EmptyState icon={<HistoryIcon size={24} />} title="Пока нет задач" text="История заполнится после STT, TTS или клонирования." /> : (
        <Panel className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-xs">
              <thead className="bg-[var(--panel-2)] text-[10px] uppercase tracking-wider text-[var(--muted)]"><tr><th className="px-4 py-3">Задача</th><th className="px-4 py-3">Тип</th><th className="px-4 py-3">Модель</th><th className="px-4 py-3">Статус</th><th className="px-4 py-3">Время</th><th className="px-4 py-3">RTF</th><th className="px-4 py-3">VRAM</th><th className="px-4 py-3" /></tr></thead>
              <tbody>{list.map((task) => (
                <tr key={task.id} className="border-t border-[var(--border)] hover:bg-[var(--hover)]">
                  <td className="px-4 py-3"><button className="text-left" onClick={() => setSelected(task)}><div className="font-mono text-[11px]">{task.id.slice(0, 10)}</div><div className="mt-0.5 max-w-[280px] truncate text-[11px] text-[var(--muted)]">{task.text || "—"}</div></button></td>
                  <td className="px-4 py-3"><Badge tone={task.type === "stt" ? "blue" : "accent"}>{task.type}</Badge></td>
                  <td className="max-w-[150px] truncate px-4 py-3 text-[var(--muted)]">{modelNames[task.model_id] ?? task.model_id ?? "—"}</td>
                  <td className="px-4 py-3"><Badge tone={statusTone[task.status] ?? "neutral"}>{task.status}</Badge></td>
                  <td className="px-4 py-3 tabular-nums text-[var(--muted)]">{task.total_ms ? `${(task.total_ms / 1000).toFixed(1)}s` : "—"}</td>
                  <td className="px-4 py-3 tabular-nums text-[var(--muted)]">{task.rtf_infer ? task.rtf_infer.toFixed(3) : "—"}</td>
                  <td className="px-4 py-3 tabular-nums text-[var(--muted)]">{task.peak_vram_mb ? `${(task.peak_vram_mb / 1024).toFixed(1)} GB` : "—"}</td>
                  <td className="px-4 py-3"><button className="text-[var(--muted)] hover:text-[var(--accent)]" onClick={() => setSelected(task)}>→</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      )}

      <Modal open={Boolean(selected)} onClose={() => { setSelected(null); if (params.get("task")) setParams({}); }} title={`Задача ${selected?.id.slice(0, 12) ?? ""}`} subtitle={selected ? new Date(selected.queued_at ?? "").toLocaleString("ru-RU") : ""} wide footer={<><button className="btn" onClick={() => selected && api(`/api/tasks/${selected.id}/retry`, { method: "POST" }).then((task) => { setSelected(null); tasks.reload(); setParams({ task: (task as TaskInfo).id }); })}><RotateCcw size={14} /> Повторить</button><button className="btn" onClick={() => setSelected(null)}>Закрыть</button></>}>
        {selected && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2"><Badge tone={statusTone[selected.status] ?? "neutral"}>{selected.status}</Badge><Badge>{selected.model_id}</Badge><Badge>{selected.device}</Badge>{selected.warnings.map((warning) => <Badge key={warning} tone="accent">{warning.slice(0, 40)}</Badge>)}</div>
            <TaskTimer task={selected} />
            {selected.status === "completed" && <TaskStats task={selected} />}
            {selected.status === "completed" && selected.type === "stt" && (
              <div>
                <div className="mb-2 text-xs font-semibold text-[var(--muted)]">Транскрипт</div>
                <textarea readOnly className="input min-h-[150px] font-mono text-xs" value={selected.result?.text ?? ""} />
                <div className="mt-2 flex gap-2">{["txt", "srt", "vtt", "json"].map((format) => <a key={format} className="btn px-2 py-1 text-xs" href={`/api/tasks/${selected.id}/export?format=${format}`}><Download size={12} /> {format}</a>)}</div>
              </div>
            )}
            {selected.status === "completed" && <TaskAudio task={selected} />}
            {selected.error_message && <div className="rounded-xl border border-red-400/25 bg-red-400/5 p-3 text-xs text-red-600 dark:text-red-300">{selected.error_code}: {selected.error_message}</div>}
            <div className="grid gap-2 rounded-xl border border-[var(--border)] p-3 text-[11px] text-[var(--muted)] sm:grid-cols-2">
              <div>queue: {selected.queue_ms} ms</div><div>load: {selected.load_ms} ms</div><div>infer: {selected.infer_ms} ms</div><div>post: {selected.post_ms} ms</div><div>peak CPU: {selected.peak_cpu_pct.toFixed(0)}%</div><div>peak GPU: {selected.peak_gpu_pct.toFixed(0)}%</div><div>peak RAM: {(selected.peak_ram_mb / 1024).toFixed(1)} GB</div><div>peak temp: {selected.peak_gpu_temp_c.toFixed(0)} °C</div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
