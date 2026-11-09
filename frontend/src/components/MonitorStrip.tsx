import clsx from "clsx";
import { Activity, Cpu, HardDrive, MemoryStick, Thermometer, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { formatMb } from "../api/client";
import { useMonitorStore } from "../store/monitor";
import { MetricBar } from "./ui";

function Row({
  icon,
  label,
  value,
  percent,
  tone = "accent",
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  percent: number;
  tone?: "accent" | "mint" | "danger";
  sub?: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-[11px]">
        <span className="flex items-center gap-1.5 text-[var(--muted)]">
          {icon}
          {label}
        </span>
        <span className="font-medium tabular-nums text-[var(--text)]">{value}</span>
      </div>
      <MetricBar value={percent} tone={tone} />
      {sub && <div className="text-[10px] text-[var(--muted)]">{sub}</div>}
    </div>
  );
}

export function MonitorStrip({ compact = false }: { compact?: boolean }) {
  const snapshot = useMonitorStore((state) => state.snapshot);
  const connected = useMonitorStore((state) => state.connected);
  if (!snapshot) {
    return (
      <div className={clsx("rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-3", compact && "text-xs")}>
        <div className="flex items-center gap-2 text-[var(--muted)]">
          <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
          Подключение к монитору…
        </div>
      </div>
    );
  }
  const gpu = snapshot.gpu;
  const vramPercent = gpu.available && gpu.vram_used_mb && gpu.vram_total_mb ? (gpu.vram_used_mb / gpu.vram_total_mb) * 100 : 0;
  const vramTone = vramPercent >= 90 ? "danger" : vramPercent >= 80 ? "accent" : "mint";
  const ramTone = snapshot.ram.percent >= 90 ? "danger" : snapshot.ram.percent >= 80 ? "accent" : "mint";

  if (compact) {
    return (
      <Link
        to="/monitor"
        className="block rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-3 transition hover:border-[var(--accent)]/40"
      >
        <div className="mb-2.5 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">
            <Activity size={12} /> Ресурсы
          </span>
          <span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "bg-mint-400" : "bg-red-400")} title={connected ? "WebSocket подключён" : "Нет соединения"} />
        </div>
        <div className="space-y-2.5">
          <Row icon={<Cpu size={12} />} label="CPU" value={`${snapshot.cpu.percent.toFixed(0)}%`} percent={snapshot.cpu.percent} sub={snapshot.cpu.temp_c ? `${snapshot.cpu.temp_c} °C` : snapshot.cpu.freq_mhz ? `${snapshot.cpu.freq_mhz} MHz` : undefined} />
          <Row icon={<MemoryStick size={12} />} label="RAM" value={`${snapshot.ram.percent.toFixed(0)}%`} percent={snapshot.ram.percent} tone={ramTone} sub={`${formatMb(snapshot.ram.used_mb)} / ${formatMb(snapshot.ram.total_mb)}`} />
          {gpu.available ? (
            <>
              <Row icon={<Zap size={12} />} label="GPU" value={`${gpu.util ?? 0}%`} percent={gpu.util ?? 0} tone="mint" sub={gpu.temp_c ? `${gpu.temp_c} °C` : undefined} />
              <Row icon={<HardDrive size={12} />} label="VRAM" value={`${formatMb(gpu.vram_used_mb)} / ${formatMb(gpu.vram_total_mb)}`} percent={vramPercent} tone={vramTone} />
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-2 py-2 text-[10px] leading-4 text-[var(--muted)]">
              GPU недоступен: {gpu.error || "NVIDIA не найден"}
            </div>
          )}
          <div className="flex items-center justify-between pt-0.5 text-[10px] text-[var(--muted)]">
            <span className="flex items-center gap-1">
              <Thermometer size={10} /> GPU {gpu.temp_c ?? "—"} °C
            </span>
            <span>swap {snapshot.ram.swap_percent.toFixed(0)}%</span>
          </div>
        </div>
      </Link>
    );
  }

  return (
    <div className="panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Живой монитор</div>
          <div className="mt-1 text-sm text-[var(--text)]">{gpu.available ? gpu.name : "GPU недоступен"}</div>
        </div>
        <span className={clsx("flex items-center gap-2 text-xs", connected ? "text-mint-400" : "text-red-400")}>
          <span className={clsx("h-2 w-2 rounded-full", connected ? "bg-mint-400" : "bg-red-400")} />
          {connected ? "1 Hz" : "offline"}
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Row icon={<Cpu size={14} />} label="CPU" value={`${snapshot.cpu.percent.toFixed(0)}%`} percent={snapshot.cpu.percent} sub={snapshot.cpu.temp_c ? `${snapshot.cpu.temp_c} °C · ${snapshot.cpu.freq_mhz ?? "—"} MHz` : `${snapshot.cpu.freq_mhz ?? "—"} MHz`} />
        <Row icon={<MemoryStick size={14} />} label="RAM" value={`${formatMb(snapshot.ram.used_mb)} / ${formatMb(snapshot.ram.total_mb)}`} percent={snapshot.ram.percent} tone={ramTone} sub={`swap ${formatMb(snapshot.ram.swap_used_mb)}`} />
        {gpu.available ? (
          <>
            <Row icon={<Zap size={14} />} label="GPU" value={`${gpu.util ?? 0}%`} percent={gpu.util ?? 0} tone="mint" sub={`${gpu.temp_c ?? "—"} °C · ${gpu.power_w ?? "—"} W`} />
            <Row icon={<HardDrive size={14} />} label="VRAM" value={`${formatMb(gpu.vram_used_mb)} / ${formatMb(gpu.vram_total_mb)}`} percent={vramPercent} tone={vramTone} sub={`свободно ${formatMb((gpu.vram_total_mb ?? 0) - (gpu.vram_used_mb ?? 0))}`} />
          </>
        ) : (
          <div className="sm:col-span-2 rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
            GPU-блок недоступен, приложение продолжает работать. {gpu.error}
          </div>
        )}
      </div>
    </div>
  );
}
