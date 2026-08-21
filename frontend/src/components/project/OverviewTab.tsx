"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, fmtDate, getToken } from "@/lib/api";
import { pickDirNative } from "@/lib/pickDir";
import type { ChangeReport, Job, Project } from "@/lib/types";
import StatusBadge from "@/components/StatusBadge";
import DirPicker from "@/components/DirPicker";

const KIND_LABELS: Record<string, string> = {
  code: "код",
  config: "конфиги",
  doc: "документы",
  test: "тесты",
  asset: "ассеты",
  data: "данные",
  other: "прочее",
};

export default function OverviewTab({
  project,
  jobs,
  onAction,
}: {
  project: Project;
  jobs: Job[];
  onAction: () => void;
}) {
  const [changes, setChanges] = useState<ChangeReport[]>([]);
  const [error, setError] = useState("");
  const [showGitImport, setShowGitImport] = useState(false);
  const [showRootPicker, setShowRootPicker] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [autoContinue, setAutoContinue] = useState(true);
  const [watch, setWatch] = useState(false);

  useEffect(() => {
    setAutoContinue(localStorage.getItem("projectai_auto_continue") !== "0");
  }, []);

  useEffect(() => {
    setWatch(!!project.meta.watch);
  }, [project.meta.watch]);

  useEffect(() => {
    if (!showMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowMenu(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showMenu]);

  function toggleAutoContinue(v: boolean) {
    setAutoContinue(v);
    localStorage.setItem("projectai_auto_continue", v ? "1" : "0");
  }

  async function toggleWatch(v: boolean) {
    setWatch(v);
    setError("");
    try {
      await api(`/projects/${project.id}/watch`, {
        method: "POST",
        body: JSON.stringify({ enabled: v }),
      });
      onAction();
    } catch (e) {
      setWatch(!v);
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }
  async function addRoot(path: string) {
    setShowRootPicker(false);
    setError("");
    try {
      await api(`/projects/${project.id}/roots`, {
        method: "POST",
        body: JSON.stringify({ path }),
      });
      onAction();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  /** Как и при создании проекта: сначала системный диалог, DirPicker — запасной. */
  async function browseRoot() {
    setError("");
    try {
      const p = await pickDirNative(project.root_path);
      if (p === "unsupported") setShowRootPicker(true);
      else if (p) await addRoot(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  async function removeRoot(alias: string) {
    if (!confirm(`Убрать каталог «${alias}» из проекта? Его файлы удалятся из карты знаний.`)) return;
    setError("");
    try {
      await api(`/projects/${project.id}/roots/${encodeURIComponent(alias)}`, { method: "DELETE" });
      onAction();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  const extraRoots = project.meta.extra_roots ?? [];
  const overview = project.meta.overview;
  const stats = project.meta.stats;
  const graphStats = project.stats;

  useEffect(() => {
    api<ChangeReport[]>(`/projects/${project.id}/changes`).then(setChanges).catch(() => {});
  }, [project.id, project.updated_at]);

  async function runIndex(mode: "update" | "reverify") {
    setError("");
    if (mode === "reverify" && !confirm("Перепроверить весь проект заново? Все файлы будут переанализированы ИИ.")) return;
    try {
      // ручной запуск: ретраим упавшие файлы; при включённой галке гоним бэклог до конца
      await api(`/projects/${project.id}/index`, {
        method: "POST",
        body: JSON.stringify({ mode, retry_errors: true, auto_continue: autoContinue }),
      });
      onAction();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  async function downloadExport() {
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/projects/${project.id}/export/markdown`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error("Экспорт не удался");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${project.name.replace(/[^\wа-яё -]/gi, "").trim() || "проект"} — карта знаний.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  const lastJob = jobs.find((j) => j.type === "index");

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2 space-y-4">
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="font-medium">О проекте</div>
            <div className="flex gap-1.5 items-center relative">
              <button
                className="btn btn-ghost text-sm"
                title="Просканировать изменения и продолжить ИИ-анализ"
                onClick={() => runIndex("update")}
              >
                ⟳ Обновить индекс
              </button>
              <button
                className="btn btn-ghost text-sm px-2.5"
                title="Ещё действия"
                onClick={() => setShowMenu((v) => !v)}
              >
                ⋯
              </button>
              {showMenu && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setShowMenu(false)} />
                  <div className="absolute right-0 top-full mt-1.5 z-40 card p-1.5 w-72 shadow-xl space-y-0.5">
                    <label
                      className="flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)] cursor-pointer select-none"
                      title="Иначе за один прогон анализируется ограниченная порция файлов"
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 accent-[var(--accent)]"
                        checked={autoContinue}
                        onChange={(e) => toggleAutoContinue(e.target.checked)}
                      />
                      <span className="text-sm">
                        Анализ до конца бэклога
                        <span className="block text-[11px] text-[var(--muted)]">
                          продолжать порциями, пока все файлы не проанализированы
                        </span>
                      </span>
                    </label>
                    <label
                      className="flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)] cursor-pointer select-none"
                      title="Работает, пока запущен сервер; состояние сохраняется"
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 accent-[var(--accent)]"
                        checked={watch}
                        onChange={(e) => toggleWatch(e.target.checked)}
                      />
                      <span className="text-sm">
                        Наблюдение за каталогом
                        <span className="block text-[11px] text-[var(--muted)]">
                          правки в коде сами запускают обновление индекса
                        </span>
                      </span>
                    </label>
                    <div className="border-t border-[var(--border)] my-1" />
                    <button
                      className="w-full text-left text-sm px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                      onClick={() => { setShowMenu(false); runIndex("reverify"); }}
                    >
                      ⟲ Перепроверить всё
                      <span className="block text-[11px] text-[var(--muted)]">полный пере-анализ всех файлов ИИ</span>
                    </button>
                    <button
                      className="w-full text-left text-sm px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                      onClick={() => { setShowMenu(false); setShowGitImport(true); }}
                    >
                      ⎇ Импорт из git
                      <span className="block text-[11px] text-[var(--muted)]">история коммитов → задачи канбана</span>
                    </button>
                    <button
                      className="w-full text-left text-sm px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                      onClick={() => { setShowMenu(false); browseRoot(); }}
                    >
                      🗂 Добавить каталог
                      <span className="block text-[11px] text-[var(--muted)]">
                        мультирепо: например, отдельный репозиторий бэкенда
                      </span>
                    </button>
                    <button
                      className="w-full text-left text-sm px-2.5 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                      onClick={() => { setShowMenu(false); downloadExport(); }}
                    >
                      ⬇ Экспорт карты знаний
                      <span className="block text-[11px] text-[var(--muted)]">скачать одним markdown-файлом</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
          {error && <div className="text-sm text-red-400">{error}</div>}
          {overview?.summary ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{overview.summary}</p>
          ) : (
            <p className="text-sm text-[var(--muted)]">
              Обзор появится после первичной индексации (ИИ-анализ файлов и синтез).
            </p>
          )}
          <div className="flex gap-2 flex-wrap">
            {(project.meta.detect?.project_kinds ?? []).map((k) => (
              <span key={k} className="chip text-[var(--accent)]">{k}</span>
            ))}
            {(project.meta.detect?.stack ?? []).map((s) => (
              <span key={s} className="chip">{s}</span>
            ))}
          </div>
          {extraRoots.length > 0 && (
            <div className="space-y-1.5 pt-1 border-t border-[var(--border)]">
              <div className="text-xs text-[var(--muted)] pt-2">
                Дополнительные каталоги (их файлы ходят с префиксом «алиас/»):
              </div>
              {extraRoots.map((r) => (
                <div key={r.alias} className="flex items-center gap-2 text-xs group min-w-0">
                  <span className="chip shrink-0">{r.alias}/</span>
                  <span className="font-mono text-[var(--muted)] truncate">{r.path}</span>
                  <button
                    className="text-[var(--muted)] hover:text-red-300 opacity-0 group-hover:opacity-100 shrink-0"
                    title="Убрать каталог из проекта"
                    onClick={() => removeRoot(r.alias)}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {overview?.components?.length ? (
          <div className="card p-5 space-y-3">
            <div className="font-medium">Компоненты</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {overview.components.map((c) => (
                <div key={c.name} className="border border-[var(--border)] rounded-lg p-3 space-y-1">
                  <div className="text-sm font-medium flex items-center gap-2">
                    {c.name} <span className="chip">{c.kind}</span>
                  </div>
                  <div className="text-xs text-[var(--muted)] leading-relaxed">{c.summary}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {overview?.business_logic?.length ? (
          <div className="card p-5 space-y-3">
            <div className="font-medium">Бизнес-логика</div>
            {overview.business_logic.map((f) => (
              <div key={f.name} className="border-l-2 border-[var(--accent)] pl-3 space-y-0.5">
                <div className="text-sm font-medium">{f.name}</div>
                <div className="text-xs text-[var(--muted)] leading-relaxed">{f.summary}</div>
              </div>
            ))}
          </div>
        ) : null}

        {overview?.conventions ? (
          <div className="card p-5 space-y-2">
            <div className="font-medium">Конвенции</div>
            <div className="text-xs text-[var(--muted)] leading-relaxed">
              Как код написан <b>по факту</b>: ИИ вывел это сам при индексации, руками не
              правится и перезаписывается на каждом прогоне. То, о чём <b>договорились</b>,
              — на странице «Соглашения».
            </div>
            <p className="text-sm text-[var(--muted)] whitespace-pre-wrap leading-relaxed">{overview.conventions}</p>
          </div>
        ) : null}
      </div>

      <div className="space-y-4">
        <Link
          href={`/projects/${project.id}/decisions`}
          className="card p-5 block hover:border-[var(--accent)] transition-colors space-y-1"
        >
          <div className="font-medium">Соглашения проекта →</div>
          <div className="text-xs text-[var(--muted)] leading-relaxed">
            Актуальные решения и смены подходов — то, чего в коде не прочитать.
            Пишут человек и ИИ (record_decision); учитываются в каждой проработке
            и проверке.
          </div>
        </Link>
        <div className="card p-5 space-y-3">
          <div className="font-medium">Статистика</div>
          {stats ? (
            <>
              <div className="text-sm">
                Файлов: <b>{stats.files_total}</b>, проанализировано ИИ: <b>{stats.analyzed}</b>
              </div>
              <div className="flex gap-2 flex-wrap">
                {Object.entries(stats.by_kind).map(([k, v]) => (
                  <span key={k} className="chip">{KIND_LABELS[k] ?? k}: {v}</span>
                ))}
              </div>
            </>
          ) : (
            <div className="text-sm text-[var(--muted)]">Ещё не сканировался</div>
          )}
          {graphStats?.nodes && (
            <div className="text-xs text-[var(--muted)]">
              Граф: {Object.entries(graphStats.nodes).map(([k, v]) => `${k} ${v}`).join(", ")}; связей: {graphStats.relations}
            </div>
          )}
          {lastJob && (
            <div className="text-xs text-[var(--muted)] flex items-center gap-2">
              Последняя индексация: <StatusBadge status={lastJob.status} /> {fmtDate(lastJob.created_at)}
            </div>
          )}
          {lastJob?.error && (
            <div className="text-xs text-red-400 whitespace-pre-wrap">{lastJob.error.slice(0, 300)}</div>
          )}
        </div>

        <div className="card p-5 space-y-3">
          <div className="font-medium">Что изменилось</div>
          {changes.length === 0 ? (
            <div className="text-sm text-[var(--muted)]">Отчётов пока нет</div>
          ) : (
            changes.slice(0, 5).map((c) => (
              <div key={c.id} className="border border-[var(--border)] rounded-lg p-3 space-y-1">
                <div className="flex justify-between text-xs text-[var(--muted)]">
                  <span>{c.mode === "initial" ? "Первичный скан" : c.mode === "reverify" ? "Полная перепроверка" : "Обновление"}</span>
                  <span>{fmtDate(c.created_at)}</span>
                </div>
                <div className="text-sm">
                  <span className="text-emerald-300">+{c.stats.added}</span>{" "}
                  <span className="text-amber-300">~{c.stats.modified}</span>{" "}
                  <span className="text-red-300">−{c.stats.deleted}</span>{" "}
                  <span className="text-[var(--muted)]">из {c.stats.total}</span>
                </div>
                {[...c.added.slice(0, 3), ...c.modified.slice(0, 3)].map((p) => (
                  <div key={p} className="text-xs font-mono text-[var(--muted)] truncate">{p}</div>
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      {showGitImport && (
        <GitImportModal
          projectId={project.id}
          onClose={() => setShowGitImport(false)}
          onStarted={() => {
            setShowGitImport(false);
            onAction();
          }}
        />
      )}
      {showRootPicker && (
        <DirPicker onSelect={addRoot} onClose={() => setShowRootPicker(false)} />
      )}
    </div>
  );
}

const PERIODS = [
  { days: 7, label: "Неделя" },
  { days: 30, label: "Месяц" },
  { days: 90, label: "3 месяца" },
  { days: 0, label: "Вся история" },
];

type GitRepo = {
  path: string;
  current_branch: string;
  branches: string[];
  last_commit: string;
  total_commits: number;
};

type RepoConfig = {
  checked: boolean;
  branch: string;
  days: number;
  limit: number;
};

function GitImportModal({
  projectId,
  onClose,
  onStarted,
}: {
  projectId: string;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [repos, setRepos] = useState<GitRepo[] | null>(null);
  const [configs, setConfigs] = useState<Record<string, RepoConfig>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<GitRepo[]>(`/projects/${projectId}/git/repos`)
      .then((rs) => {
        setRepos(rs);
        const cfg: Record<string, RepoConfig> = {};
        for (const r of rs) {
          cfg[r.path] = { checked: true, branch: r.current_branch, days: 30, limit: 150 };
        }
        setConfigs(cfg);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Ошибка");
        setRepos([]);
      });
  }, [projectId]);

  function update(path: string, patch: Partial<RepoConfig>) {
    setConfigs((c) => ({ ...c, [path]: { ...c[path], ...patch } }));
  }

  const selectedCount = Object.values(configs).filter((c) => c.checked).length;

  async function start() {
    setBusy(true);
    setError("");
    try {
      await api(`/projects/${projectId}/git/import`, {
        method: "POST",
        body: JSON.stringify({
          repos: Object.entries(configs)
            .filter(([, c]) => c.checked)
            .map(([path, c]) => ({
              path,
              branch: c.branch || null,
              since_days: c.days || null,
              limit: c.limit,
            })),
        }),
      });
      onStarted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="card w-full max-w-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="font-medium">Импорт истории git</div>
        <div className="text-xs text-[var(--muted)] leading-relaxed">
          Выбери репозитории и настрой каждый: ветка, период, лимит коммитов. ИИ сгруппирует
          коммиты в выполненные работы: полностью совпадающие открытые задачи закроются,
          частично сделанные получат галочки на шагах плана. Уже импортированные коммиты
          пропускаются, свежие работы ложатся сверху колонки «Готово».
        </div>

        {repos === null ? (
          <div className="text-sm text-[var(--muted)]">Ищу репозитории…</div>
        ) : repos.length === 0 ? (
          <div className="text-sm text-[var(--muted)]">Git-репозитории не найдены</div>
        ) : (
          <div className="space-y-3">
            {repos.map((r) => {
              const c = configs[r.path];
              if (!c) return null;
              return (
                <div
                  key={r.path}
                  className={`border rounded-lg p-3 space-y-2.5 ${
                    c.checked ? "border-[var(--accent)]/50" : "border-[var(--border)] opacity-60"
                  }`}
                >
                  <label className="flex items-start gap-2.5 cursor-pointer">
                    <input
                      type="checkbox"
                      className="mt-1 accent-[var(--accent)] w-4 h-4"
                      checked={c.checked}
                      onChange={() => update(r.path, { checked: !c.checked })}
                    />
                    <div className="min-w-0">
                      <div className="text-sm font-mono font-medium truncate">
                        {r.path === "." ? "(корень проекта)" : r.path}
                      </div>
                      <div className="text-xs text-[var(--muted)]">
                        {r.total_commits} коммитов · последний: {r.last_commit || "—"}
                      </div>
                    </div>
                  </label>
                  {c.checked && (
                    <div className="flex gap-3 flex-wrap items-end pl-6">
                      <div className="space-y-1">
                        <div className="text-[11px] text-[var(--muted)]">Ветка</div>
                        <select
                          className="input !w-44 text-xs"
                          value={c.branch}
                          onChange={(e) => update(r.path, { branch: e.target.value })}
                        >
                          {[r.current_branch, ...r.branches.filter((b) => b !== r.current_branch)].map(
                            (b) => (
                              <option key={b} value={b}>
                                {b === r.current_branch ? `${b} (текущая)` : b}
                              </option>
                            )
                          )}
                        </select>
                      </div>
                      <div className="space-y-1">
                        <div className="text-[11px] text-[var(--muted)]">Период</div>
                        <div className="flex gap-1.5">
                          {PERIODS.map((p) => (
                            <button
                              key={p.days}
                              type="button"
                              onClick={() => update(r.path, { days: p.days })}
                              className={`chip cursor-pointer text-[11px] ${
                                c.days === p.days
                                  ? "!text-[var(--accent)] !border-[var(--accent)]"
                                  : "hover:border-[var(--accent)]"
                              }`}
                            >
                              {p.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="space-y-1">
                        <div className="text-[11px] text-[var(--muted)]">Лимит</div>
                        <input
                          type="number"
                          className="input !w-24 text-xs"
                          min={10}
                          max={1000}
                          value={c.limit}
                          onChange={(e) => update(r.path, { limit: Number(e.target.value) || 150 })}
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {error && <div className="text-sm text-red-400">{error}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
          <button className="btn" onClick={start} disabled={busy || selectedCount === 0}>
            {busy ? "…" : `Импортировать (${selectedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}

