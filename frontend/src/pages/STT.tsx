import clsx from "clsx";
import { Check, Clipboard, Download, FileAudio, Loader2, Mic, Square, UploadCloud, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ModelInfo, TaskInfo } from "../api/types";
import { ResourceDecision } from "../components/TaskDecision";
import { TaskStats, TaskTimer } from "../components/TaskPanel";
import { Badge, EmptyState, ErrorBox, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useTaskStream } from "../hooks/useTaskStream";

const LANGUAGES = [
  ["auto", "Авто"], ["ru", "Русский"], ["en", "English"], ["de", "Deutsch"], ["fr", "Français"], ["es", "Español"], ["it", "Italiano"], ["pl", "Polski"], ["uk", "Українська"], ["tr", "Türkçe"], ["zh", "中文"], ["ja", "日本語"], ["ko", "한국어"],
];

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

export function STTPage() {
  const models = useAsync(() => api<ModelInfo[]>("/api/models?category=stt"), []);
  const projects = useAsync(() => api<{ id: string; name: string }[]>("/api/projects"), []);
  const installedModels = useMemo(() => (models.data ?? []).filter((model) => model.installed), [models.data]);
  const [projectId, setProjectId] = useState("");
  const [modelId, setModelId] = useState("");
  const [language, setLanguage] = useState("auto");
  const [beam, setBeam] = useState(5);
  const [vad, setVad] = useState(true);
  const [words, setWords] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string>("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [copied, setCopied] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | undefined>(undefined);
  const { task, error, refresh } = useTaskStream(taskId);

  useEffect(() => {
    if (!modelId && installedModels.length) setModelId(installedModels[0].id);
  }, [installedModels, modelId]);

  useEffect(() => {
    if (!file) {
      setAudioUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => () => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  const selectFile = (next: File | null) => {
    setFile(next);
    setTaskId(null);
    setSubmitError(null);
  };

  const startRecording = async () => {
    setSubmitError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const recorded = new File([blob], "recording.webm", { type: "audio/webm" });
        selectFile(recorded);
        stream.getTracks().forEach((track) => track.stop());
      };
      recorderRef.current = recorder;
      setRecording(true);
      setRecordSeconds(0);
      timerRef.current = window.setInterval(() => setRecordSeconds((value) => value + 1), 1000);
      recorder.start();
    } catch (err) {
      setSubmitError(`Микрофон недоступен: ${(err as Error).message}`);
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
  };

  const submit = async () => {
    if (!file || !modelId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("model_id", modelId);
      form.append("language", language);
      form.append("beam_size", String(beam));
      form.append("vad", String(vad));
      form.append("word_timestamps", String(words));
      form.append("project_id", projectId);
      const response = await api<{ task_id: string }>("/api/stt/transcribe", { method: "POST", body: form });
      setTaskId(response.task_id);
    } catch (err) {
      setSubmitError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const transcript = task?.result?.text ?? "";
  const segments = task?.result?.segments ?? [];
  const copy = async () => {
    if (!transcript) return;
    await navigator.clipboard.writeText(transcript);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Speech to text"
        title="Транскрипция"
        description="Файл или микрофон, модель и язык, таймкоды и экспорт в TXT/SRT/VTT/JSON."
        actions={<Link to="/models" className="btn">Менеджер моделей</Link>}
      />

      {submitError && <ErrorBox message={submitError} onClose={() => setSubmitError(null)} />}
      {error && <ErrorBox message={error} />}
      {!models.loading && installedModels.length === 0 && (
        <Panel className="p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold">Нет установленной STT-модели</div><p className="mt-1 text-xs text-[var(--muted)]">Скачайте Faster-Whisper tiny/base/small в менеджере моделей.</p></div><Link to="/models" className="btn-primary"><UploadCloud size={15} /> Скачать модель</Link></div></Panel>
      )}

      <div className="grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
        <Panel className="p-5">
          <div
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); const next = event.dataTransfer.files[0]; if (next) selectFile(next); }}
            className={clsx("relative flex min-h-[210px] flex-col items-center justify-center rounded-2xl border border-dashed p-6 text-center transition", file ? "border-mint-400/40 bg-mint-400/5" : "border-[var(--border)] bg-[var(--panel-2)] hover:border-[var(--accent)]/40")}
          >
            {file ? (
              <>
                <FileAudio size={34} className="text-mint-400" />
                <div className="mt-3 max-w-full truncate text-sm font-medium">{file.name}</div>
                <div className="mt-1 text-xs text-[var(--muted)]">{(file.size / 1024 / 1024).toFixed(1)} MB · {file.type || "audio"}</div>
                {audioUrl && <audio controls src={audioUrl} className="mt-4 w-full max-w-md" />}
                <button className="absolute right-3 top-3 rounded-lg p-1.5 text-[var(--muted)] hover:bg-[var(--hover)]" onClick={() => selectFile(null)}><X size={16} /></button>
              </>
            ) : (
              <>
                <UploadCloud size={34} className="text-[var(--muted)]" />
                <div className="mt-3 text-sm font-medium">Перетащите аудио или выберите файл</div>
                <div className="mt-1 text-xs text-[var(--muted)]">wav, mp3, m4a, ogg · до 2 GB</div>
                <label className="btn mt-4 cursor-pointer"><UploadCloud size={15} /> Выбрать файл<input type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg" className="hidden" onChange={(event) => selectFile(event.target.files?.[0] ?? null)} /></label>
              </>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            {recording ? (
              <button className="btn border-red-400/30 text-red-500" onClick={stopRecording}><Square size={14} /> Остановить · {formatTime(recordSeconds)}</button>
            ) : (
              <button className="btn" onClick={startRecording}><Mic size={15} /> Записать с микрофона</button>
            )}
            <span className="text-[11px] text-[var(--muted)]">Запись конвертируется на сервере в 16 kHz mono.</span>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-[var(--muted)]">Модель<select className="select mt-1" value={modelId} onChange={(event) => setModelId(event.target.value)}>{installedModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
            <label className="text-xs text-[var(--muted)]">Язык<select className="select mt-1" value={language} onChange={(event) => setLanguage(event.target.value)}>{LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
            <label className="text-xs text-[var(--muted)]">Проект<select className="select mt-1" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Без проекта</option>{(projects.data ?? []).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <label className="text-xs text-[var(--muted)]">Beam size<input type="number" min={1} max={10} className="input mt-1" value={beam} onChange={(event) => setBeam(Number(event.target.value))} /></label>
            <div className="flex items-end gap-4 pb-1 text-xs text-[var(--muted)]">
              <label className="flex items-center gap-2"><input type="checkbox" checked={vad} onChange={(event) => setVad(event.target.checked)} /> VAD</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={words} onChange={(event) => setWords(event.target.checked)} /> слова</label>
            </div>
          </div>

          <button className="btn-primary mt-5 w-full" disabled={!file || !modelId || submitting} onClick={submit}>{submitting ? <Loader2 size={16} className="animate-spin" /> : <Mic size={16} />} Транскрибировать</button>
        </Panel>

        <div className="space-y-4">
          {task ? (
            <>
              <TaskTimer task={task} />
              {task.status === "awaiting_decision" && <ResourceDecision task={task} onResolved={refresh} />}
              {task.status === "completed" && <TaskStats task={task} />}
              {task.status === "completed" && (
                <Panel className="p-5">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold">Результат <Badge tone="mint">{task.result?.language ?? task.language}</Badge></div>
                    <button className="btn px-2.5 py-1.5" onClick={copy}>{copied ? <Check size={14} /> : <Clipboard size={14} />} {copied ? "Скопировано" : "Копировать"}</button>
                  </div>
                  <textarea className="input min-h-[150px] resize-y font-mono text-xs leading-5" readOnly value={transcript} />
                  <div className="mt-3 flex flex-wrap gap-2">
                    {["txt", "srt", "vtt", "json"].map((format) => (
                      <a key={format} className="btn px-2.5 py-1.5 text-xs" href={`/api/tasks/${task.id}/export?format=${format}`}><Download size={13} /> {format.toUpperCase()}</a>
                    ))}
                  </div>
                </Panel>
              )}
            </>
          ) : (
            <Panel className="p-5">
              <EmptyState icon={<Mic size={22} />} title="Результат появится здесь" text="После запуска вы увидите живой таймер, сегменты с таймкодами и экспорт." />
            </Panel>
          )}
        </div>
      </div>

      {task?.status === "completed" && segments.length > 0 && (
        <Panel className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3"><div className="text-sm font-semibold">Сегменты</div><span className="text-xs text-[var(--muted)]">{segments.length} · {task.result?.audio_duration_sec?.toFixed(1)}s</span></div>
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[var(--panel-2)] text-[10px] uppercase tracking-wider text-[var(--muted)]"><tr><th className="px-4 py-2">Начало</th><th className="px-4 py-2">Конец</th><th className="px-4 py-2">Текст</th></tr></thead>
              <tbody>{segments.map((segment, index) => <tr key={`${segment.start}-${index}`} className="border-t border-[var(--border)] align-top"><td className="whitespace-nowrap px-4 py-2.5 font-mono text-[var(--muted)]">{segment.start.toFixed(2)}s</td><td className="whitespace-nowrap px-4 py-2.5 font-mono text-[var(--muted)]">{segment.end.toFixed(2)}s</td><td className="px-4 py-2.5 leading-5">{segment.text}</td></tr>)}</tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
