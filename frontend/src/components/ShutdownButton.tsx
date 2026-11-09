import { Power, ServerOff } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { Modal } from "./Modal";
import { ErrorBox } from "./ui";

export function ShutdownButton() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shutdown = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/api/system/shutdown", {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      setDone(true);
      setOpen(false);
      window.setTimeout(() => {
        try {
          window.close();
        } catch {
          // Browsers generally do not allow closing a tab they did not open.
        }
      }, 1500);
    } catch (err) {
      // A dropped connection is expected when the process exits; the server
      // stops after sending 202, so the UI may lose the response.
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      const alive = await fetch("/api/health", { cache: "no-store" })
        .then((response) => response.ok)
        .catch(() => false);
      if (!alive) {
        setDone(true);
        setOpen(false);
      } else {
        setError((err as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-[var(--muted)] transition hover:bg-red-400/10 hover:text-red-500"
        title="Остановить сервер и выгрузить модели"
      >
        <Power size={17} />
        <span className="hidden text-xs xl:inline">Выход</span>
      </button>

      <Modal
        open={open}
        onClose={() => !busy && setOpen(false)}
        title="Остановить MyVS?"
        subtitle="Сервер, все воркеры и загруженные модели будут остановлены."
        footer={
          <>
            <button className="btn" disabled={busy} onClick={() => setOpen(false)}>Отмена</button>
            <button className="btn bg-red-500 text-white hover:bg-red-600" disabled={busy} onClick={shutdown}>
              <Power size={15} /> {busy ? "Выгружаем…" : "Остановить и выгрузить"}
            </button>
          </>
        }
      >
        <div className="space-y-3 text-xs leading-5 text-[var(--muted)]">
          <div className="rounded-xl border border-red-400/25 bg-red-400/5 p-3 text-red-700 dark:text-red-300">
            Незавершённые задачи будут прерваны, очередь остановлена.
          </div>
          <p>Модели будут выгружены из VRAM и RAM, воркеры завершены, порт освобождён.</p>
          <p>После остановки сервера вкладку можно закрыть. Автоматическое закрытие вкладки браузер может заблокировать.</p>
        </div>
        {error && <div className="mt-3"><ErrorBox message={error} onClose={() => setError(null)} /></div>}
      </Modal>

      {done && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--bg)] px-6">
          <div className="max-w-md text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--panel)] text-[var(--accent)]">
              <ServerOff size={30} />
            </div>
            <h2 className="mt-5 text-xl font-semibold">MyVS остановлен</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
              Модели выгружены из памяти, воркеры остановлены, сервер завершил работу.
              Вкладку можно закрыть.
            </p>
            <div className="mt-5 flex justify-center gap-2">
              <button className="btn" onClick={() => window.close()}>Закрыть вкладку</button>
              <button className="btn" onClick={() => window.location.reload()}>Проверить снова</button>
            </div>
            <p className="mt-4 text-[11px] text-[var(--muted)]">
              Если вкладка не закрылась, браузер запретил автоматическое закрытие.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
