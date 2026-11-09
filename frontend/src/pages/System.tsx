import clsx from "clsx";
import { CheckCircle2, Clock3, Database, Download, HardDrive, RefreshCw, Server, TriangleAlert, Zap } from "lucide-react";
import { api, formatMs } from "../api/client";
import type { StartupHistoryItem, StartupInfo, SystemInfo } from "../api/types";
import { Badge, EmptyState, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

interface Diagnostics {
  gpu: { available: boolean; name: string; total_mb: number; error: string };
  ffmpeg: string | null;
  packages: Record<string, string>;
  db_path: string;
  db_exists: boolean;
  worker_pid: number | null;
  frontend_index: string;
  runtimes?: Record<string, { env: string; installed: boolean; python: string; fallback: boolean }>;
}

function PhaseBars({ phases, total }: { phases: { name: string; duration_ms: number; status: string; detail: string }[]; total: number }) {
  const max = Math.max(total, ...phases.map((phase) => phase.duration_ms), 1);
  return (
    <div className="space-y-2.5">
      {phases.map((phase) => (
        <div key={phase.name} className="grid grid-cols-[130px_1fr_70px] items-center gap-3 text-xs">
          <div className="truncate text-[var(--muted)]">{phase.name}</div>
          <div className="h-2 overflow-hidden rounded-full bg-[var(--track)]">
            <div
              className={clsx("h-full rounded-full", phase.status === "error" ? "bg-red-400" : "bg-[var(--accent)]")}
              style={{ width: `${Math.max(2, (phase.duration_ms / max) * 100)}%` }}
            />
          </div>
          <div className="text-right tabular-nums text-[var(--muted)]">{formatMs(phase.duration_ms)}</div>
        </div>
      ))}
    </div>
  );
}

export function SystemPage() {
  const info = useAsync(() => api<SystemInfo>("/api/system/info"), []);
  const current = useAsync(() => api<StartupInfo>("/api/system/startup/current"), []);
  const history = useAsync(() => api<StartupHistoryItem[]>("/api/system/startup/history?limit=10"), []);
  const diagnostics = useAsync(() => api<Diagnostics>("/api/system/diagnostics"), []);
  const reload = () => { info.reload(); current.reload(); history.reload(); diagnostics.reload(); };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Система"
        title="О системе"
        description="Этапы запуска, окружение, диагностика и известные ограничения."
        actions={<button className="btn" onClick={reload}><RefreshCw size={15} /> Проверить снова</button>}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Версия", value: info.data?.version ?? "—", sub: info.data?.app ?? "MyVS", icon: Server },
          { label: "Python", value: info.data?.python ?? "—", sub: info.data?.platform ?? "", icon: Database },
          { label: "GPU", value: info.data?.gpu.available ? "доступен" : "нет", sub: info.data?.gpu.name || info.data?.gpu.error || "—", icon: Zap },
          { label: "Диск", value: info.data ? `${info.data.disk_free_gb} GB` : "—", sub: "свободно в data", icon: HardDrive },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <Panel key={item.label} className="p-5">
              <div className="flex items-start justify-between text-[var(--muted)]">
                <span className="text-[11px] font-semibold uppercase tracking-[0.15em]">{item.label}</span>
                <Icon size={16} />
              </div>
              <div className="mt-3 truncate text-xl font-semibold">{item.value}</div>
              <div className="mt-1 truncate text-[11px] text-[var(--muted)]" title={item.sub}>{item.sub}</div>
            </Panel>
          );
        })}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
        <Panel className="p-5">
          <div className="mb-5 flex items-start justify-between">
            <div>
              <div className="text-sm font-semibold">Текущий запуск</div>
              <div className="mt-1 text-xs text-[var(--muted)]">От старта процесса до готовности API</div>
            </div>
            <div className="text-right">
              <div className="text-2xl font-semibold tabular-nums text-[var(--accent)]">{current.data ? formatMs(current.data.total_ms) : "—"}</div>
              <Badge tone={current.data?.ready ? "mint" : "accent"}>{current.data?.ready ? "готово" : "идёт"}</Badge>
            </div>
          </div>
          {current.data?.phases.length ? <PhaseBars phases={current.data.phases} total={current.data.total_ms} /> : <EmptyState icon={<Clock3 size={20} />} title="Нет данных" text="Таймер появится после инициализации." />}
          <div className="mt-5 grid gap-2 border-t border-[var(--border)] pt-4 text-[11px] text-[var(--muted)] sm:grid-cols-3">
            <div>старт: {current.data ? new Date(current.data.started_at).toLocaleTimeString("ru-RU") : "—"}</div>
            <div>готово: {current.data?.ready_at ? new Date(current.data.ready_at).toLocaleTimeString("ru-RU") : "—"}</div>
            <div>фазы: {current.data?.phases.length ?? 0}</div>
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold">Диагностика</div>
            <Badge tone={diagnostics.data?.gpu.available ? "mint" : "danger"}>{diagnostics.data?.gpu.available ? "GPU ok" : "GPU нет"}</Badge>
          </div>
          <div className="space-y-3 text-xs">
            <div className="flex items-start gap-3">
              {diagnostics.data?.ffmpeg ? <CheckCircle2 size={15} className="mt-0.5 text-mint-400" /> : <TriangleAlert size={15} className="mt-0.5 text-amber-500" />}
              <div className="min-w-0"><div className="text-[var(--text)]">ffmpeg</div><div className="truncate text-[var(--muted)]">{diagnostics.data?.ffmpeg ?? "не найден"}</div></div>
            </div>
            <div className="flex items-start gap-3">
              {diagnostics.data?.db_exists ? <CheckCircle2 size={15} className="mt-0.5 text-mint-400" /> : <TriangleAlert size={15} className="mt-0.5 text-amber-500" />}
              <div className="min-w-0"><div className="text-[var(--text)]">SQLite</div><div className="truncate text-[var(--muted)]">{diagnostics.data?.db_path ?? "—"}</div></div>
            </div>
            <div className="flex items-start gap-3">
              <Download size={15} className="mt-0.5 text-[var(--muted)]" />
              <div className="min-w-0"><div className="text-[var(--text)]">Frontend</div><div className="truncate text-[var(--muted)]">{diagnostics.data?.frontend_index ?? "—"}</div></div>
            </div>
          </div>
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--muted)]">Пакеты</div>
            <div className="space-y-1.5 font-mono text-[10px]">
              {Object.entries(diagnostics.data?.packages ?? {}).map(([name, version]) => (
                <div key={name} className="flex justify-between gap-3"><span className="text-[var(--muted)]">{name}</span><span className={version === "not installed" ? "text-amber-500" : "text-[var(--text)]"}>{version}</span></div>
              ))}
            </div>
          </div>
          <div className="mt-4 border-t border-[var(--border)] pt-4">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--muted)]">Изолированные окружения</div>
            <div className="space-y-1.5 text-[10px]">
              {Object.entries(diagnostics.data?.runtimes ?? {}).map(([name, runtime]) => (
                <div key={name} className="flex items-center justify-between gap-3"><span className="text-[var(--muted)]">{name}</span><Badge tone={runtime.installed ? "mint" : "accent"}>{runtime.installed ? runtime.env : "main fallback"}</Badge></div>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between"><div className="text-sm font-semibold">История запусков</div><span className="text-xs text-[var(--muted)]">последние 10</span></div>
          {history.data?.length ? (
            <div className="space-y-2">
              {history.data.map((run, index) => (
                <details key={run.id} className="group rounded-xl border border-[var(--border)] bg-[var(--panel-2)]" open={index === 0}>
                  <summary className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 text-xs">
                    <span className="flex items-center gap-2"><span className={clsx("h-2 w-2 rounded-full", run.ok ? "bg-mint-400" : "bg-red-400")} />{new Date(run.started_at).toLocaleString("ru-RU")}</span>
                    <span className="flex items-center gap-3 text-[var(--muted)]"><span>v{run.app_version}</span><span className="font-semibold text-[var(--text)]">{formatMs(run.total_ms)}</span></span>
                  </summary>
                  <div className="border-t border-[var(--border)] px-4 py-3"><PhaseBars phases={run.phases} total={run.total_ms} /></div>
                </details>
              ))}
            </div>
          ) : (
            <EmptyState icon={<Clock3 size={20} />} title="История пуста" text="Первый запуск появится здесь после готовности приложения." />
          )}
        </Panel>

        <Panel className="p-5">
          <div className="mb-4 text-sm font-semibold">Известные ограничения</div>
          <ul className="space-y-3 text-xs leading-5 text-[var(--muted)]">
            <li className="flex gap-2"><TriangleAlert size={14} className="mt-0.5 shrink-0 text-amber-500" />Без NVIDIA/драйвера GPU-блок показывает «недоступно», приложение работает с CPU-моделями.</li>
            <li className="flex gap-2"><TriangleAlert size={14} className="mt-0.5 shrink-0 text-amber-500" />На Windows per-process VRAM через NVML может быть недоступна; используется глобальная дельта.</li>
            <li className="flex gap-2"><TriangleAlert size={14} className="mt-0.5 shrink-0 text-amber-500" />Температура CPU на Windows часто не отдаётся psutil — это не ошибка приложения.</li>
            <li className="flex gap-2"><TriangleAlert size={14} className="mt-0.5 shrink-0 text-amber-500" />RTX 4060 8 GB: часть VRAM занимает рабочий стол. Пресеты пересчитываются по фактическому бюджету.</li>
            <li className="flex gap-2"><TriangleAlert size={14} className="mt-0.5 shrink-0 text-amber-500" />VoxCPM2 в FP16 не помещается в 8 GB с резервом; приоритет — GGUF-вариант.</li>
            <li className="flex gap-2"><TriangleAlert size={14} className="mt-0.5 shrink-0 text-amber-500" />Chatterbox оставляет watermark во всех выходных файлах; OmniVoice — только некоммерческое использование.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
