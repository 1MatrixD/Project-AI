"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, setToken, fmtDate } from "@/lib/api";
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
            <Link key={p.id} href={`/projects/${p.id}`} className="card p-5 hover:border-[var(--accent)] transition-colors space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="font-medium truncate">{p.name}</div>
                <StatusBadge status={p.status} />
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
              <div className="text-xs text-[var(--muted)]">Обновлён {fmtDate(p.updated_at)}</div>
            </Link>
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
              <button type="button" className="btn btn-ghost whitespace-nowrap" onClick={() => setShowPicker(true)}>
                Обзор…
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
            setRootPath(p);
            setShowPicker(false);
            if (!name) setName(p.split(/[\\/]/).filter(Boolean).pop() ?? "");
          }}
        />
      )}
    </div>
  );
}
