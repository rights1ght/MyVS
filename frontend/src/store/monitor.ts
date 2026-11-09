import { create } from "zustand";
import type { Snapshot } from "../api/types";

interface MonitorState {
  snapshot: Snapshot | null;
  connected: boolean;
  everConnected: boolean;
  setSnapshot: (snapshot: Snapshot) => void;
  setConnected: (connected: boolean) => void;
}

export const useMonitorStore = create<MonitorState>((set) => ({
  snapshot: null,
  connected: false,
  everConnected: false,
  setSnapshot: (snapshot) => set({ snapshot }),
  setConnected: (connected) =>
    set((state) => ({ connected, everConnected: state.everConnected || connected })),
}));

interface ThemeState {
  theme: "dark" | "light";
  toggle: () => void;
  setTheme: (theme: "dark" | "light") => void;
}

const storedTheme = (): "dark" | "light" => {
  const value = localStorage.getItem("myvs-theme");
  if (value === "light" || value === "dark") return value;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
};

export const useThemeStore = create<ThemeState>((set) => {
  const theme = typeof window === "undefined" ? "dark" : storedTheme();
  return {
    theme,
    setTheme: (next) => {
      localStorage.setItem("myvs-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      document.documentElement.classList.toggle("light", next === "light");
      set({ theme: next });
    },
    toggle: () =>
      set((state) => {
        const next = state.theme === "dark" ? "light" : "dark";
        localStorage.setItem("myvs-theme", next);
        document.documentElement.classList.toggle("dark", next === "dark");
        document.documentElement.classList.toggle("light", next === "light");
        return { theme: next };
      }),
  };
});
