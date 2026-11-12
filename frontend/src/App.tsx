import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useMonitorSocket } from "./hooks/useMonitorSocket";
import { OverviewPage } from "./pages/Overview";

// Only the landing page is in the main bundle; every other page is fetched on first visit.
const HistoryPage = lazy(() => import("./pages/History").then((m) => ({ default: m.HistoryPage })));
const ModelsPage = lazy(() => import("./pages/Models").then((m) => ({ default: m.ModelsPage })));
const MonitorPage = lazy(() => import("./pages/Monitor").then((m) => ({ default: m.MonitorPage })));
const ProjectsPage = lazy(() => import("./pages/Projects").then((m) => ({ default: m.ProjectsPage })));
const QueuePage = lazy(() => import("./pages/Queue").then((m) => ({ default: m.QueuePage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));
const STTPage = lazy(() => import("./pages/STT").then((m) => ({ default: m.STTPage })));
const SystemPage = lazy(() => import("./pages/System").then((m) => ({ default: m.SystemPage })));
const TTSPage = lazy(() => import("./pages/TTS").then((m) => ({ default: m.TTSPage })));
const VoicesPage = lazy(() => import("./pages/Voices").then((m) => ({ default: m.VoicesPage })));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="p-8 text-sm text-[var(--muted)]">Загрузка…</div>}>{children}</Suspense>;
}

function App() {
  useMonitorSocket();
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="projects" element={<Lazy><ProjectsPage /></Lazy>} />
          <Route path="stt" element={<Lazy><STTPage /></Lazy>} />
          <Route path="tts" element={<Lazy><TTSPage /></Lazy>} />
          <Route path="voices" element={<Lazy><VoicesPage /></Lazy>} />
          <Route path="models" element={<Lazy><ModelsPage /></Lazy>} />
          <Route path="queue" element={<Lazy><QueuePage /></Lazy>} />
          <Route path="history" element={<Lazy><HistoryPage /></Lazy>} />
          <Route path="monitor" element={<Lazy><MonitorPage /></Lazy>} />
          <Route path="settings" element={<Lazy><SettingsPage /></Lazy>} />
          <Route path="system" element={<Lazy><SystemPage /></Lazy>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
