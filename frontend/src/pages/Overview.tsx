import clsx from "clsx";
import {
  ArrowRight,
  AudioLines,
  Boxes,
  CheckCircle2,
  Clock3,
  Cpu,
  FolderKanban,
  Gauge,
  HardDrive,
  Mic2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api, formatMb, formatMs } from "../api/client";
import type { HealthInfo, QueuePayload, StartupInfo, SystemInfo } from "../api/types";
import { MonitorStrip } from "../components/MonitorStrip";
import { Badge, EmptyState, MetricBar, PageHeader, Panel, StatusDot } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useMonitorStore } from "../store/monitor";

const quickActions = [
  { to: "/stt", title: "Транскрипция", text: "Файл или микрофон, таймкоды и экспорт", icon: Mic2, tone: "text-sky-500 dark:text-sky-300" },
  { to: "/tts", title: "Синтез речи", text: "Встроенные и клонированные голоса", icon: AudioLines, tone: "text-amber-500 dark:text-amber-300" },
  { to: "/voices", title: "Клонировать голос", text: "5–30 секунд референса и проверка качества", icon: Sparkles, tone: "text-emerald-600 dark:text-mint-300" },
  { to: "/models", title: "Менеджер моделей", text: "Скачивание, замеры VRAM и загрузка", icon: Boxes, tone: "text-violet-500 dark:text-violet-300" },
];

export function OverviewPage() {
  const snapshot = useMonitorStore((state) => state.snapshot);
  const info = useAsync(() => api<SystemInfo>("/api/system/info"), []);
  const health = useAsync(() => api<HealthInfo>("/api/health"), []);
  const startup = useAsync(() => api<StartupInfo>("/api/system/startup/current"), []);
  const queue = useAsync(() => api<QueuePayload>("/api/queue"), []);
  const gpu = info.data?.gpu;
  const gpuMem = snapshot?.gpu;
  const vramPercent = gpuMem?.available && gpuMem.vram_used_mb && gpuMem.vram_total_mb ? (gpuMem.vram_used_mb / gpuMem.vram_total_mb) * 100 : 0;
  const unacked = snapshot?.alerts.filter((alert) => !alert.acknowledged) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="MyVS · локальная студия"
        title="Рабочий стол"
        description="Речь остаётся на этой машине: STT, TTS, клонирование и модели работают без внешних API."
        actions={
          <>
            <button className="btn" onClick={() => { info.reload(); health.reload(); startup.reload(); }}>
              <RefreshCw size={15} /> Обновить
            </button>
            <Link to="/models" className="btn-primary">
              <Boxes size={16} /> Модели
            </Link>
          </>
        }
      />

      <section className="relative overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-panel md:p-8">
        <div className="pointer-events-none absolute inset-0 grid-bg opacity-30" />
        <div className="pointer-events-none absolute -right-10 -top-20 h-64 w-64 rounded-full bg-[var(--accent)]/10 blur-3xl" />
        <div className="relative grid gap-8 lg:grid-cols-[1.2fr_.8fr] lg:items-center">
          <div>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <Badge tone="mint"><span className="h-1.5 w-1.5 rounded-full bg-mint-400" /> всё локально</Badge>
              <Badge tone="accent"><ShieldCheck size={11} /> без внешних API</Badge>
              <Badge>{info.data?.platform ?? "Windows"}</Badge>
            </div>
            <h2 className="max-w-xl text-3xl font-semibold leading-tight tracking-tight md:text-[40px]">
              Слышать. Синтезировать. <span className="text-[var(--accent)]">Своим голосом.</span>
            </h2>
            <p className="mt-4 max-w-xl text-sm leading-6 text-[var(--muted)]">
              Один рабочий стол для расшифровки, озвучивания и экспериментов с голосом. Модели живут в изолированных GPU-воркерах,
              а бюджет VRAM и RAM виден до запуска.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/stt" className="btn-primary"><Mic2 size={16} /> Начать с транскрипции</Link>
              <Link to="/tts" className="btn"><AudioLines size={16} /> Озвучить текст</Link>
            </div>
          </div>
          <div className="relative flex min-h-[170px] items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--bg)]/60 px-6">
            <div className="absolute left-5 top-4 text-[10px] uppercase tracking-[0.2em] text-[var(--muted)]">waveform / ready</div>
            <div className="wave-bars text-[var(--accent)]">
              {[18, 32, 12, 38, 24, 44, 16, 30, 46, 22, 36, 14, 28, 40, 20, 34, 10, 26, 42, 18, 30, 12, 36, 22, 44, 16, 28, 38, 14, 24].map((height, index) => (
                <span key={index} style={{ height, animationDelay: `${(index % 7) * -0.17}s` }} />
              ))}
            </div>
            <div className="absolute bottom-4 right-5 flex items-center gap-2 text-[10px] text-[var(--muted)]">
              <span className="h-1.5 w-1.5 rounded-full bg-mint-400" /> {snapshot?.seq ? `${snapshot.seq} samples` : "connecting"}
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Panel className="p-5">
          <div className="flex items-start justify-between text-[var(--muted)]"><span className="text-xs uppercase tracking-wider">CPU</span><Cpu size={16} /></div>
          <div className="mt-3 text-2xl font-semibold tabular-nums">{snapshot ? `${snapshot.cpu.percent.toFixed(0)}%` : "—"}</div>
          <div className="mt-3"><MetricBar value={snapshot?.cpu.percent ?? 0} tone={(snapshot?.cpu.percent ?? 0) > 85 ? "danger" : "mint"} /></div>
          <div className="mt-2 text-[11px] text-[var(--muted)]">{snapshot ? `${snapshot.cpu.freq_mhz ?? "—"} MHz · ${snapshot.cpu.per_core.length} ядер` : "нет данных"}</div>
        </Panel>
        <Panel className="p-5">
          <div className="flex items-start justify-between text-[var(--muted)]"><span className="text-xs uppercase tracking-wider">RAM</span><Gauge size={16} /></div>
          <div className="mt-3 text-2xl font-semibold tabular-nums">{snapshot ? `${snapshot.ram.percent.toFixed(0)}%` : "—"}</div>
          <div className="mt-3"><MetricBar value={snapshot?.ram.percent ?? 0} tone={(snapshot?.ram.percent ?? 0) > 85 ? "danger" : "accent"} /></div>
          <div className="mt-2 text-[11px] text-[var(--muted)]">{snapshot ? `${formatMb(snapshot.ram.used_mb)} / ${formatMb(snapshot.ram.total_mb)}` : "нет данных"}</div>
        </Panel>
        <Panel className="p-5">
          <div className="flex items-start justify-between text-[var(--muted)]"><span className="text-xs uppercase tracking-wider">VRAM</span><Zap size={16} /></div>
          <div className="mt-3 text-2xl font-semibold tabular-nums">{gpuMem?.available ? `${vramPercent.toFixed(0)}%` : "N/A"}</div>
          <div className="mt-3"><MetricBar value={vramPercent} tone={vramPercent > 90 ? "danger" : "mint"} /></div>
          <div className="mt-2 truncate text-[11px] text-[var(--muted)]">{gpuMem?.available ? `${formatMb(gpuMem.vram_used_mb)} / ${formatMb(gpuMem.vram_total_mb)}` : gpu?.error || "GPU недоступен"}</div>
        </Panel>
        <Panel className="p-5">
          <div className="flex items-start justify-between text-[var(--muted)]"><span className="text-xs uppercase tracking-wider">Готовность</span><CheckCircle2 size={16} /></div>
          <div className="mt-3 flex items-baseline gap-2"><span className="text-2xl font-semibold tabular-nums">{startup.data ? formatMs(startup.data.total_ms) : "—"}</span><span className="text-[11px] text-[var(--muted)]">запуск</span></div>
          <div className="mt-3"><MetricBar value={startup.data?.ready ? 100 : 40} tone="mint" /></div>
          <div className="mt-2 text-[11px] text-[var(--muted)]">{startup.data?.ready ? "API и монитор готовы" : "инициализация"}</div>
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.35fr_.65fr]">
        <div className="space-y-5">
          <MonitorStrip />
          <Panel className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold">Быстрый старт</div>
                <div className="mt-1 text-xs text-[var(--muted)]">Четыре шага до первого результата</div>
              </div>
              <Badge tone="accent">{health.data ? "local" : "offline"}</Badge>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {quickActions.map((action) => {
                const Icon = action.icon;
                return (
                  <Link key={action.to} to={action.to} className="group rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-4 transition hover:border-[var(--accent)]/40">
                    <div className="flex items-center justify-between">
                      <Icon size={20} className={action.tone} />
                      <ArrowRight size={15} className="text-[var(--muted)] transition group-hover:translate-x-0.5 group-hover:text-[var(--accent)]" />
                    </div>
                    <div className="mt-3 text-sm font-medium">{action.title}</div>
                    <div className="mt-1 text-xs leading-5 text-[var(--muted)]">{action.text}</div>
                  </Link>
                );
              })}
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-sm font-semibold">Активные задачи</div>
              <Link to="/queue" className="text-xs text-[var(--muted)] hover:text-[var(--accent)]">Очередь →</Link>
            </div>
            {(queue.data?.tasks.length ?? 0) > 0 ? (
              <div className="space-y-2">
                {queue.data?.tasks.slice(0, 5).map((task) => (
                  <Link key={task.id} to={`/history?task=${task.id}`} className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3 text-xs transition hover:border-[var(--accent)]/40">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] font-mono text-[10px] text-[var(--accent-strong)]">{task.type.toUpperCase()}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{task.model_id || "модель не выбрана"}</span>
                      <span className="mt-0.5 block truncate text-[var(--muted)]">{task.text || task.id}</span>
                    </span>
                    <Badge tone={task.status === "running" ? "mint" : task.status === "awaiting_decision" ? "accent" : "blue"}>{task.status}</Badge>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<Clock3 size={22} />}
                title="Очередь пуста"
                text="Запустите транскрипцию, синтез или тест клонированного голоса — задача появится здесь."
              />
            )}
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-sm font-semibold">Готовность системы</div>
              <StatusDot ok={Boolean(health.data?.ready)} label={health.data?.ready ? "online" : "starting"} />
            </div>
            <div className="space-y-3">
              {[
                { label: "Backend", ok: Boolean(health.data), detail: health.data ? `v${health.data.version}` : "—" },
                { label: "SQLite", ok: Boolean(health.data?.ready), detail: health.data?.data_dir ?? "—" },
                { label: "GPU / NVML", ok: Boolean(gpu?.available), detail: gpu?.available ? gpu.name : gpu?.error ?? "—" },
                { label: "Frontend", ok: Boolean(info.data?.frontend_built), detail: info.data?.frontend_built ? "production build" : "не собран" },
              ].map((item) => (
                <div key={item.label} className="flex items-start gap-3">
                  <span className={clsx("mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full", item.ok ? "bg-mint-400/15 text-mint-400" : "bg-amber-400/15 text-amber-500")}>
                    {item.ok ? <CheckCircle2 size={12} /> : <TriangleAlert size={12} />}
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm">{item.label}</div>
                    <div className="truncate text-[11px] text-[var(--muted)]">{item.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-semibold">Бюджет памяти</div>
              <HardDrive size={15} className="text-[var(--muted)]" />
            </div>
            <div className="space-y-3 text-xs text-[var(--muted)]">
              <div className="flex justify-between gap-3"><span>Резерв VRAM</span><span className="font-medium text-[var(--text)]">{info.data?.reserve_vram_gb ?? 0.8} GB</span></div>
              <div className="flex justify-between gap-3"><span>Резерв RAM</span><span className="font-medium text-[var(--text)]">{info.data?.reserve_ram_gb ?? 3} GB</span></div>
              <div className="flex justify-between gap-3"><span>Свободно на диске</span><span className="font-medium text-[var(--text)]">{info.data?.disk_free_gb ?? "—"} GB</span></div>
              <div className="flex justify-between gap-3"><span>Режим</span><span className="font-medium text-[var(--text)]">параллельный</span></div>
            </div>
            <Link to="/settings" className="mt-4 inline-flex items-center gap-1 text-xs text-[var(--accent)] hover:underline">Настроить бюджет <ArrowRight size={12} /></Link>
          </Panel>

          <Panel className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-semibold">Предупреждения</div>
              <Link to="/monitor" className="text-xs text-[var(--muted)] hover:text-[var(--accent)]">все →</Link>
            </div>
            {unacked.length ? (
              <div className="space-y-2">
                {unacked.slice(0, 3).map((alert) => (
                  <div key={alert.id} className="rounded-lg border border-amber-400/25 bg-amber-400/5 p-3 text-xs text-[var(--text)]">
                    <div className="flex items-center gap-2 font-medium"><TriangleAlert size={13} className="text-amber-500" /> {alert.metric}</div>
                    <div className="mt-1 text-[var(--muted)]">{alert.message}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 text-xs text-[var(--muted)]">
                <ShieldCheck size={15} className="text-mint-400" /> Всё в пределах порогов
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
