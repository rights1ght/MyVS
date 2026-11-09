import clsx from "clsx";
import {
  AlertTriangle,
  Boxes,
  Check,
  CheckCircle2,
  Download,
  Gauge,
  HardDrive,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, formatBytes, formatMb } from "../api/client";
import type { DownloadInfo, ModelInfo, ModelVariantInfo, ResourcePlan } from "../api/types";
import { Modal } from "../components/Modal";
import { Badge, EmptyState, ErrorBox, MetricBar, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const CATEGORIES = [
  { id: "", label: "Все" },
  { id: "stt", label: "STT" },
  { id: "tts", label: "TTS" },
  { id: "clone", label: "Клонирование" },
];

const ACTIVE_DOWNLOAD = new Set(["queued", "downloading", "verifying", "paused"]);

function russianBadge(status: string) {
  if (status === "confirmed") return <Badge tone="mint"><Check size={10} /> RU</Badge>;
  if (status === "none") return <Badge tone="neutral">RU нет</Badge>;
  return <Badge tone="accent">RU проверить</Badge>;
}

function variantStatus(variant: ModelVariantInfo) {
  if (variant.install_state === "installed") return <Badge tone="mint"><CheckCircle2 size={10} /> установлено</Badge>;
  if (variant.install_state === "downloading") return <Badge tone="blue">скачивается</Badge>;
  if (variant.install_state === "error") return <Badge tone="danger">ошибка</Badge>;
  return <Badge>не скачано</Badge>;
}

function chooseDefaultVariant(model: ModelInfo): ModelVariantInfo | undefined {
  return (
    model.variants.find((variant) => variant.device === "gpu" && variant.install_state === "installed") ??
    model.variants.find((variant) => variant.install_state === "installed") ??
    model.variants.find((variant) => variant.device === "gpu") ??
    model.variants[0]
  );
}

export function ModelsPage() {
  const models = useAsync(() => api<ModelInfo[]>("/api/models"), []);
  const resources = useAsync(() => api<{ loaded: { model_id: string; state: string }[] }>("/api/resources/status"), []);
  const [tab, setTab] = useState("");
  const [query, setQuery] = useState("");
  const [license, setLicense] = useState("");
  const [commercial, setCommercial] = useState("");
  const [installedOnly, setInstalledOnly] = useState(false);
  const [downloads, setDownloads] = useState<DownloadInfo[]>([]);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ModelInfo | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [custom, setCustom] = useState({ id: "", name: "", category: "tts", adapter: "piper", path: "", license: "unknown", commercial: false, russian: "verify", vram: "0", ram: "1", disk: "0" });
  const [plan, setPlan] = useState<{ model: ModelInfo; plan: ResourcePlan } | null>(null);

  const refresh = () => {
    models.reload();
    resources.reload();
  };

  useEffect(() => {
    let mounted = true;
    const tick = () => {
      api<DownloadInfo[]>("/api/downloads")
        .then((rows) => {
          if (!mounted) return;
          setDownloads(rows);
          if (rows.some((row) => row.status === "completed")) refresh();
        })
        .catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 1500);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const loadedIds = new Set((resources.data?.loaded ?? []).map((item) => item.model_id));
  const list = useMemo(() => {
    return (models.data ?? []).filter((model) => {
      if (tab && model.category !== tab) return false;
      if (license && model.license !== license) return false;
      if (commercial === "yes" && !model.commercial) return false;
      if (commercial === "no" && model.commercial) return false;
      if (installedOnly && !model.installed) return false;
      if (query && !`${model.name} ${model.description} ${model.id}`.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [models.data, tab, query, license, commercial, installedOnly]);
  const licenses = Array.from(new Set((models.data ?? []).map((model) => model.license))).sort();

  const startDownload = async (model: ModelInfo, variant: ModelVariantInfo) => {
    setBusy(`download:${variant.id}`);
    setError(null);
    try {
      const row = await api<DownloadInfo>(`/api/models/${model.id}/download`, { method: "POST", body: JSON.stringify({ variant_id: variant.id }) });
      setDownloads((current) => [row, ...current.filter((item) => item.id !== row.id)]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  };

  const pause = async (row: DownloadInfo) => {
    try {
      await api(`/api/downloads/${row.id}/${row.status === "paused" ? "resume" : "pause"}`, { method: "POST" });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const load = async (model: ModelInfo, variant?: ModelVariantInfo, options?: { variantId?: string; device?: string; force?: boolean }) => {
    setBusy(`load:${model.id}`);
    setError(null);
    try {
      if (!options?.force) {
        const compatibility = await api<ResourcePlan>(`/api/models/${model.id}/compatibility?${new URLSearchParams({ variant_id: options?.variantId ?? variant?.id ?? "", device: options?.device ?? variant?.device ?? "" })}`);
        if (compatibility.verdict !== "fits" && !options) {
          setPlan({ model, plan: compatibility });
          return;
        }
      }
      await api(`/api/models/${model.id}/load`, {
        method: "POST",
        body: JSON.stringify({ variant_id: options?.variantId ?? variant?.id, device: options?.device ?? variant?.device, force: Boolean(options?.force) }),
      });
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  };

  const resolveLoad = async (choice: string) => {
    if (!plan) return;
    if (choice === "cancel") {
      setPlan(null);
      return;
    }
    if (choice.startsWith("evict:")) {
      const option = plan.plan.options.find((item) => item.id === choice);
      if (option?.model_id) {
        await api("/api/resources/evict", { method: "POST", body: JSON.stringify({ model_id: option.model_id }) });
      }
      const model = plan.model;
      setPlan(null);
      await load(model, undefined, { variantId: plan.plan.variant_id, device: plan.plan.device });
      return;
    }
    if (choice.startsWith("cpu:") || choice.startsWith("quant:")) {
      const option = plan.plan.options.find((item) => item.id === choice);
      if (option?.variant_id) {
        const model = plan.model;
        setPlan(null);
        await load(model, undefined, { variantId: option.variant_id });
      }
      return;
    }
    if (choice === "confirm") {
      const model = plan.model;
      setPlan(null);
      await load(model, undefined, { variantId: plan.plan.variant_id, device: plan.plan.device, force: true });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Менеджер"
        title="Модели"
        description="Каталог, загрузка с прогрессом, проверка целостности и ручное управление VRAM."
        actions={<><button className="btn" onClick={refresh}><RefreshCw size={15} /> Обновить</button><button className="btn-primary" onClick={() => setCustomOpen(true)}><Plus size={16} /> Своя модель</button></>}
      />

      {error && <ErrorBox message={error} onClose={() => setError(null)} />}

      {downloads.filter((row) => ACTIVE_DOWNLOAD.has(row.status)).length > 0 && (
        <Panel className="p-4">
          <div className="mb-3 flex items-center justify-between"><div className="text-sm font-semibold">Загрузки</div><Badge tone="blue">{downloads.filter((row) => ACTIVE_DOWNLOAD.has(row.status)).length} активных</Badge></div>
          <div className="space-y-3">
            {downloads.filter((row) => ACTIVE_DOWNLOAD.has(row.status)).map((row) => {
              const model = (models.data ?? []).find((item) => item.id === row.model_id);
              const pct = row.bytes_total ? (row.bytes_done / row.bytes_total) * 100 : 0;
              return (
                <div key={row.id} className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="font-medium">{model?.name ?? row.model_id} <span className="ml-2 text-[var(--muted)]">{row.status === "paused" ? "пауза" : `${(row.speed_bps / 1024 / 1024).toFixed(1)} MB/s`}</span></div>
                    <div className="flex items-center gap-2 text-[var(--muted)]"><span>{formatBytes(row.bytes_done)} / {formatBytes(row.bytes_total)}</span><button className="btn-ghost px-2 py-1" onClick={() => pause(row)}>{row.status === "paused" ? <Play size={13} /> : <Pause size={13} />}</button><button className="btn-ghost px-2 py-1" onClick={() => api(`/api/downloads/${row.id}/cancel`, { method: "POST" }).then(() => setDownloads((current) => current.map((item) => item.id === row.id ? { ...item, status: "cancelled" } : item)))}><XCircle size={13} /></button></div>
                  </div>
                  <div className="mt-2"><MetricBar value={pct} tone={pct > 90 ? "mint" : "accent"} /></div>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      <Panel className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          {CATEGORIES.map((category) => (
            <button key={category.id} onClick={() => setTab(category.id)} className={clsx("rounded-xl px-3 py-2 text-xs font-medium transition", tab === category.id ? "bg-[var(--accent-soft)] text-[var(--accent-strong)]" : "text-[var(--muted)] hover:bg-[var(--hover)]")}>{category.label}</button>
          ))}
          <div className="relative ml-auto min-w-[220px] flex-1 sm:max-w-xs">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти модель…" className="input pl-9" />
          </div>
          <select className="select w-auto" value={license} onChange={(event) => setLicense(event.target.value)}><option value="">Лицензия</option>{licenses.map((item) => <option key={item} value={item}>{item}</option>)}</select>
          <select className="select w-auto" value={commercial} onChange={(event) => setCommercial(event.target.value)}><option value="">Коммерция</option><option value="yes">разрешена</option><option value="no">нет</option></select>
          <label className="flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)]"><input type="checkbox" checked={installedOnly} onChange={(event) => setInstalledOnly(event.target.checked)} /> установлено</label>
        </div>
      </Panel>

      {models.loading && <div className="panel p-8 text-center text-sm text-[var(--muted)]">Загрузка каталога…</div>}
      {!models.loading && list.length === 0 && <EmptyState icon={<Boxes size={24} />} title="Ничего не найдено" text="Измените фильтры или добавьте свою модель." />}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((model) => {
          const defaultVariant = chooseDefaultVariant(model);
          const measurement = defaultVariant?.measurement;
          const loaded = loadedIds.has(model.id);
          return (
            <Panel key={model.id} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={model.category === "stt" ? "blue" : model.category === "tts" ? "mint" : "accent"}>{model.category.toUpperCase()}</Badge>
                    {russianBadge(model.russian_status)}
                    {model.watermark && <Badge tone="accent">watermark</Badge>}
                    {!model.commercial && <Badge tone="danger">NC</Badge>}
                  </div>
                  <button className="mt-2 text-left text-[15px] font-semibold hover:text-[var(--accent)]" onClick={() => setDetail(model)}>{model.name}</button>
                </div>
                {loaded ? <Badge tone="mint">в VRAM</Badge> : model.installed ? <Badge tone="blue">на диске</Badge> : <Badge>не скачано</Badge>}
              </div>
              <p className="mt-2 line-clamp-2 min-h-9 text-xs leading-4 text-[var(--muted)]">{model.description}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] text-[var(--muted)]">
                <div><div className="uppercase tracking-wider">VRAM</div><div className="mt-0.5 text-xs text-[var(--text)]">{measurement ? `${measurement.peak_vram_gb.toFixed(2)} GB*` : `${defaultVariant?.vram_estimate_gb ?? 0} GB`}</div></div>
                <div><div className="uppercase tracking-wider">RAM</div><div className="mt-0.5 text-xs text-[var(--text)]">{defaultVariant?.ram_estimate_gb ?? 0} GB</div></div>
                <div><div className="uppercase tracking-wider">Диск</div><div className="mt-0.5 text-xs text-[var(--text)]">{defaultVariant?.disk_gb ?? 0} GB</div></div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1 text-[10px] text-[var(--muted)]">
                {model.languages.slice(0, 7).map((language) => <span key={language} className="rounded bg-[var(--panel-2)] px-1.5 py-0.5">{language}</span>)}
                {model.languages.length > 7 && <span>+{model.languages.length - 7}</span>}
                <span className="ml-auto">{model.license}</span>
              </div>
              {measurement && <div className="mt-2 text-[10px] text-mint-500 dark:text-mint-300">* измерено на этой машине</div>}
              <div className="mt-auto flex flex-wrap gap-2 pt-4">
                {defaultVariant && !defaultVariant.install_state.startsWith("installed") ? (
                  <button className="btn-primary" disabled={busy === `download:${defaultVariant.id}`} onClick={() => startDownload(model, defaultVariant)}><Download size={14} /> {defaultVariant.install_state === "paused" ? "Продолжить" : "Скачать"}</button>
                ) : loaded ? (
                  <button className="btn" onClick={() => api(`/api/models/${model.id}/unload`, { method: "POST" }).then(refresh).catch((err) => setError((err as Error).message))}><Zap size={14} /> Выгрузить</button>
                ) : (
                  <button className="btn-primary" disabled={busy === `load:${model.id}`} onClick={() => defaultVariant && load(model, defaultVariant)}><Play size={14} /> Загрузить</button>
                )}
                <button className="btn" onClick={() => setDetail(model)}>Детали</button>
              </div>
            </Panel>
          );
        })}
      </div>

      <Modal open={Boolean(detail)} onClose={() => setDetail(null)} title={detail?.name ?? ""} subtitle={detail?.description} wide footer={<button className="btn" onClick={() => setDetail(null)}>Закрыть</button>}>
        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">{russianBadge(detail.russian_status)}<Badge>{detail.license}</Badge>{detail.commercial ? <Badge tone="mint">коммерция разрешена</Badge> : <Badge tone="danger">некоммерческое</Badge>}{detail.requires_exclusive && <Badge tone="accent">только exclusive</Badge>}</div>
            {detail.warnings.length > 0 && <div className="rounded-xl border border-amber-400/25 bg-amber-400/5 p-3 text-xs text-amber-700 dark:text-amber-300">{detail.warnings.map((warning) => <div key={warning}>• {warning}</div>)}</div>}
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Варианты</div>
              {detail.variants.map((variant) => (
                <div key={variant.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3 text-xs">
                  <div className="min-w-[130px] font-medium">{variant.label}</div>
                  <div className="text-[var(--muted)]">{variant.device.toUpperCase()} · {variant.precision}</div>
                  <div className="text-[var(--muted)]">{variant.vram_estimate_gb} GB VRAM</div>
                  <div className="text-[var(--muted)]">{variant.ram_estimate_gb} GB RAM</div>
                  {variantStatus(variant)}
                  <div className="ml-auto flex gap-1.5">
                    {variant.install_state !== "installed" ? <button className="btn px-2 py-1" onClick={() => startDownload(detail, variant)}><Download size={12} /> Скачать</button> : <button className="btn px-2 py-1" onClick={() => load(detail, variant)}><Play size={12} /> Загрузить</button>}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn" onClick={() => api(`/api/models/${detail.id}/verify`, { method: "POST", body: JSON.stringify({}) }).then((result) => setError(JSON.stringify(result, null, 2))).catch((err) => setError((err as Error).message))}><ShieldCheck size={14} /> Проверить целостность</button>
              {detail.installed && <button className="btn" onClick={() => api(`/api/models/${detail.id}?delete_files=true`, { method: "DELETE" }).then(() => { setDetail(null); refresh(); })}><Trash2 size={14} /> Удалить файлы</button>}
            </div>
            <div className="rounded-xl border border-[var(--border)] p-3 text-[11px] leading-5 text-[var(--muted)]">
              Адаптер: <span className="font-mono">{detail.adapter}</span> · возможности: {detail.capabilities.join(", ") || "—"} · языки: {detail.languages.length}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={Boolean(plan)} onClose={() => setPlan(null)} title="Не хватает памяти" subtitle={plan?.plan.reason}>
        {plan && (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-[var(--border)] p-3"><div className="text-[var(--muted)]">VRAM</div><div className="mt-1 text-base font-semibold">{plan.plan.need_vram_gb.toFixed(2)} / {plan.plan.free_vram_gb.toFixed(2)} GB</div></div>
              <div className="rounded-xl border border-[var(--border)] p-3"><div className="text-[var(--muted)]">RAM</div><div className="mt-1 text-base font-semibold">{plan.plan.need_ram_gb.toFixed(2)} / {plan.plan.free_ram_gb.toFixed(2)} GB</div></div>
            </div>
            <div className="space-y-2">
              {plan.plan.options.map((option) => (
                <button key={option.id} className="flex w-full items-center justify-between rounded-xl border border-[var(--border)] p-3 text-left hover:border-[var(--accent)]/40" onClick={() => resolveLoad(option.id)}>
                  <span>{option.label}</span>
                  <span className="text-[var(--muted)]">{option.reclaim_gb ? `+${option.reclaim_gb} GB` : option.would_fit ? "подходит" : ""}</span>
                </button>
              ))}
            </div>
            {plan.plan.verdict === "tight" && <button className="btn w-full" onClick={() => resolveLoad("confirm")}>Загрузить всё равно</button>}
            <p className="text-[11px] leading-5 text-[var(--muted)]">При отказе задача не запускается. Для задач те же решения доступны в очереди.</p>
          </div>
        )}
      </Modal>

      <Modal open={customOpen} onClose={() => setCustomOpen(false)} title="Своя модель" subtitle="Метаданные и путь. Запуск возможен только если архитектура поддерживается выбранным адаптером." footer={<><button className="btn" onClick={() => setCustomOpen(false)}>Отмена</button><button className="btn-primary" onClick={async () => {
        try {
          await api("/api/models/custom", { method: "POST", body: JSON.stringify({ id: custom.id, name: custom.name, category: custom.category, adapter: custom.adapter, license: custom.license, commercial: custom.commercial, russian: custom.russian, path: custom.path, variant: { device: "gpu", precision: "fp16", vram_gb: Number(custom.vram), ram_gb: Number(custom.ram), disk_gb: Number(custom.disk), download: { type: "local", path: custom.path } } }) });
          setCustomOpen(false); refresh();
        } catch (err) { setError((err as Error).message); }
      }}>Добавить</button></>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-[var(--muted)]">ID<input className="input mt-1" value={custom.id} onChange={(event) => setCustom({ ...custom, id: event.target.value })} placeholder="my-model" /></label>
          <label className="text-xs text-[var(--muted)]">Название<input className="input mt-1" value={custom.name} onChange={(event) => setCustom({ ...custom, name: event.target.value })} /></label>
          <label className="text-xs text-[var(--muted)]">Категория<select className="select mt-1" value={custom.category} onChange={(event) => setCustom({ ...custom, category: event.target.value })}><option value="stt">STT</option><option value="tts">TTS</option><option value="clone">Клонирование</option></select></label>
          <label className="text-xs text-[var(--muted)]">Адаптер<select className="select mt-1" value={custom.adapter} onChange={(event) => setCustom({ ...custom, adapter: event.target.value })}>{["faster_whisper","piper","silero","kokoro","chatterbox","omnivoice","voxcpm2","qwen3_tts"].map((item) => <option key={item}>{item}</option>)}</select></label>
          <label className="text-xs text-[var(--muted)] sm:col-span-2">Путь к локальной модели<input className="input mt-1" value={custom.path} onChange={(event) => setCustom({ ...custom, path: event.target.value })} placeholder="D:\models\my-model" /></label>
          <label className="text-xs text-[var(--muted)]">Лицензия<input className="input mt-1" value={custom.license} onChange={(event) => setCustom({ ...custom, license: event.target.value })} /></label>
          <label className="text-xs text-[var(--muted)]">Русский<select className="select mt-1" value={custom.russian} onChange={(event) => setCustom({ ...custom, russian: event.target.value })}><option value="confirmed">подтверждён</option><option value="verify">проверить</option><option value="none">нет</option></select></label>
          <label className="text-xs text-[var(--muted)]">VRAM, GB<input className="input mt-1" value={custom.vram} onChange={(event) => setCustom({ ...custom, vram: event.target.value })} /></label>
          <label className="text-xs text-[var(--muted)]">RAM, GB<input className="input mt-1" value={custom.ram} onChange={(event) => setCustom({ ...custom, ram: event.target.value })} /></label>
          <label className="flex items-center gap-2 text-xs text-[var(--muted)]"><input type="checkbox" checked={custom.commercial} onChange={(event) => setCustom({ ...custom, commercial: event.target.checked })} /> коммерческое использование разрешено</label>
        </div>
      </Modal>
    </div>
  );
}
