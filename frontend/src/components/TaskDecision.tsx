import { AlertTriangle, Cpu, HardDrive, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, formatMb } from "../api/client";
import type { ResourceOption, ResourcePlan, TaskInfo } from "../api/types";
import { Badge, ErrorBox, MetricBar } from "./ui";

export function ResourceDecision({
  task,
  onResolved,
}: {
  task: TaskInfo;
  onResolved: () => void;
}) {
  const plan = (task.progress?.plan || (task.params as { resource_plan?: ResourcePlan })?.resource_plan) as ResourcePlan | undefined;
  const [choice, setChoice] = useState("evict");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!plan || task.status !== "awaiting_decision") return null;
  // The backend emits unique ids such as "evict:<model>" / "cpu:<variant>"; the kind is in `action`.
  const evictOptions = plan.options.filter((option) => option.action === "evict");
  const cpuOption = plan.options.find((option) => option.action === "cpu");
  const quantOption = plan.options.find((option) => option.action === "quant");

  const resolve = async (value: string, extra: { model_id?: string; variant_id?: string } = {}) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/tasks/${task.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ choice: value, ...extra }),
      });
      onResolved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const options: { id: string; label: string; description: string; icon: React.ReactNode; disabled?: boolean; onClick: () => void }[] = [];
  for (const option of evictOptions) {
    options.push({
      id: `evict-${option.model_id}`,
      label: option.label,
      description: `Освободит ~${(option.reclaim_gb ?? 0).toFixed(1)} GB VRAM${option.would_fit ? " и позволит загрузить модель" : ""}.`,
      icon: <Trash2 size={17} />,
      disabled: !option.would_fit,
      onClick: () => resolve("evict", { model_id: option.model_id }),
    });
  }
  if (cpuOption) {
    options.push({
      id: "cpu",
      label: "Перевести на CPU",
      description: "Медленнее, но не занимает VRAM. Зависит от RAM.",
      icon: <Cpu size={17} />,
      disabled: !cpuOption.would_fit,
      onClick: () => resolve("cpu", { variant_id: cpuOption.variant_id }),
    });
  }
  if (quantOption) {
    options.push({
      id: "quant",
      label: quantOption.label,
      description: "Более лёгкая квантизация; качество может снизиться.",
      icon: <HardDrive size={17} />,
      disabled: !quantOption.would_fit,
      onClick: () => resolve("quant", { variant_id: quantOption.variant_id }),
    });
  }
  if (plan.verdict === "tight") {
    options.push({
      id: "confirm",
      label: "Загрузить всё равно",
      description: "Память впритык. Возможен OOM; сервер переживёт его и освободит VRAM.",
      icon: <AlertTriangle size={17} />,
      onClick: () => resolve("confirm"),
    });
  }
  options.push({
    id: "cancel",
    label: "Отменить задачу",
    description: "Задача не будет выполнена.",
    icon: <RefreshCw size={17} />,
    onClick: () => resolve("cancel"),
  });

  return (
    <div className="rounded-2xl border border-amber-400/30 bg-amber-400/5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold"><AlertTriangle size={17} className="text-amber-500" /> Модель не помещается автоматически</div>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">{task.error_message || plan.reason}</p>
        </div>
        <Badge tone={plan.verdict === "tight" ? "accent" : "danger"}>{plan.verdict === "tight" ? "впритык" : "не влезает"}</Badge>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3">
          <div className="flex justify-between text-[11px] text-[var(--muted)]"><span>VRAM нужно</span><span>{plan.need_vram_gb.toFixed(2)} GB</span></div>
          <div className="mt-2"><MetricBar value={plan.need_vram_gb} max={Math.max(plan.need_vram_gb + plan.free_vram_gb, 1)} tone="accent" /></div>
          <div className="mt-2 flex justify-between text-[11px] text-[var(--muted)]"><span>свободно</span><span>{plan.free_vram_gb.toFixed(2)} GB</span></div>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3">
          <div className="flex justify-between text-[11px] text-[var(--muted)]"><span>RAM нужно</span><span>{plan.need_ram_gb.toFixed(2)} GB</span></div>
          <div className="mt-2"><MetricBar value={plan.need_ram_gb} max={Math.max(plan.need_ram_gb + plan.free_ram_gb, 1)} tone="mint" /></div>
          <div className="mt-2 flex justify-between text-[11px] text-[var(--muted)]"><span>свободно</span><span>{plan.free_ram_gb.toFixed(2)} GB</span></div>
        </div>
      </div>
      <div className="mt-4 space-y-2">
        {options.map((option) => (
          <button
            key={option.id}
            disabled={busy || option.disabled}
            onClick={option.onClick}
            className="flex w-full items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3 text-left transition hover:border-[var(--accent)]/40 disabled:cursor-not-allowed disabled:opacity-45"
          >
            <span className="mt-0.5 text-[var(--accent)]">{option.icon}</span>
            <span className="min-w-0">
              <span className="block text-xs font-medium">{option.label}</span>
              <span className="mt-0.5 block text-[11px] leading-4 text-[var(--muted)]">{option.description}</span>
            </span>
          </button>
        ))}
      </div>
      {error && <div className="mt-3"><ErrorBox message={error} onClose={() => setError(null)} /></div>}
    </div>
  );
}
