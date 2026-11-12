import clsx from "clsx";
import { Activity, Check, Cpu, Eraser, Gauge, HardDrive, MemoryStick, Thermometer, TriangleAlert, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, formatMb } from "../api/client";
import type { AlertInfo, Snapshot } from "../api/types";
import { Modal } from "../components/Modal";
import { Sparkline } from "../components/Sparkline";
import { Badge, EmptyState, ErrorBox, MetricBar, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { usePolling } from "../hooks/usePolling";
import { useMonitorStore } from "../store/monitor";

function Stat({
  icon,
  label,
  value,
  sub,
  percent,
  tone = "accent",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  percent?: number;
  tone?: "accent" | "mint" | "danger";
}) {
  return (
    <Panel className="p-5">
      <div className="flex items-start justify-between text-[var(--muted)]">
        <span className="text-[11px] font-semibold uppercase tracking-[0.15em]">{label}</span>
        {icon}
      </div>
      <div className="mt-3 text-2xl font-semibold tabular-nums">{value}</div>
      {percent !== undefined && <div className="mt-3"><MetricBar value={percent} tone={tone} /></div>}
      {sub && <div className="mt-2 text-[11px] text-[var(--muted)]">{sub}</div>}
    </Panel>
  );
}

export function MonitorPage() {
  const snapshot = useMonitorStore((state) => state.snapshot);
  const setSnapshot = useMonitorStore((state) => state.setSnapshot);
  const history = useAsync(() => api<Snapshot[]>("/api/monitor/history?seconds=300"), []);
  const alerts = useAsync(() => api<AlertInfo[]>("/api/monitor/alerts?limit=50"), []);
  const [unloadOpen, setUnloadOpen] = useState(false);
  const [unloading, setUnloading] = useState(false);
  const [unloadMessage, setUnloadMessage] = useState<string | null>(null);
  const [unloadError, setUnloadError] = useState<string | null>(null);
  const loadedCount = snapshot?.models.length ?? 0;
  const gpu = snapshot?.gpu;
  const vramPercent = gpu?.available && gpu.vram_used_mb && gpu.vram_total_mb ? (gpu.vram_used_mb / gpu.vram_total_mb) * 100 : 0;
  const data = history.data ?? [];
  const cpuSeries = data.map((item) => item.cpu.percent);
  const ramSeries = data.map((item) => item.ram.percent);
  const vramSeries = data.map((item) => (item.gpu.available && item.gpu.vram_used_mb && item.gpu.vram_total_mb ? (item.gpu.vram_used_mb / item.gpu.vram_total_mb) * 100 : 0));
  const gpuSeries = data.map((item) => item.gpu.util ?? 0);
  const diskSeries = data.map((item) => item.disk.read_mb_s + item.disk.write_mb_s);

  const lastSeq = useRef(0);
  useEffect(() => {
    const last = history.data?.[history.data.length - 1]?.seq ?? 0;
    if (last > lastSeq.current) lastSeq.current = last;
  }, [history.data]);
  usePolling(() => {
    // Only fetch samples we have not seen (the full 300-sample window is ~170 KB).
    api<Snapshot[]>(`/api/monitor/history?seconds=300&after=${lastSeq.current}`)
      .then((fresh) => {
        if (!fresh.length) return;
        lastSeq.current = fresh[fresh.length - 1].seq;
        history.setData((previous) => [...(previous ?? []), ...fresh].slice(-300));
      })
      .catch(() => undefined);
    api<AlertInfo[]>("/api/monitor/alerts?limit=50").then(alerts.setData).catch(() => undefined);
  }, 2000);

  const acknowledge = async (id: string) => {
    await api(`/api/monitor/alerts/${id}/ack`, { method: "POST" });
    alerts.reload();
  };

  const unloadAll = async () => {
    setUnloading(true);
    setUnloadError(null);
    try {
      const result = await api<{ count: number; loaded_before: string[] }>("/api/resources/unload-all", {
        method: "POST",
        body: JSON.stringify({ force: true }),
      });
      setUnloadMessage(`Выгружено моделей: ${result.count}. VRAM и RAM освобождены.`);
      setUnloadOpen(false);
      const next = await api<Snapshot>("/api/monitor/snapshot");
      setSnapshot(next);
      history.reload();
    } catch (err) {
      setUnloadError((err as Error).message);
    } finally {
      setUnloading(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Система"
        title="Мониторинг"
        description="Живые метрики хоста и GPU, история за пять минут, предупреждения о ресурсах."
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={snapshot ? "mint" : "danger"}>{snapshot ? "обновление 1 Гц" : "нет соединения"}</Badge>
            <button
              className="btn border-red-400/30 text-red-600 hover:bg-red-400/10 disabled:opacity-40 dark:text-red-300"
              disabled={loadedCount === 0}
              title={loadedCount === 0 ? "Нет загруженных моделей" : "Выгрузить все модели из VRAM/RAM"}
              onClick={() => setUnloadOpen(true)}
            >
              <Eraser size={15} /> Выгрузить всё {loadedCount > 0 ? `(${loadedCount})` : ""}
            </button>
          </div>
        }
      />

      {unloadMessage && <div className="flex items-center justify-between gap-3 rounded-xl border border-mint-400/30 bg-mint-400/10 px-4 py-3 text-sm text-emerald-700 dark:text-mint-300"><span>{unloadMessage}</span><button className="text-current opacity-60 hover:opacity-100" onClick={() => setUnloadMessage(null)}>✕</button></div>}
      {unloadError && <ErrorBox message={unloadError} onClose={() => setUnloadError(null)} />}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={<Cpu size={16} />} label="CPU" value={`${snapshot?.cpu.percent.toFixed(0) ?? "—"}%`} percent={snapshot?.cpu.percent ?? 0} sub={snapshot?.cpu.temp_c ? `${snapshot.cpu.temp_c} °C · ${snapshot.cpu.freq_mhz} MHz` : `${snapshot?.cpu.freq_mhz ?? "—"} MHz`} tone="mint" />
        <Stat icon={<Zap size={16} />} label="GPU" value={gpu?.available ? `${gpu.util ?? 0}%` : "N/A"} percent={gpu?.util ?? 0} sub={gpu?.available ? `${gpu.temp_c ?? "—"} °C · ${gpu.power_w ?? "—"} W` : gpu?.error} tone="mint" />
        <Stat icon={<HardDrive size={16} />} label="VRAM" value={gpu?.available ? formatMb(gpu.vram_used_mb) : "N/A"} percent={vramPercent} sub={gpu?.available ? `${formatMb(gpu.vram_total_mb)} всего` : "GPU недоступен"} tone={vramPercent > 90 ? "danger" : "accent"} />
        <Stat icon={<MemoryStick size={16} />} label="RAM" value={`${snapshot?.ram.percent.toFixed(0) ?? "—"}%`} percent={snapshot?.ram.percent ?? 0} sub={snapshot ? `${formatMb(snapshot.ram.used_mb)} / ${formatMb(snapshot.ram.total_mb)} · swap ${snapshot.ram.swap_percent.toFixed(0)}%` : undefined} tone={(snapshot?.ram.percent ?? 0) > 90 ? "danger" : "accent"} />
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold">Загрузка CPU</div>
            <span className="text-xs text-[var(--muted)]">5 минут</span>
          </div>
          <Sparkline values={cpuSeries} color="var(--mint)" max={100} />
          <div className="mt-5 grid grid-cols-6 gap-2 sm:grid-cols-8 lg:grid-cols-12">
            {snapshot?.cpu.per_core.map((value, index) => (
              <div key={index}>
                <div className="mb-1 flex justify-between text-[9px] text-[var(--muted)]"><span>{index}</span><span>{value.toFixed(0)}</span></div>
                <div className="h-1.5 rounded-full bg-[var(--track)]"><div className="h-full rounded-full bg-mint-400" style={{ width: `${Math.min(value, 100)}%` }} /></div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold">GPU и VRAM</div>
            <span className="text-xs text-[var(--muted)]">5 минут</span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--muted)]">загрузка</div>
              <Sparkline values={gpuSeries} color="var(--accent)" max={100} />
            </div>
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--muted)]">VRAM</div>
              <Sparkline values={vramSeries} color="var(--danger)" max={100} />
            </div>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3 text-xs text-[var(--muted)]">
            <div><div className="text-[10px] uppercase tracking-wider">temp</div><div className="mt-1 text-base text-[var(--text)]">{gpu?.temp_c ?? "—"} °C</div></div>
            <div><div className="text-[10px] uppercase tracking-wider">power</div><div className="mt-1 text-base text-[var(--text)]">{gpu?.power_w ?? "—"} W</div></div>
            <div><div className="text-[10px] uppercase tracking-wider">clock</div><div className="mt-1 text-base text-[var(--text)]">{gpu?.clock_mhz ?? "—"} MHz</div></div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.3fr_.7fr]">
        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold">Диск и память</div>
            <Gauge size={15} className="text-[var(--muted)]" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-4">
              <div className="flex items-center justify-between text-xs text-[var(--muted)]"><span>RAM</span><span>{snapshot ? `${formatMb(snapshot.ram.used_mb)} / ${formatMb(snapshot.ram.total_mb)}` : "—"}</span></div>
              <div className="mt-3"><MetricBar value={snapshot?.ram.percent ?? 0} tone={(snapshot?.ram.percent ?? 0) > 90 ? "danger" : "accent"} /></div>
              <div className="mt-3 flex justify-between text-[11px] text-[var(--muted)]"><span>swap</span><span>{snapshot ? `${formatMb(snapshot.ram.swap_used_mb)} / ${formatMb(snapshot.ram.swap_total_mb)}` : "—"}</span></div>
            </div>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-4">
              <div className="flex items-center justify-between text-xs text-[var(--muted)]"><span>Диск</span><span>{snapshot ? `${snapshot.disk.free_gb} GB свободно` : "—"}</span></div>
              <Sparkline values={diskSeries} color="var(--mint)" />
              <div className="mt-2 flex justify-between text-[11px] text-[var(--muted)]"><span>чтение {snapshot?.disk.read_mb_s ?? 0} MB/s</span><span>запись {snapshot?.disk.write_mb_s ?? 0} MB/s</span></div>
            </div>
          </div>
          <div className="mt-4 overflow-hidden rounded-xl border border-[var(--border)]">
            <table className="w-full text-left text-xs">
              <thead className="bg-[var(--panel-2)] text-[10px] uppercase tracking-wider text-[var(--muted)]">
                <tr><th className="px-3 py-2">Модель</th><th className="px-3 py-2">Устройство</th><th className="px-3 py-2">VRAM</th><th className="px-3 py-2">Состояние</th></tr>
              </thead>
              <tbody>
                {(snapshot?.models ?? []).map((model) => (
                  <tr key={model.model_id} className="border-t border-[var(--border)]">
                    <td className="px-3 py-2.5">{model.model_name ?? model.model_id}</td>
                    <td className="px-3 py-2.5 uppercase text-[var(--muted)]">{model.device}</td>
                    <td className="px-3 py-2.5 tabular-nums">{formatMb(model.vram_mb ?? 0)}</td>
                    <td className="px-3 py-2.5"><Badge tone={model.state === "loaded" ? "mint" : "neutral"}>{model.state}</Badge></td>
                  </tr>
                ))}
                {!(snapshot?.models ?? []).length && (
                  <tr><td colSpan={4} className="px-3 py-8 text-center text-[var(--muted)]">Нет загруженных моделей</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold">Предупреждения</div>
            <Badge tone={alerts.data?.length ? "accent" : "mint"}>{alerts.data?.length ?? 0}</Badge>
          </div>
          {alerts.data?.length ? (
            <div className="max-h-[420px] space-y-2 overflow-auto pr-1">
              {alerts.data.map((alert) => (
                <div key={alert.id} className={clsx("rounded-xl border p-3", alert.severity === "critical" ? "border-red-400/30 bg-red-400/5" : alert.severity === "high" ? "border-orange-400/30 bg-orange-400/5" : "border-amber-400/25 bg-amber-400/5")}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs font-medium"><TriangleAlert size={13} className={alert.severity === "critical" ? "text-red-400" : "text-amber-500"} /> {alert.metric}</div>
                    {!alert.acknowledged && (
                      <button className="rounded p-1 text-[var(--muted)] hover:bg-[var(--hover)]" onClick={() => acknowledge(alert.id)} title="Подтвердить"><Check size={13} /></button>
                    )}
                  </div>
                  <div className="mt-1 text-[11px] leading-4 text-[var(--muted)]">{alert.message}</div>
                  <div className="mt-1 text-[10px] text-[var(--muted)]">{new Date(alert.ts).toLocaleString("ru-RU")}</div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={<Activity size={20} />} title="Пока тихо" text="Пороги VRAM, RAM, swap и температуры GPU не превышены." />
          )}
        </Panel>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Panel className="p-4 text-xs text-[var(--muted)]"><div className="flex items-center gap-2 text-[var(--text)]"><Thermometer size={14} /> Пороговые уровни</div><p className="mt-2 leading-5">80% — жёлтый, 90% — оранжевый, 100% — красный. GPU: 80 °C.</p></Panel>
        <Panel className="p-4 text-xs text-[var(--muted)]"><div className="flex items-center gap-2 text-[var(--text)]"><Cpu size={14} /> CPU-температура</div><p className="mt-2 leading-5">На Windows датчик часто недоступен — показывается «—», приложение не падает.</p></Panel>
        <Panel className="p-4 text-xs text-[var(--muted)]"><div className="flex items-center gap-2 text-[var(--text)]"><HardDrive size={14} /> История</div><p className="mt-2 leading-5">В памяти хранится 300 секунд; в БД сохраняются пики задач и предупреждения.</p></Panel>
      </div>

      <Modal
        open={unloadOpen}
        onClose={() => !unloading && setUnloadOpen(false)}
        title="Выгрузить все модели?"
        subtitle={`Сейчас загружено: ${loadedCount}.`}
        footer={
          <>
            <button className="btn" disabled={unloading} onClick={() => setUnloadOpen(false)}>Отмена</button>
            <button className="btn border-red-400/30 bg-red-500 text-white hover:bg-red-600" disabled={unloading} onClick={unloadAll}>
              <Eraser size={15} /> {unloading ? "Выгружаем…" : "Выгрузить всё"}
            </button>
          </>
        }
      >
        <div className="space-y-3 text-xs leading-5 text-[var(--muted)]">
          <div className="rounded-xl border border-amber-400/25 bg-amber-400/5 p-3 text-amber-700 dark:text-amber-300">
            Активные задачи будут прерваны. Очередь и история сохранятся.
          </div>
          <p>Будут остановлены все воркеры, освобождены VRAM и RAM. Сервер продолжит работать — можно сразу загрузить модель снова.</p>
          <div className="space-y-1.5">
            {(snapshot?.models ?? []).map((model) => (
              <div key={model.model_id} className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2">
                <span className="text-[var(--text)]">{model.model_name ?? model.model_id}</span>
                <span className="uppercase">{model.device} · {formatMb(model.vram_mb ?? 0)}</span>
              </div>
            ))}
          </div>
          {unloadError && <ErrorBox message={unloadError} onClose={() => setUnloadError(null)} />}
        </div>
      </Modal>
    </div>
  );
}
