import clsx from "clsx";
import { Gauge, Plus, RefreshCw, Save, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ModelInfo, SettingsPayload } from "../api/types";
import { Badge, ErrorBox, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

interface ResourceStatus {
  mode: string;
  policy: string;
  reserve_vram_gb: number;
  reserve_ram_gb: number;
  idle_unload_seconds: number;
  memory: Record<string, number | boolean>;
  loaded: { model_id: string; model_name: string; device: string; vram_mb: number }[];
}

interface Preset {
  stt: string;
  tts: string;
  tts_device: string;
  need_vram_gb: number;
  free_vram_gb: number;
  verdict: string;
}

export function SettingsPage() {
  const settings = useAsync(() => api<SettingsPayload>("/api/settings"), []);
  const resources = useAsync(() => api<ResourceStatus>("/api/resources/status"), []);
  const presets = useAsync(() => api<Preset[]>("/api/resources/presets"), []);
  const models = useAsync(() => api<ModelInfo[]>("/api/models"), []);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [profile, setProfile] = useState({ name: "", model_id: "", beam: 5, temperature: 0, vad: true, batch: 1, precision: "int8" });

  useEffect(() => {
    if (settings.data) setValues(settings.data.values);
  }, [settings.data]);

  const save = async () => {
    setError(null);
    try {
      const result = await api<SettingsPayload>("/api/settings", { method: "PUT", body: JSON.stringify(values) });
      setValues(result.values);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1800);
      resources.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const update = (key: string, value: unknown) => setValues((current) => ({ ...current, [key]: value }));
  const createProfile = async () => {
    if (!profile.name.trim()) return;
    try {
      await api("/api/settings/profiles", {
        method: "POST",
        body: JSON.stringify({
          name: profile.name,
          model_id: profile.model_id,
          is_default: Boolean(profile.model_id),
          values: { beam_size: Number(profile.beam), temperature: Number(profile.temperature), vad: profile.vad, batch_size: Number(profile.batch), precision: profile.precision },
        }),
      });
      setProfile({ name: "", model_id: "", beam: 5, temperature: 0, vad: true, batch: 1, precision: "int8" });
      settings.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const managedModels = (models.data ?? []).filter((model) => model.installed);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Configuration" title="Настройки" description="Режимы ресурсов, резервы, параметры моделей и профили." actions={<><button className="btn" onClick={() => { settings.reload(); resources.reload(); presets.reload(); }}><RefreshCw size={15} /> Обновить</button><button className="btn-primary" onClick={save}><Save size={15} /> {saved ? "Сохранено" : "Сохранить"}</button></>} />
      {error && <ErrorBox message={error} onClose={() => setError(null)} />}

      <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
        <Panel className="p-5">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold"><SlidersHorizontal size={16} /> Ресурсы и режим</div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-xs text-[var(--muted)]">Режим<select className="select mt-1" value={String(values.resource_mode ?? "parallel")} onChange={(event) => update("resource_mode", event.target.value)}><option value="parallel">Параллельный</option><option value="economy">Экономный</option><option value="exclusive">Эксклюзивный</option></select></label>
            <label className="text-xs text-[var(--muted)]">При нехватке памяти<select className="select mt-1" value={String(values.conflict_policy ?? "ask")} onChange={(event) => update("conflict_policy", event.target.value)}><option value="ask">Спрашивать</option><option value="auto">Автоматически (LRU → CPU)</option></select></label>
            <label className="text-xs text-[var(--muted)]">Резерв VRAM, GB<input type="number" min={0.2} max={4} step={0.1} className="input mt-1" value={Number(values.reserve_vram_gb ?? 0.8)} onChange={(event) => update("reserve_vram_gb", Number(event.target.value))} /></label>
            <label className="text-xs text-[var(--muted)]">Резерв RAM, GB<input type="number" min={0} max={12} step={0.5} className="input mt-1" value={Number(values.reserve_ram_gb ?? 3)} onChange={(event) => update("reserve_ram_gb", Number(event.target.value))} /></label>
            <label className="text-xs text-[var(--muted)]">Выгружать idle через, сек<input type="number" min={0} max={7200} step={30} className="input mt-1" value={Number(values.idle_unload_seconds ?? 600)} onChange={(event) => update("idle_unload_seconds", Number(event.target.value))} /></label>
            <label className="text-xs text-[var(--muted)]">Лимит VRAM на модель, GB (0 = без лимита)<input type="number" min={0} step={0.5} className="input mt-1" value={Number(values.vram_limit_gb ?? 0)} onChange={(event) => update("vram_limit_gb", Number(event.target.value))} /></label>
            <label className="text-xs text-[var(--muted)]">Устройство по умолчанию<select className="select mt-1" value={String(values.default_device ?? "gpu")} onChange={(event) => update("default_device", event.target.value)}><option value="gpu">GPU</option><option value="cpu">CPU</option></select></label>
            <label className="text-xs text-[var(--muted)]">Точность по умолчанию<select className="select mt-1" value={String(values.default_precision ?? "int8")} onChange={(event) => update("default_precision", event.target.value)}><option value="int8">int8</option><option value="fp16">fp16</option><option value="bf16">bf16</option><option value="int4">int4</option></select></label>
            <label className="text-xs text-[var(--muted)]">STT beam size<input type="number" min={1} max={10} className="input mt-1" value={Number(values.stt_beam_size ?? 5)} onChange={(event) => update("stt_beam_size", Number(event.target.value))} /></label>
            <label className="text-xs text-[var(--muted)]">STT temperature<input type="number" min={0} max={1} step={0.1} className="input mt-1" value={Number(values.stt_temperature ?? 0)} onChange={(event) => update("stt_temperature", Number(event.target.value))} /></label>
            <label className="flex items-center gap-2 text-xs text-[var(--muted)]"><input type="checkbox" checked={Boolean(values.stt_vad ?? true)} onChange={(event) => update("stt_vad", event.target.checked)} /> VAD по умолчанию</label>
            <label className="flex items-center gap-2 text-xs text-[var(--muted)]"><input type="checkbox" checked={Boolean(values.auto_restore_exclusive ?? true)} onChange={(event) => update("auto_restore_exclusive", event.target.checked)} /> восстанавливать модели после exclusive</label>
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2 text-sm font-semibold"><Gauge size={16} /> Бюджет сейчас</div><Badge>{resources.data?.mode ?? "—"}</Badge></div>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between text-[var(--muted)]"><span>VRAM свободно</span><span className="font-semibold text-[var(--text)]">{Number(resources.data?.memory.free_vram_gb ?? 0).toFixed(2)} GB</span></div>
            <div className="flex justify-between text-[var(--muted)]"><span>RAM свободно</span><span className="font-semibold text-[var(--text)]">{Number(resources.data?.memory.free_ram_gb ?? 0).toFixed(2)} GB</span></div>
            <div className="flex justify-between text-[var(--muted)]"><span>Резерв VRAM / RAM</span><span>{resources.data?.reserve_vram_gb ?? 0.8} / {resources.data?.reserve_ram_gb ?? 3} GB</span></div>
          </div>
          <div className="mt-4 border-t border-[var(--border)] pt-3">
            <div className="mb-2 text-[10px] uppercase tracking-wider text-[var(--muted)]">Загружено</div>
            {(resources.data?.loaded ?? []).length ? resources.data?.loaded.map((item) => <div key={item.model_id} className="mb-2 flex items-center justify-between text-xs"><span>{item.model_name}</span><span className="text-[var(--muted)]">{item.device} · {(item.vram_mb / 1024).toFixed(1)} GB</span></div>) : <div className="text-xs text-[var(--muted)]">Нет загруженных моделей</div>}
          </div>
          <div className="mt-4 border-t border-[var(--border)] pt-3">
            <div className="mb-2 text-[10px] uppercase tracking-wider text-[var(--muted)]">Пресеты совместимости</div>
            <div className="space-y-2">
              {(presets.data ?? []).map((preset) => <div key={`${preset.stt}-${preset.tts}`} className="rounded-lg border border-[var(--border)] p-2 text-[11px]"><div className="flex items-center justify-between"><span>{preset.stt} + {preset.tts}</span><Badge tone={preset.verdict === "fits" ? "mint" : preset.verdict === "tight" ? "accent" : "danger"}>{preset.verdict}</Badge></div><div className="mt-1 text-[var(--muted)]">{preset.need_vram_gb} GB нужно · {preset.free_vram_gb} GB свободно</div></div>)}
            </div>
          </div>
        </Panel>
      </div>

      <Panel className="p-5">
        <div className="mb-4 flex items-center justify-between"><div className="text-sm font-semibold">Профили параметров модели</div><Badge>{settings.data?.profiles.length ?? 0}</Badge></div>
        <div className="grid gap-4 lg:grid-cols-[1fr_.9fr]">
          <div className="space-y-2">
            {(settings.data?.profiles ?? []).map((item) => <div key={item.id} className="flex items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3 text-xs"><div><div className="font-medium">{item.name}</div><div className="mt-0.5 text-[var(--muted)]">{item.model_id || "global"} {item.is_default ? "· default" : ""}</div></div><button className="btn-ghost px-2 py-1" onClick={() => api(`/api/settings/profiles/${item.id}`, { method: "DELETE" }).then(() => settings.reload())}><Trash2 size={13} /></button></div>)}
            {!(settings.data?.profiles.length) && <div className="rounded-xl border border-dashed border-[var(--border)] p-4 text-center text-xs text-[var(--muted)]">Профилей пока нет. Создайте профиль для конкретной модели.</div>}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-[var(--muted)] sm:col-span-2">Название<input className="input mt-1" value={profile.name} onChange={(event) => setProfile({ ...profile, name: event.target.value })} placeholder="Fast STT" /></label>
            <label className="text-xs text-[var(--muted)] sm:col-span-2">Модель<select className="select mt-1" value={profile.model_id} onChange={(event) => setProfile({ ...profile, model_id: event.target.value })}><option value="">Глобальный</option>{managedModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
            <label className="text-xs text-[var(--muted)]">beam<input className="input mt-1" type="number" value={profile.beam} onChange={(event) => setProfile({ ...profile, beam: Number(event.target.value) })} /></label>
            <label className="text-xs text-[var(--muted)]">temperature<input className="input mt-1" type="number" step={0.1} value={profile.temperature} onChange={(event) => setProfile({ ...profile, temperature: Number(event.target.value) })} /></label>
            <label className="flex items-center gap-2 text-xs text-[var(--muted)]"><input type="checkbox" checked={profile.vad} onChange={(event) => setProfile({ ...profile, vad: event.target.checked })} /> VAD</label>
            <label className="text-xs text-[var(--muted)]">batch<input className="input mt-1" type="number" value={profile.batch} onChange={(event) => setProfile({ ...profile, batch: Number(event.target.value) })} /></label>
            <button className="btn sm:col-span-2" onClick={createProfile}><Plus size={14} /> Создать профиль</button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
