import { FolderKanban, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { EmptyState, ErrorBox, PageHeader, Panel } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

interface Project {
  id: string;
  name: string;
  description: string;
  color: string;
  created_at: string;
}

export function ProjectsPage() {
  const projects = useAsync(() => api<Project[]>("/api/projects"), []);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    if (!name.trim()) return;
    try {
      await api("/api/projects", { method: "POST", body: JSON.stringify({ name, description }) });
      setName(""); setDescription(""); projects.reload();
    } catch (err) { setError((err as Error).message); }
  };
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Workspace" title="Проекты" description="Группируйте задачи, голоса и историю по проектам." />
      {error && <ErrorBox message={error} onClose={() => setError(null)} />}
      <Panel className="p-4">
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1" placeholder="Название проекта" value={name} onChange={(event) => setName(event.target.value)} />
          <input className="input flex-1" placeholder="Описание" value={description} onChange={(event) => setDescription(event.target.value)} />
          <button className="btn-primary" onClick={create}><Plus size={15} /> Создать</button>
        </div>
      </Panel>
      {(projects.data ?? []).length === 0 ? <EmptyState icon={<FolderKanban size={24} />} title="Проектов пока нет" text="Создайте первый проект, чтобы группировать задачи." /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(projects.data ?? []).map((project) => (
            <Panel key={project.id} className="p-5">
              <div className="flex items-start justify-between"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]"><FolderKanban size={18} /></div><button className="btn-ghost px-2 py-1" onClick={() => api(`/api/projects/${project.id}`, { method: "DELETE" }).then(() => projects.reload())}><Trash2 size={14} /></button></div>
              <div className="mt-3 text-sm font-semibold">{project.name}</div>
              <p className="mt-1 text-xs text-[var(--muted)]">{project.description || "Без описания"}</p>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
