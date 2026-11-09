import clsx from "clsx";
import {
  Activity,
  AudioLines,
  Bell,
  Boxes,
  FolderKanban,
  Gauge,
  History,
  ListOrdered,
  Mic2,
  Moon,
  Settings,
  Sparkles,
  Sun,
  Waves,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useMonitorStore, useThemeStore } from "../store/monitor";
import { MonitorStrip } from "./MonitorStrip";
import { ShutdownButton } from "./ShutdownButton";

const workNav = [
  { to: "/", label: "Обзор", icon: Gauge, end: true },
  { to: "/projects", label: "Проекты", icon: FolderKanban },
  { to: "/stt", label: "STT", icon: Mic2 },
  { to: "/tts", label: "TTS", icon: AudioLines },
  { to: "/voices", label: "Голоса", icon: Sparkles },
];

const systemNav = [
  { to: "/models", label: "Модели", icon: Boxes },
  { to: "/queue", label: "Очередь", icon: ListOrdered },
  { to: "/history", label: "История", icon: History },
  { to: "/monitor", label: "Мониторинг", icon: Activity },
  { to: "/settings", label: "Настройки", icon: Settings },
  { to: "/system", label: "О системе", icon: Waves },
];

function NavItem({ item }: { item: (typeof workNav)[number] }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        clsx(
          "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition",
          isActive
            ? "bg-[var(--accent-soft)] font-medium text-[var(--accent-strong)]"
            : "text-[var(--muted)] hover:bg-[var(--hover)] hover:text-[var(--text)]",
        )
      }
    >
      <Icon size={17} className="shrink-0" />
      <span>{item.label}</span>
    </NavLink>
  );
}

export function Layout() {
  const theme = useThemeStore((state) => state.theme);
  const toggle = useThemeStore((state) => state.toggle);
  const alerts = useMonitorStore((state) => state.snapshot?.alerts ?? []);
  const connected = useMonitorStore((state) => state.connected);
  const unacked = alerts.filter((alert) => !alert.acknowledged).length;

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="pointer-events-none fixed inset-x-0 top-0 h-80 bg-[radial-gradient(70%_100%_at_50%_0%,var(--glow),transparent)]" />
      <div className="relative flex min-h-screen">
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-[238px] flex-col border-r border-[var(--border)] bg-[var(--sidebar)] px-3.5 py-5 backdrop-blur-xl lg:flex">
          <NavLink to="/" className="mb-7 flex items-center gap-3 px-2">
            <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent)] text-[#1a1205] shadow-[0_8px_24px_var(--accent-glow)]">
              <AudioLines size={20} strokeWidth={2.4} />
            </div>
            <div>
              <div className="text-[15px] font-semibold tracking-tight">MyVS</div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">local voice studio</div>
            </div>
          </NavLink>

          <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Работа</div>
          <nav className="space-y-0.5">
            {workNav.map((item) => (
              <NavItem key={item.to} item={item} />
            ))}
          </nav>

          <div className="mb-1 mt-6 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Система</div>
          <nav className="space-y-0.5">
            {systemNav.map((item) => (
              <NavItem key={item.to} item={item} />
            ))}
          </nav>

          <div className="mt-auto pt-5">
            <MonitorStrip compact />
            <div className="mt-3 flex items-center justify-between px-1 text-[10px] text-[var(--muted)]">
              <span className="flex items-center gap-1.5">
                <span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "bg-mint-400" : "bg-red-400")} />
                {connected ? "live" : "reconnect…"}
              </span>
              <span>v0.1.0</span>
            </div>
          </div>
        </aside>

        <div className="min-w-0 flex-1 lg:pl-[238px]">
          <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--header)] backdrop-blur-xl">
            <div className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
              <div className="flex min-w-0 items-center gap-3">
                <NavLink to="/" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-[#1a1205] lg:hidden">
                  <AudioLines size={18} />
                </NavLink>
                <button className="hidden items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--panel)] px-3 py-1.5 text-xs text-[var(--muted)] transition hover:text-[var(--text)] sm:flex">
                  <FolderKanban size={14} />
                  Без проекта
                  <span className="text-[var(--muted)]">▾</span>
                </button>
                <div className="hidden h-5 w-px bg-[var(--border)] sm:block" />
                <span className="hidden text-xs text-[var(--muted)] md:block">всё локально · без внешних API</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="mr-1 hidden items-center gap-2 rounded-full border border-mint-400/25 bg-mint-400/5 px-3 py-1.5 text-[11px] text-emerald-700 dark:text-mint-300 sm:flex">
                  <span className="h-1.5 w-1.5 rounded-full bg-mint-400" />
                  Параллельный режим
                </div>
                <NavLink to="/monitor" className="relative rounded-xl p-2 text-[var(--muted)] transition hover:bg-[var(--hover)] hover:text-[var(--text)]" title="Предупреждения">
                  <Bell size={18} />
                  {unacked > 0 && (
                    <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white">
                      {unacked}
                    </span>
                  )}
                </NavLink>
                <button
                  onClick={toggle}
                  className="rounded-xl p-2 text-[var(--muted)] transition hover:bg-[var(--hover)] hover:text-[var(--text)]"
                  title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
                >
                  {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
                </button>
                <ShutdownButton />
                <div className="ml-1 flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--panel-2)] text-[11px] font-semibold text-[var(--muted)]">
                  VS
                </div>
              </div>
            </div>
          </header>

          <div className="flex gap-1 overflow-x-auto border-b border-[var(--border)] bg-[var(--header)] px-3 py-2 backdrop-blur-xl lg:hidden">
            {[...workNav, ...systemNav].map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={"end" in item ? Boolean(item.end) : false}
                  className={({ isActive }) => clsx("flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px]", isActive ? "bg-[var(--accent-soft)] text-[var(--accent-strong)]" : "text-[var(--muted)]")}
                >
                  <Icon size={14} /> {item.label}
                </NavLink>
              );
            })}
          </div>

          <main className="mx-auto w-full max-w-[1440px] px-4 py-7 sm:px-6 lg:px-8 lg:py-9">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
