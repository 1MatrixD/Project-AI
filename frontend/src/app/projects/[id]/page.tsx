"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, streamEvents } from "@/lib/api";
import type { Job, Project } from "@/lib/types";
import StatusBadge from "@/components/StatusBadge";
import OverviewTab from "@/components/project/OverviewTab";
import KanbanTab from "@/components/project/KanbanTab";
import ChatTab from "@/components/project/ChatTab";
import FilesTab from "@/components/project/FilesTab";
import MaterialsTab from "@/components/project/MaterialsTab";
import GraphTab from "@/components/project/GraphTab";
import PluginTab from "@/components/project/PluginTab";

const TABS = [
  { key: "overview", label: "Обзор" },
  { key: "kanban", label: "Задачи" },
  { key: "chat", label: "Чат" },
  { key: "files", label: "Файлы" },
  { key: "materials", label: "Материалы" },
  { key: "graph", label: "Карта" },
  { key: "plugin", label: "Плагин" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const JOB_LABELS: Record<string, string> = {
  index: "Индексация",
  knowledge_update: "Обновление карты знаний",
  verify_tasks: "ИИ-проверка задач",
  enrich_tasks: "RLM-проработка задач",
  plan_task: "Планировщик задачи",
  git_import: "Импорт истории git",
  process_material: "Обработка материала",
  plugin_generate: "Генерация плагина",
};

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tab, setTab] = useState<TabKey>("overview");
  const [refreshTick, setRefreshTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const [p, j] = await Promise.all([
        api<Project>(`/projects/${id}`),
        api<Job[]>(`/projects/${id}/jobs?limit=10`),
      ]);
      setProject(p);
      setJobs(j);
    } catch {
      /* обработано в api() */
    }
  }, [id]);

  // SSE-пуш событий проекта; редкий поллинг — только как резерв при обрыве стрима
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    load();
    let stopped = false;
    const ctrl = new AbortController();
    (async () => {
      while (!stopped) {
        try {
          await streamEvents(
            `/projects/${id}/jobs/events`,
            (e) => {
              if (e.type === "job") {
                loadRef.current();
                const st = e.job?.status;
                if (st === "done" || st === "error" || st === "cancelled") {
                  setRefreshTick((x) => x + 1);
                }
              } else if (e.type === "tasks_changed") {
                setRefreshTick((x) => x + 1);
              }
            },
            ctrl.signal
          );
        } catch {
          /* обрыв/401 — переподключимся */
        }
        if (!stopped) await new Promise((r) => setTimeout(r, 3000));
      }
    })();
    const t = setInterval(() => {
      loadRef.current();
      setRefreshTick((x) => x + 1);
    }, 20000);
    return () => {
      stopped = true;
      ctrl.abort();
      clearInterval(t);
    };
  }, [id, load]);

  const activeJobs = jobs.filter((j) => j.status === "running" || j.status === "queued");

  if (!project) {
    return <div className="flex-1 flex items-center justify-center text-[var(--muted)]">Загрузка…</div>;
  }

  return (
    <div className="flex-1 flex flex-col max-w-7xl w-full mx-auto p-4 gap-4 min-h-0">
      <div className="flex items-center gap-3 flex-wrap">
        <Link href="/projects" className="text-[var(--muted)] hover:text-white">←</Link>
        <div className="text-lg font-semibold">{project.name}</div>
        <StatusBadge status={project.status} />
        <div className="text-xs text-[var(--muted)] font-mono truncate max-w-md">{project.root_path}</div>
        <div className="flex-1" />
        <div className="flex gap-2 border border-[var(--border)] rounded-lg p-1 flex-wrap">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                tab === t.key ? "bg-[var(--accent)] text-white" : "text-[var(--muted)] hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {activeJobs.length > 0 && (
        <div className="card px-4 py-3 space-y-2">
          {activeJobs.map((j) => (
            <div key={j.id} className="space-y-1">
              <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                <span className="pulse flex-1 truncate">
                  {JOB_LABELS[j.type] ?? j.type}
                  {j.detail ? ` — ${j.detail}` : ""}
                </span>
                <span>{Math.round(j.progress * 100)}%</span>
                <button
                  title="Отменить задачу"
                  onClick={async () => {
                    try {
                      await api(`/projects/${id}/jobs/${j.id}/cancel`, { method: "POST" });
                    } catch {
                      /* уже завершена */
                    }
                    load();
                  }}
                  className="px-1.5 rounded hover:bg-[var(--surface-2)] hover:text-red-400 transition-colors"
                >
                  ✕
                </button>
              </div>
              <div className="h-1.5 rounded bg-[var(--surface-2)] overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)] transition-all duration-500"
                  style={{ width: `${Math.max(3, j.progress * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex-1 min-h-0">
        {tab === "overview" && (
          <OverviewTab project={project} jobs={jobs} onAction={load} />
        )}
        {tab === "kanban" && <KanbanTab projectId={project.id} refreshTick={refreshTick} />}
        {tab === "chat" && <ChatTab projectId={project.id} />}
        {tab === "files" && <FilesTab projectId={project.id} />}
        {tab === "materials" && <MaterialsTab projectId={project.id} refreshTick={refreshTick} />}
        {tab === "graph" && <GraphTab projectId={project.id} />}
        {tab === "plugin" && <PluginTab projectId={project.id} />}
      </div>
    </div>
  );
}
