import clsx from "clsx";
import { AudioLines, CheckCircle2, Mic, Plus, ShieldCheck, Sparkles, Square, Trash2, UploadCloud, Waves } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ModelInfo, VoiceInfo } from "../api/types";
import { Modal } from "../components/Modal";
import { Badge, EmptyState, ErrorBox, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

interface Analysis {
  ok: boolean;
  score: number;
  duration_sec: number;
  snr_db?: number;
  clipping_ratio?: number;
  issues: string[];
  warnings: string[];
  recommendation: string;
}

function VoiceCard({ voice, onDelete }: { voice: VoiceInfo; onDelete: () => void }) {
  const [playing, setPlaying] = useState(false);
  return (
    <Panel className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3">
          <div className={clsx("flex h-10 w-10 items-center justify-center rounded-xl", voice.kind === "cloned" ? "bg-mint-400/10 text-mint-400" : voice.kind === "designed" ? "bg-violet-400/10 text-violet-400" : "bg-[var(--accent-soft)] text-[var(--accent)]")}><Waves size={18} /></div>
          <div>
            <div className="text-sm font-medium">{voice.name}</div>
            <div className="mt-0.5 text-[10px] text-[var(--muted)]">{voice.model_name || voice.model_id} · {voice.language.toUpperCase()} {voice.gender ? `· ${voice.gender}` : ""}</div>
          </div>
        </div>
        <Badge tone={voice.kind === "builtin" ? "neutral" : voice.kind === "designed" ? "accent" : "mint"}>{voice.kind}</Badge>
      </div>
      {voice.kind === "cloned" && (
        <div className="mt-3 flex items-center gap-2 text-[11px] text-[var(--muted)]"><ShieldCheck size={13} className="text-mint-400" /> consent зафиксирован · {voice.duration_sec.toFixed(1)}s</div>
      )}
      {voice.quality_score !== null && (
        <div className="mt-2 flex items-center gap-2 text-[11px]"><span className="text-[var(--muted)]">Качество</span><span className="font-semibold">{voice.quality_score}/100</span>{voice.quality_json?.snr_db !== undefined && <span className="text-[var(--muted)]">SNR {Number(voice.quality_json.snr_db).toFixed(0)} dB</span>}</div>
      )}
      {voice.kind === "designed" && <p className="mt-2 line-clamp-2 text-[11px] leading-4 text-[var(--muted)]">{voice.description}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Link to={`/tts?voice=${voice.id}`} className="btn-primary px-3 py-1.5 text-xs"><AudioLines size={13} /> Озвучить</Link>
        {voice.has_reference && <button className="btn px-3 py-1.5 text-xs" onClick={() => setPlaying((value) => !value)}>{playing ? "Скрыть" : "Референс"}</button>}
        {voice.kind !== "builtin" && <button className="btn-ghost px-2 py-1.5 text-xs" onClick={onDelete}><Trash2 size={13} /></button>}
      </div>
      {playing && voice.has_reference && <audio controls autoPlay src={`/api/voices/${voice.id}/reference`} className="mt-3 w-full" />}
    </Panel>
  );
}

export function VoicesPage() {
  const voices = useAsync(() => api<VoiceInfo[]>("/api/voices"), []);
  const models = useAsync(() => api<ModelInfo[]>("/api/models?category=clone"), []);
  const [tab, setTab] = useState("all");
  const [cloneOpen, setCloneOpen] = useState(false);
  const [designOpen, setDesignOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [recording, setRecording] = useState(false);
  const [clone, setClone] = useState({ name: "", language: "ru", model_id: "", consent: false, reference_text: "", test_text: "Привет! Это тест клонированного голоса." });
  const [design, setDesign] = useState({ name: "", description: "", language: "ru", model_id: "", test_text: "Привет! Это голос, созданный по описанию." });
  const [busy, setBusy] = useState(false);
  const [createdTask, setCreatedTask] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const cloneModels = (models.data ?? []).filter((model) => model.installed && model.capabilities.includes("clone"));
  const designModels = (models.data ?? []).filter((model) => model.installed && model.capabilities.includes("voice_design"));

  useEffect(() => {
    if (!clone.model_id && cloneModels.length) setClone((value) => ({ ...value, model_id: cloneModels[0].id }));
    if (!design.model_id && designModels.length) setDesign((value) => ({ ...value, model_id: designModels[0].id }));
  }, [cloneModels.length, designModels.length]);

  useEffect(() => {
    if (!file) { setAudioUrl(""); setAnalysis(null); return; }
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    setAnalyzing(true);
    const form = new FormData();
    form.append("file", file);
    api<Analysis>("/api/voices/analyze", { method: "POST", body: form })
      .then(setAnalysis)
      .catch((err: Error) => setError(err.message))
      .finally(() => setAnalyzing(false));
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const list = (voices.data ?? []).filter((voice) => tab === "all" || voice.kind === tab);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setFile(new File([blob], "clone-reference.webm", { type: "audio/webm" }));
        stream.getTracks().forEach((track) => track.stop());
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (err) {
      setError(`Микрофон недоступен: ${(err as Error).message}`);
    }
  };
  const stopRecording = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  };

  const submitClone = async () => {
    if (!file || !clone.model_id || !clone.consent) {
      setError("Нужны референс, модель и подтверждение прав.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", clone.name || "Клонированный голос");
      form.append("language", clone.language);
      form.append("model_id", clone.model_id);
      form.append("consent", String(clone.consent));
      form.append("reference_text", clone.reference_text);
      form.append("test_text", clone.test_text);
      const result = await api<{ voice: VoiceInfo; task_id: string | null }>("/api/voices/clone", { method: "POST", body: form });
      setCloneOpen(false);
      setFile(null);
      setCreatedTask(result.task_id);
      voices.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitDesign = async () => {
    if (!design.model_id || !design.description.trim()) {
      setError("Выберите модель и опишите голос.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ voice: VoiceInfo; task_id: string | null }>("/api/voices/design", { method: "POST", body: JSON.stringify(design) });
      setDesignOpen(false);
      setCreatedTask(result.task_id);
      voices.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Voice library"
        title="Голоса"
        description="Встроенные голоса, клонирование по референсу 5–30 секунд и создание голоса по текстовому описанию."
        actions={<><button className="btn" onClick={() => setDesignOpen(true)}><Sparkles size={15} /> По описанию</button><button className="btn-primary" onClick={() => setCloneOpen(true)}><Plus size={16} /> Клонировать</button></>}
      />

      {error && <ErrorBox message={error} onClose={() => setError(null)} />}
      {createdTask && <Panel className="p-4 text-xs text-[var(--muted)]">Создан тестовый синтез: <Link to={`/tts`} className="text-[var(--accent)]">откройте TTS</Link> или задачу <span className="font-mono">{createdTask.slice(0, 8)}</span> в истории.</Panel>}

      <div className="flex flex-wrap items-center gap-2">
        {[["all", "Все"], ["builtin", "Встроенные"], ["cloned", "Клонированные"], ["designed", "По описанию"]].map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)} className={clsx("rounded-xl px-3 py-2 text-xs font-medium", tab === id ? "bg-[var(--accent-soft)] text-[var(--accent-strong)]" : "text-[var(--muted)] hover:bg-[var(--hover)]")}>{label}</button>
        ))}
        <Badge tone="mint"><CheckCircle2 size={10} /> consent обязателен</Badge>
      </div>

      {(models.data ?? []).length === 0 && <Panel className="p-4 text-sm text-[var(--muted)]">Клонирование станет доступно после установки модели Chatterbox, Qwen3-TTS, OmniVoice или VoxCPM2. <Link className="text-[var(--accent)]" to="/models">Менеджер моделей →</Link></Panel>}

      {list.length === 0 ? <EmptyState icon={<Sparkles size={24} />} title="Голосов пока нет" text="Скачайте TTS-модель или создайте клонированный голос." /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((voice) => <VoiceCard key={voice.id} voice={voice} onDelete={async () => { if (!confirm(`Удалить голос «${voice.name}»?`)) return; try { await api(`/api/voices/${voice.id}`, { method: "DELETE" }); voices.reload(); } catch (err) { setError((err as Error).message); } }} />)}
        </div>
      )}

      <Modal open={cloneOpen} onClose={() => setCloneOpen(false)} title="Клонировать голос" subtitle="Референс 5–30 с, чистая речь, обязательное подтверждение прав." wide footer={<><button className="btn" onClick={() => setCloneOpen(false)}>Отмена</button><button className="btn-primary" disabled={busy || !clone.consent || !file || !clone.model_id} onClick={submitClone}>{busy ? "Сохраняем…" : "Сохранить и проверить"}</button></>}>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-[var(--muted)]">Имя голоса<input className="input mt-1" value={clone.name} onChange={(event) => setClone({ ...clone, name: event.target.value })} placeholder="Например, Мой голос" /></label>
            <label className="text-xs text-[var(--muted)]">Язык<select className="select mt-1" value={clone.language} onChange={(event) => setClone({ ...clone, language: event.target.value })}><option value="ru">Русский</option><option value="en">English</option><option value="de">Deutsch</option><option value="fr">Français</option><option value="es">Español</option></select></label>
            <label className="text-xs text-[var(--muted)] sm:col-span-2">Модель клонирования<select className="select mt-1" value={clone.model_id} onChange={(event) => setClone({ ...clone, model_id: event.target.value })}><option value="">Выберите</option>{cloneModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
          </div>
          <div className="rounded-xl border border-dashed border-[var(--border)] p-4">
            <div className="flex flex-wrap items-center gap-3">
              <label className="btn cursor-pointer"><UploadCloud size={15} /> Загрузить 5–30 с<input type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm" className="hidden" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
              {recording ? <button className="btn border-red-400/30 text-red-500" onClick={stopRecording}><Square size={14} /> Остановить</button> : <button className="btn" onClick={startRecording}><Mic size={15} /> Записать</button>}
              {file && <span className="text-xs text-[var(--muted)]">{file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB</span>}
            </div>
            {audioUrl && <audio controls src={audioUrl} className="mt-3 w-full" />}
          </div>
          {analyzing && <div className="text-xs text-[var(--muted)]">Проверяем длительность, шум и клиппинг…</div>}
          {analysis && (
            <div className={clsx("rounded-xl border p-4", analysis.ok ? "border-mint-400/30 bg-mint-400/5" : "border-red-400/30 bg-red-400/5")}>
              <div className="flex items-center justify-between"><div className="text-sm font-medium">Качество: {analysis.score}/100</div><Badge tone={analysis.ok ? "mint" : "danger"}>{analysis.ok ? "подходит" : "не подходит"}</Badge></div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-[var(--muted)]"><span>{analysis.duration_sec.toFixed(1)} s</span><span>SNR {analysis.snr_db?.toFixed(0) ?? "—"} dB</span><span>клиппинг {((analysis.clipping_ratio ?? 0) * 100).toFixed(2)}%</span></div>
              {(analysis.issues.length > 0 || analysis.warnings.length > 0) && <ul className="mt-2 space-y-1 text-[11px] leading-4">{analysis.issues.map((issue) => <li key={issue} className="text-red-600 dark:text-red-300">• {issue}</li>)}{analysis.warnings.map((warning) => <li key={warning} className="text-amber-600 dark:text-amber-300">• {warning}</li>)}</ul>}
            </div>
          )}
          <label className="text-xs text-[var(--muted)]">Транскрипт референса (опционально, повышает качество)<textarea className="input mt-1 min-h-[60px]" value={clone.reference_text} onChange={(event) => setClone({ ...clone, reference_text: event.target.value })} placeholder="Что произнесено в референсе" /></label>
          <label className="text-xs text-[var(--muted)]">Тестовая фраза<input className="input mt-1" value={clone.test_text} onChange={(event) => setClone({ ...clone, test_text: event.target.value })} /></label>
          <label className="flex items-start gap-2 rounded-xl border border-amber-400/30 bg-amber-400/5 p-3 text-xs leading-5 text-amber-700 dark:text-amber-300"><input type="checkbox" className="mt-1" checked={clone.consent} onChange={(event) => setClone({ ...clone, consent: event.target.checked })} /> У меня есть право использовать этот голос. Я не буду выдавать синтез за реального человека и использовать его для обмана.</label>
        </div>
      </Modal>

      <Modal open={designOpen} onClose={() => setDesignOpen(false)} title="Создать голос по описанию" subtitle="Доступно для Qwen3-TTS VoiceDesign, OmniVoice и VoxCPM2." footer={<><button className="btn" onClick={() => setDesignOpen(false)}>Отмена</button><button className="btn-primary" disabled={busy} onClick={submitDesign}>{busy ? "Создаём…" : "Создать и проверить"}</button></>}>
        <div className="space-y-3">
          <label className="text-xs text-[var(--muted)]">Имя<input className="input mt-1" value={design.name} onChange={(event) => setDesign({ ...design, name: event.target.value })} /></label>
          <label className="text-xs text-[var(--muted)]">Модель<select className="select mt-1" value={design.model_id} onChange={(event) => setDesign({ ...design, model_id: event.target.value })}><option value="">Выберите</option>{designModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
          <label className="text-xs text-[var(--muted)]">Описание голоса<textarea className="input mt-1 min-h-[100px]" value={design.description} onChange={(event) => setDesign({ ...design, description: event.target.value })} placeholder="Тёплый женский голос 30 лет, спокойный, чуть хриплый, медленный темп" /></label>
          <label className="text-xs text-[var(--muted)]">Тестовая фраза<input className="input mt-1" value={design.test_text} onChange={(event) => setDesign({ ...design, test_text: event.target.value })} /></label>
          {designModels.length === 0 && <div className="rounded-xl border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted)]">Нет установленной модели с voice design. <Link className="text-[var(--accent)]" to="/models">Скачать →</Link></div>}
        </div>
      </Modal>
    </div>
  );
}
