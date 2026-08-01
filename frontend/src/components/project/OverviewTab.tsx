"use client";

import { useCallback, useEffect, useState } from "react";
import { api, fmtDate } from "@/lib/api";
import type { ChangeReport, Decision, Job, Project } from "@/lib/types";
import StatusBadge from "@/components/StatusBadge";

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
  const [autoContinue, setAutoContinue] = useState(true);
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

  const lastJob = jobs.find((j) => j.type === "index");

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2 space-y-4">
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="font-medium">О проекте</div>
            <div className="flex gap-2 flex-wrap items-center">
              <label
                className="flex items-center gap-1.5 text-xs text-[var(--muted)] cursor-pointer select-none"
                title="После каждого прогона автоматически продолжать ИИ-анализ, пока бэклог не опустеет"
              >
                <input
                  type="checkbox"
                  checked={autoContinue}
                  onChange={(e) => setAutoContinue(e.target.checked)}
                />
                до конца бэклога
              </label>
              <button className="btn btn-ghost text-sm" onClick={() => runIndex("update")}>
                ⟳ Обновить индекс
              </button>
              <button className="btn btn-ghost text-sm" onClick={() => runIndex("reverify")}>
                ⟲ Перепроверить всё
              </button>
              <button
                className="btn btn-ghost text-sm"
                title="Разобрать историю коммитов (включая вложенные репо) в задачи канбана"
                onClick={() => setShowGitImport(true)}
              >
                ⎇ Импорт из git
              </button>
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
            <p className="text-sm text-[var(--muted)] whitespace-pre-wrap leading-relaxed">{overview.conventions}</p>
          </div>
        ) : null}
      </div>

      <div className="space-y-4">
        <DecisionsCard projectId={project.id} />
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

const DECISION_SOURCE: Record<string, string> = {
  manual: "вручную",
  meeting: "с созвона",
  doc: "из документа",
  chat: "из чата",
};

/** Соглашения проекта: актуальные решения и смены подходов — защита ИИ от ложных «багов». */
function DecisionsCard({ projectId }: { projectId: string }) {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback(async () => {
    try {
      setDecisions(await api<Decision[]>(`/projects/${projectId}/decisions`));
    } catch {}
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!topic.trim() || !text.trim()) return;
    await api(`/projects/${projectId}/decisions`, {
      method: "POST",
      body: JSON.stringify({ topic: topic.trim(), text: text.trim() }),
    });
    setTopic("");
    setText("");
    setShowAdd(false);
    load();
  }

  async function remove(id: string) {
    if (!confirm("Удалить соглашение?")) return;
    await api(`/projects/${projectId}/decisions/${id}`, { method: "DELETE" });
    load();
  }

  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">Соглашения проекта</div>
        <button className="btn btn-ghost text-sm" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? "✕" : "+ Добавить"}
        </button>
      </div>
      <div className="text-xs text-[var(--muted)]">
        Актуальные решения и смены подходов («раньше X, теперь Y»). ИИ сверяется с ними в
        проработке и проверках — код, противоречащий соглашению, считается легаси, а не багом.
      </div>
      {showAdd && (
        <form onSubmit={add} className="space-y-2">
          <input
            className="input"
            placeholder="Тема (например: Роли в админке)"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <textarea
            className="input min-h-16 text-sm"
            placeholder="Актуальное решение…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn w-full justify-center text-sm">Сохранить</button>
        </form>
      )}
      {decisions.length === 0 ? (
        <div className="text-sm text-[var(--muted)]">
          Пока нет — добавь вручную, попроси ИИ в чате зафиксировать (record_decision) или
          загрузи созвон: решения извлекаются автоматически.
        </div>
      ) : (
        decisions.map((d) => (
          <div key={d.id} className="border border-[var(--border)] rounded-lg p-3 space-y-1 group">
            <div className="flex justify-between gap-2">
              <div className="text-sm font-medium">{d.topic}</div>
              <button
                className="text-[var(--muted)] hover:text-red-300 opacity-0 group-hover:opacity-100 text-xs"
                onClick={() => remove(d.id)}
              >
                ✕
              </button>
            </div>
            <div className="text-xs text-[var(--muted)] whitespace-pre-wrap leading-relaxed">{d.text}</div>
            <div className="text-[10px] text-[var(--muted)]">
              {DECISION_SOURCE[d.source] ?? d.source} · {fmtDate(d.updated_at)}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
