import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useMonitorSocket } from "./hooks/useMonitorSocket";
import { HistoryPage } from "./pages/History";
import { ModelsPage } from "./pages/Models";
import { MonitorPage } from "./pages/Monitor";
import { OverviewPage } from "./pages/Overview";
import { ProjectsPage } from "./pages/Projects";
import { QueuePage } from "./pages/Queue";
import { SettingsPage } from "./pages/Settings";
import { STTPage } from "./pages/STT";
import { SystemPage } from "./pages/System";
import { TTSPage } from "./pages/TTS";
import { VoicesPage } from "./pages/Voices";

function App() {
  useMonitorSocket();
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="stt" element={<STTPage />} />
          <Route path="tts" element={<TTSPage />} />
          <Route path="voices" element={<VoicesPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="queue" element={<QueuePage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="monitor" element={<MonitorPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="system" element={<SystemPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
