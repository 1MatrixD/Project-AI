"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { api, streamEvents } from "@/lib/api";
import type { Job, Project } from "@/lib/types";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import StatusBadge from "@/components/StatusBadge";
import { toast } from "@/components/Toast";
import { ProjectProvider } from "@/components/project/ProjectContext";

/** Вкладки — маршруты, а не клиентское состояние: рефреш и прямые ссылки
 *  сохраняют текущую страницу (раньше F5 всегда сбрасывал на «Обзор»). */
const NAV = [
  { href: "", key: "overview" },
  { href: "/tasks", key: "tasks" },
  { href: "/decisions", key: "decisions" },
  { href: "/files", key: "files" },
  { href: "/materials", key: "materials" },
  { href: "/map", key: "map" },
  { href: "/plugin", key: "plugin" },
] as const;

/** Подпись типа фоновой работы; неизвестный тип показывается как есть. */
function useJobLabel() {
  const t = useTranslations("layout.jobs");
  return (type: string) => (t.has(type) ? t(type) : type);
}

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const t = useTranslations("layout");
  const tCommon = useTranslations("common");
  const jobLabel = useJobLabel();
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
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
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  // Подписи для тостов берём через ref: сам эффект подписки не должен
  // пересоздаваться при смене языка.
  const labelsRef = useRef({ jobLabel, failed: t("jobFailed") });
  useEffect(() => {
    labelsRef.current = { jobLabel, failed: t("jobFailed") };
  });
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
                // Итог работы — тостом: «готово с ошибками» раньше выглядело
                // как обычное зелёное завершение, и пустые карточки удивляли.
                if (e.job) {
                  const label = labelsRef.current.jobLabel(e.job.type);
                  if (st === "error") {
                    const first = String(e.job.error ?? "").split("\n")[0].slice(0, 160);
                    toast(`${label}: ${first || labelsRef.current.failed}`, "error");
                  } else if (st === "done" && e.job.detail) {
                    toast(`${label}: ${e.job.detail}`, "error");
                  }
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
    const timer = setInterval(() => {
      loadRef.current();
      setRefreshTick((x) => x + 1);
    }, 20000);
    return () => {
      stopped = true;
      ctrl.abort();
      clearInterval(timer);
    };
  }, [id, load]);

  if (!project) {
    return <div className="flex-1 flex items-center justify-center text-[var(--muted)]">{tCommon("loading")}</div>;
  }

  const base = `/projects/${id}`;

  return (
    <ProjectProvider value={{ project, jobs, refreshTick, reload: load }}>
      <div className="flex-1 flex flex-col max-w-7xl w-full mx-auto p-4 gap-4 min-h-0">
        <div className="flex items-center gap-3 flex-wrap">
          <Link href="/projects" className="text-[var(--muted)] hover:text-white">←</Link>
          <div className="text-lg font-semibold">{project.name}</div>
          <StatusBadge status={project.status} />
          <div className="text-xs text-[var(--muted)] font-mono truncate max-w-md">{project.root_path}</div>
          <div className="flex-1" />
          <IndexButton projectId={project.id} unsynced={project.unsynced_worklogs ?? 0} onStarted={load} />
          <JobsTray projectId={project.id} jobs={jobs} onAction={load} />
          <nav className="flex gap-2 border border-[var(--border)] rounded-lg p-1 flex-wrap">
            {NAV.map((n) => {
              const href = `${base}${n.href}`;
              const active = n.href === "" ? pathname === base : pathname.startsWith(href);
              return (
                <Link
                  key={n.href}
                  href={href}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                    active ? "bg-[var(--accent)] text-white" : "text-[var(--muted)] hover:text-white"
                  }`}
                >
                  {t(`nav.${n.key}`)}
                </Link>
              );
            })}
          </nav>
          <LanguageSwitcher />
        </div>

        <div className="flex-1 min-h-0">{children}</div>
      </div>
    </ProjectProvider>
  );
}

/** «Обновить индекс» из шапки — доступен с любой страницы. Бейдж показывает,
 *  сколько выполненных работ карта ещё не учитывает: обновление карты ручное,
 *  автозапуск после каждой задачи конкурировал за ИИ-слоты с проработками. */
function IndexButton({
  projectId,
  unsynced,
  onStarted,
}: {
  projectId: string;
  unsynced: number;
  onStarted: () => void;
}) {
  const t = useTranslations("layout");
  const tCommon = useTranslations("common");

  async function run() {
    try {
      const autoContinue = localStorage.getItem("projectai_auto_continue") !== "0";
      await api(`/projects/${projectId}/index`, {
        method: "POST",
        body: JSON.stringify({ mode: "update", retry_errors: true, auto_continue: autoContinue }),
      });
      toast(t("indexStarted"));
      onStarted();
    } catch (e) {
      toast(e instanceof Error ? e.message : tCommon("error"), "error");
    }
  }

  return (
    <button
      className="btn btn-ghost text-sm relative"
      onClick={run}
      title={unsynced > 0 ? t("indexTitleUnsynced", { count: unsynced }) : t("indexTitle")}
    >
      {t("indexButton")}
      {unsynced > 0 && (
        <span className="absolute -top-1.5 -right-1.5 min-w-5 h-5 px-1 rounded-full bg-amber-500 text-black text-[11px] font-medium flex items-center justify-center">
          {unsynced > 99 ? "99+" : unsynced}
        </span>
      )}
    </button>
  );
}

/** Трей работ: очередь ИИ-задач больше не занимает пол-экрана баннерами —
 *  компактный индикатор в шапке, раскрывающийся списком с прогрессом и отменой. */
function JobsTray({
  projectId,
  jobs,
  onAction,
}: {
  projectId: string;
  jobs: Job[];
  onAction: () => void;
}) {
  const t = useTranslations("layout");
  const jobLabel = useJobLabel();
  const [open, setOpen] = useState(false);
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");

  useEffect(() => {
    if (active.length === 0) setOpen(false);
  }, [active.length]);

  if (active.length === 0) return null;

  const avg = active.reduce((s, j) => s + j.progress, 0) / active.length;

  return (
    <div className="relative">
      <button
        className="btn btn-ghost text-sm pulse"
        onClick={() => setOpen((v) => !v)}
        title={t("trayTitle")}
      >
        ⚙ {active.length} · {Math.round(avg * 100)}%
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1.5 z-50 card p-3 w-96 max-w-[90vw] shadow-xl space-y-2.5">
            {active.map((j) => (
              <div key={j.id} className="space-y-1">
                <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span className="flex-1 truncate">
                    {jobLabel(j.type)}
                    {j.detail ? ` — ${j.detail}` : ""}
                  </span>
                  <span>{Math.round(j.progress * 100)}%</span>
                  <button
                    title={t("cancelJob")}
                    onClick={async () => {
                      try {
                        await api(`/projects/${projectId}/jobs/${j.id}/cancel`, { method: "POST" });
                      } catch {
                        /* уже завершена */
                      }
                      onAction();
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
        </>
      )}
    </div>
  );
}
