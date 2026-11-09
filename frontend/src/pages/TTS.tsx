import clsx from "clsx";
import { AudioLines, Clock3, Loader2, Play, Sparkles, TriangleAlert, Volume2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ModelInfo, VoiceInfo } from "../api/types";
import { ResourceDecision } from "../components/TaskDecision";
import { TaskAudio, TaskStats, TaskTimer } from "../components/TaskPanel";
import { Badge, EmptyState, ErrorBox, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useTaskStream } from "../hooks/useTaskStream";

const KIND_LABELS: Record<string, string> = { builtin: "Встроенные", cloned: "Клонированные", designed: "По описанию" };

export function TTSPage() {
  const [params] = useSearchParams();
  const voices = useAsync(() => api<VoiceInfo[]>("/api/voices"), []);
  const models = useAsync(() => api<ModelInfo[]>("/api/models?category=tts"), []);
  const cloneModels = useAsync(() => api<ModelInfo[]>("/api/models?category=clone"), []);
  const projects = useAsync(() => api<{ id: string; name: string }[]>("/api/projects"), []);
  const allVoices = voices.data ?? [];
  const [projectId, setProjectId] = useState("");
  const [text, setText] = useState("Привет! Это локальный синтез речи. Голос остаётся на этой машине.");
  const [voiceId, setVoiceId] = useState(params.get("voice") ?? "");
  const [modelId, setModelId] = useState("");
  const [variantId, setVariantId] = useState("");
  const [kind, setKind] = useState("builtin");
  const [language, setLanguage] = useState("ru");
  const [speed, setSpeed] = useState(1);
  const [pitch, setPitch] = useState(0);
  const [volume, setVolume] = useState(1);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { task, error: streamError, refresh } = useTaskStream(taskId);

  const availableModels = [...(models.data ?? []), ...(cloneModels.data ?? [])]
    .filter((item) => item.category === "tts" || item.category === "clone");
  const filtered = useMemo(() => allVoices.filter((voice) => {
    if (modelId && voice.model_id !== modelId) return false;
    if (kind && voice.kind !== kind) return false;
    if (language && voice.language !== language) return false;
    return true;
  }), [allVoices, modelId, kind, language]);
  const selected = allVoices.find((voice) => voice.id === voiceId && filtered.some((item) => item.id === voice.id)) ?? filtered[0] ?? null;
  const activeModelId = modelId || selected?.model_id || "";
  const model = availableModels.find((item) => item.id === activeModelId);
  const availableVariants = model?.variants.filter((variant) => variant.install_state === "installed") ?? [];
  const selectedVariant = availableVariants.find((variant) => variant.id === variantId) ?? availableVariants[0] ?? null;
  const installed = Boolean(model?.installed && selectedVariant);
  const isCloneOnly = model?.category === "clone";

  useEffect(() => {
    if (!modelId && selected?.model_id) setModelId(selected.model_id);
  }, [modelId, selected?.model_id]);

  useEffect(() => {
    if (filtered.length && !filtered.some((voice) => voice.id === voiceId)) setVoiceId(filtered[0].id);
    if (!filtered.length && voiceId) setVoiceId("");
  }, [filtered, voiceId]);

  useEffect(() => {
    if (selectedVariant && selectedVariant.id !== variantId) setVariantId(selectedVariant.id);
  }, [selectedVariant?.id, variantId]);

  useEffect(() => {
    const queryVoice = params.get("voice");
    if (!queryVoice || !voices.data?.length) return;
    const voice = voices.data.find((item) => item.id === queryVoice);
    if (voice) {
      setVoiceId(voice.id);
      setKind(voice.kind);
      setLanguage(voice.language);
    }
  }, [voices.data, params]);

  useEffect(() => {
    if (selected && selected.language && selected.language !== language && !params.get("voice")) {
      setLanguage(selected.language);
    }
  }, [selected?.id]);

  const synthesize = async (preview = false) => {
    if (!selected || !text.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await api<{ task_id: string }>(`/api/tts/${preview ? "preview" : "synthesize"}`, {
        method: "POST",
        body: JSON.stringify({
          text: preview ? "Привет! Так звучит этот голос в локальной студии." : text,
          voice_id: selected.id,
          model_id: activeModelId,
          variant_id: selectedVariant?.id,
          language: selected.language || language,
          speed,
          pitch,
          volume,
          project_id: projectId || null,
          device: selectedVariant?.device ?? "gpu",
        }),
      });
      setTaskId(response.task_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const chunks = Math.max(1, Math.ceil(text.length / 280));

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Text to speech"
        title="Синтез речи"
        description="Текст в речь: встроенные и клонированные голоса, скорость, тон, громкость и длинные тексты по фразам."
        actions={<Link to="/voices" className="btn"><Sparkles size={15} /> Клонировать голос</Link>}
      />

      {error && <ErrorBox message={error} onClose={() => setError(null)} />}
      {streamError && <ErrorBox message={streamError} />}

      <div className="grid gap-5 xl:grid-cols-[1.25fr_.75fr]">
        <div className="space-y-4">
          <Panel className="p-5">
            <div className="mb-2 flex items-center justify-between"><label className="text-xs font-medium text-[var(--muted)]">Текст</label><span className="text-[11px] text-[var(--muted)]">{text.length} / 10000 · {chunks} чанк(ов)</span></div>
            <textarea value={text} maxLength={10000} onChange={(event) => setText(event.target.value)} className="input min-h-[230px] resize-y text-sm leading-6" placeholder="Введите текст для озвучивания…" />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className="btn-primary" disabled={!selected || !installed || !text.trim() || submitting} onClick={() => synthesize(false)}>{submitting ? <Loader2 size={16} className="animate-spin" /> : <AudioLines size={16} />} Синтезировать</button>
              <button className="btn" disabled={!selected || !installed || submitting} onClick={() => synthesize(true)}><Play size={15} /> Прослушать голос</button>
              {model && <Badge tone={installed ? "mint" : "danger"}>{model.name}</Badge>}
            </div>
            {selected?.kind === "designed" && <div className="mt-3 rounded-xl border border-violet-400/25 bg-violet-400/5 p-3 text-xs text-violet-700 dark:text-violet-300">Голос по описанию: {selected.description}</div>}
          </Panel>

          {task && (
            <div className="space-y-4">
              <TaskTimer task={task} />
              {task.status === "awaiting_decision" && <ResourceDecision task={task} onResolved={refresh} />}
              {task.status === "completed" && <TaskAudio task={task} />}
              {task.status === "completed" && <TaskStats task={task} />}
            </div>
          )}

          {!task && (
            <Panel className="p-5"><EmptyState icon={<Volume2 size={22} />} title="Здесь появится плеер" text="Выберите голос, введите текст и запустите синтез. Длинный текст автоматически режется на фразы." /></Panel>
          )}
        </div>

        <div className="space-y-4">
          <Panel className="p-4">
            <div className="mb-3 flex items-center justify-between"><div className="text-sm font-semibold">Движок и голос</div><Badge>{filtered.length}</Badge></div>
            <label className="mb-3 block text-xs text-[var(--muted)]">TTS-модель
              <select className="select mt-1" value={activeModelId} onChange={(event) => { setModelId(event.target.value); setVoiceId(""); setVariantId(""); }}>
                {availableModels.map((item) => <option key={item.id} value={item.id} disabled={!item.installed}>{item.name}{item.installed ? "" : " · не установлена"}</option>)}
              </select>
            </label>
            <label className="mb-3 block text-xs text-[var(--muted)]">Вариант / устройство
              <select className="select mt-1" value={selectedVariant?.id ?? ""} disabled={!availableVariants.length} onChange={(event) => setVariantId(event.target.value)}>
                {availableVariants.map((variant) => <option key={variant.id} value={variant.id}>{variant.label} · {variant.device.toUpperCase()} · {variant.precision}</option>)}
              </select>
            </label>
            <div className="mb-3 flex rounded-lg border border-[var(--border)] p-0.5 text-[11px]">
              {Object.entries(KIND_LABELS).map(([value, label]) => <button key={value} onClick={() => { setKind(value); setVoiceId(""); }} className={clsx("flex-1 rounded-md px-2 py-1.5", kind === value ? "bg-[var(--accent-soft)] text-[var(--accent-strong)]" : "text-[var(--muted)]")}>{label}</button>)}
            </div>
            <div className="mb-3 flex gap-2"><select className="select text-xs" value={language} onChange={(event) => setLanguage(event.target.value)}><option value="ru">Русский</option><option value="en">English</option><option value="">Все языки</option></select></div>
            <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
              {filtered.map((voice) => (
                <button key={voice.id} onClick={() => setVoiceId(voice.id)} className={clsx("w-full rounded-xl border p-3 text-left transition", voice.id === selected?.id ? "border-[var(--accent)]/60 bg-[var(--accent-soft)]" : "border-[var(--border)] bg-[var(--panel-2)] hover:border-[var(--accent)]/30")}>
                  <div className="flex items-center justify-between gap-2"><span className="text-xs font-medium">{voice.name}</span>{voice.kind === "cloned" ? <Badge tone="mint">clone</Badge> : voice.kind === "designed" ? <Badge tone="accent">design</Badge> : <Badge>{voice.gender || "voice"}</Badge>}</div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-[var(--muted)]"><span>{voice.model_name} · {voice.language.toUpperCase()}</span>{voice.quality_score !== null && <span>Q {voice.quality_score}</span>}</div>
                </button>
              ))}
              {filtered.length === 0 && <div className="rounded-xl border border-dashed border-[var(--border)] p-4 text-center text-xs text-[var(--muted)]">Нет голосов этого типа. <Link to="/voices" className="text-[var(--accent)]">Клонировать →</Link></div>}
            </div>
          </Panel>

          <Panel className="p-4">
            <div className="mb-4 text-sm font-semibold">Параметры</div>
            <label className="label">Скорость · {speed.toFixed(2)}×<input className="mt-2 w-full accent-[var(--accent)]" type="range" min={0.5} max={2} step={0.05} value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /></label>
            <label className="label mt-4">Тон · {pitch > 0 ? "+" : ""}{pitch.toFixed(1)} пт<input className="mt-2 w-full accent-[var(--accent)]" type="range" min={-6} max={6} step={0.5} value={pitch} onChange={(event) => setPitch(Number(event.target.value))} /></label>
            <label className="label mt-4">Громкость · {Math.round(volume * 100)}%<input className="mt-2 w-full accent-[var(--accent)]" type="range" min={0} max={1.5} step={0.05} value={volume} onChange={(event) => setVolume(Number(event.target.value))} /></label>
            <label className="text-xs text-[var(--muted)] mt-4 block">Проект<select className="select mt-1" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Без проекта</option>{(projects.data ?? []).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <p className="mt-3 text-[10px] leading-4 text-[var(--muted)]">Тон и громкость применяются после синтеза; качество зависит от модели.</p>
          </Panel>

          {(model?.watermark || model?.commercial === false) && (
            <Panel className="border-amber-400/25 bg-amber-400/5 p-4 text-xs text-amber-700 dark:text-amber-300">
              <div className="flex items-center gap-2 font-medium"><TriangleAlert size={14} /> Ограничения модели</div>
              {model?.watermark && <p className="mt-2 leading-5">Все файлы Chatterbox содержат PerTh watermark. Приложение не удаляет его.</p>}
              {model?.commercial === false && <p className="mt-2 leading-5">Лицензия не разрешает коммерческое использование.</p>}
            </Panel>
          )}

          <Panel className="p-4 text-[11px] leading-5 text-[var(--muted)]">
            <div className="mb-2 flex items-center gap-2 text-[var(--text)]"><Clock3 size={14} /> Как считается RTF</div>
            RTF = время инференса / длительность аудио. Итог и пики ресурсов сохраняются в истории задачи.
          </Panel>
        </div>
      </div>
    </div>
  );
}
