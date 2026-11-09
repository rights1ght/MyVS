import clsx from "clsx";
import { AlertTriangle, X } from "lucide-react";
import type { PropsWithChildren, ReactNode } from "react";

export function Panel({ className, children }: PropsWithChildren<{ className?: string }>) {
  return <section className={clsx("panel", className)}>{children}</section>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--accent)]">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text)] md:text-[30px]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function StatusDot({ ok, label }: { ok: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-[var(--muted)]">
      <span className={clsx("h-2 w-2 rounded-full", ok ? "bg-mint-400" : "bg-red-400")} />
      {label}
    </span>
  );
}

export function MetricBar({
  value,
  max = 100,
  tone = "accent",
}: {
  value: number;
  max?: number;
  tone?: "accent" | "mint" | "danger";
}) {
  const percent = Math.max(0, Math.min(100, (value / max) * 100));
  const color = tone === "danger" ? "var(--danger)" : tone === "mint" ? "var(--mint)" : "var(--accent)";
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--track)]">
      <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${percent}%`, background: color }} />
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: PropsWithChildren<{ tone?: "neutral" | "accent" | "mint" | "danger" | "blue" }>) {
  const classes = {
    neutral: "border-[var(--border)] bg-[var(--panel-2)] text-[var(--muted)]",
    accent: "border-amber-400/30 bg-amber-400/10 text-amber-500 dark:text-amber-300",
    mint: "border-mint-400/30 bg-mint-400/10 text-emerald-700 dark:text-mint-300",
    danger: "border-red-400/30 bg-red-400/10 text-red-600 dark:text-red-300",
    blue: "border-sky-400/30 bg-sky-400/10 text-sky-700 dark:text-sky-300",
  }[tone];
  return <span className={clsx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium", classes)}>{children}</span>;
}

export function EmptyState({ icon, title, text }: { icon?: ReactNode; title: string; text: string }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] px-6 py-10 text-center">
      {icon && <div className="mb-3 text-[var(--muted)]">{icon}</div>}
      <div className="font-medium text-[var(--text)]">{title}</div>
      <p className="mt-1 max-w-md text-sm text-[var(--muted)]">{text}</p>
    </div>
  );
}

export function ErrorBox({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-700 dark:text-red-200">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" />
      <div className="flex-1">{message}</div>
      {onClose && (
        <button className="rounded p-1 hover:bg-red-400/10" onClick={onClose} aria-label="Закрыть">
          <X size={16} />
        </button>
      )}
    </div>
  );
}
