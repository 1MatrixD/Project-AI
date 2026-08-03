"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, setToken, fmtDate } from "@/lib/api";
import { pickDirNative } from "@/lib/pickDir";
import type { Project } from "@/lib/types";
import DirPicker from "@/components/DirPicker";
import StatusBadge from "@/components/StatusBadge";

export default function ProjectsPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);

  const load = useCallback(async () => {
    try {
      setProjects(await api<Project[]>("/projects"));
    } catch {
      /* 401 обработан в api() */
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  function applyPath(p: string) {
    setRootPath(p);
    if (!name) setName(p.split(/[\\/]/).filter(Boolean).pop() ?? "");
  }

  /** Сначала системный диалог; своя модалка остаётся запасным вариантом. */
  async function browse() {
    setError("");
    setPicking(true);
    try {
      const p = await pickDirNative(rootPath);
      if (p === "unsupported") setShowPicker(true);
      else if (p) applyPath(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setPicking(false);
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const p = await api<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({ name, description, root_path: rootPath }),
      });
      router.push(`/projects/${p.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 max-w-5xl w-full mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-xl font-semibold bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)] bg-clip-text text-transparent">
          Проекты ИИ
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={() => setShowCreate(true)}>+ Новый проект</button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              setToken(null);
              router.replace("/login");
            }}
          >
            Выйти
          </button>
        </div>
      </div>

      {projects === null ? (
        <div className="text-[var(--muted)]">Загрузка…</div>
      ) : projects.length === 0 ? (
        <div className="card p-10 text-center space-y-3">
          <div className="text-lg">Пока нет проектов</div>
          <div className="text-sm text-[var(--muted)]">
            Создай проект, укажи каталог с кодом — и в фоне соберётся карта знаний:
            архитектура, сервисы, бизнес-логика, связи файлов.
          </div>
          <button className="btn" onClick={() => setShowCreate(true)}>Создать первый проект</button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} onChanged={load} onError={setError} />
          ))}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowCreate(false)}>
          <form onSubmit={create} className="card w-full max-w-lg p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="font-medium text-lg">Новый проект</div>
            <input className="input" required placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} />
            <textarea
              className="input min-h-20"
              placeholder="Описание (необязательно)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="flex gap-2">
              <input
                className="input font-mono text-xs"
                required
                placeholder="Каталог проекта на диске"
                value={rootPath}
                onChange={(e) => setRootPath(e.target.value)}
              />
              <button
                type="button"
                className="btn btn-ghost whitespace-nowrap"
                onClick={browse}
                disabled={picking}
                title="Откроется системный диалог Windows"
              >
                {picking ? "Диалог открыт…" : "Обзор…"}
              </button>
            </div>
            <div className="text-xs text-[var(--muted)]">
              После создания в фоне запустится анализ проекта: структура, стек,
              ИИ-разбор файлов и карта знаний в Neo4j.
            </div>
            {error && <div className="text-sm text-red-400">{error}</div>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn btn-ghost" onClick={() => setShowCreate(false)}>Отмена</button>
              <button className="btn" disabled={busy}>{busy ? "Создаю…" : "Создать и проанализировать"}</button>
            </div>
          </form>
        </div>
      )}

      {showPicker && (
        <DirPicker
          onClose={() => setShowPicker(false)}
          onSelect={(p) => {
            applyPath(p);
            setShowPicker(false);
          }}
        />
      )}
    </div>
  );
}

/** Карточка проекта. Вся площадь — ссылка, поэтому содержимое прозрачно для
 *  кликов, а меню действий возвращает их себе (pointer-events-auto). */
function ProjectCard({
  project: p,
  onChanged,
  onError,
}: {
  project: Project;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState("");

  async function duplicate() {
    setBusy("Дублирую…");
    onError("");
    try {
      await api(`/projects/${p.id}/duplicate`, { method: "POST", body: JSON.stringify({}) });
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    const ok = confirm(
      `Удалить проект «${p.name}»?\n\n` +
        "Удалятся карта знаний, задачи, чаты, материалы и соглашения. " +
        "Каталог с кодом на диске останется нетронутым.\n\nОтменить будет нельзя."
    );
    if (!ok) return;
    setBusy("Удаляю…");
    onError("");
    try {
      await api(`/projects/${p.id}`, { method: "DELETE" });
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка");
      setBusy("");
    }
  }

  return (
    <div className="card p-5 space-y-2 relative hover:border-[var(--accent)] transition-colors">
      <Link href={`/projects/${p.id}`} className="absolute inset-0 rounded-xl" aria-label={p.name} />
      <div className="relative pointer-events-none space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="font-medium truncate">{p.name}</div>
          <div className="flex items-center gap-1.5 shrink-0">
            <StatusBadge status={p.status} />
            <div className="relative pointer-events-auto">
              <button
                className="text-[var(--muted)] hover:text-[var(--foreground)] px-1.5 leading-none"
                onClick={() => setMenu((v) => !v)}
                disabled={!!busy}
                title="Действия с проектом"
              >
                ⋯
              </button>
              {menu && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setMenu(false)} />
                  <div className="absolute right-0 top-full mt-1 z-40 card p-1 w-64 shadow-xl text-left">
                    <button
                      className="w-full text-left text-sm px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                      onClick={() => { setMenu(false); duplicate(); }}
                    >
                      ⧉ Дублировать
                      <span className="block text-[11px] text-[var(--muted)]">
                        копия с готовой картой знаний — ИИ-анализ файлов не повторяется
                      </span>
                    </button>
                    <button
                      className="w-full text-left text-sm px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)] text-red-300"
                      onClick={() => { setMenu(false); remove(); }}
                    >
                      Удалить проект
                      <span className="block text-[11px] text-[var(--muted)]">
                        каталог с кодом на диске не тронется
                      </span>
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="text-xs text-[var(--muted)] font-mono truncate">{p.root_path}</div>
        {p.description && (
          <div className="text-sm text-[var(--muted)] line-clamp-2">{p.description}</div>
        )}
        <div className="flex gap-2 flex-wrap pt-1">
          {(p.meta.detect?.stack ?? []).slice(0, 5).map((s) => (
            <span key={s} className="chip">{s}</span>
          ))}
        </div>
        <div className="text-xs text-[var(--muted)]">
          {busy || `Обновлён ${fmtDate(p.updated_at)}`}
        </div>
      </div>
    </div>
  );
}
