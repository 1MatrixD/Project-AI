"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useFmt } from "@/lib/format";
import { toast } from "@/components/Toast";
import { copyToClipboard, taskAsPrompt } from "@/lib/taskPrompt";
import type { Job, Task, TaskStatus } from "@/lib/types";

type TaskDetail = {
  files: { path: string; role: string | null; summary: string | null }[];
  worklog: { id: string; description: string; files: string[]; created_at: string }[];
};

const COLUMNS: { key: TaskStatus; accent: string }[] = [
  { key: "planned", accent: "border-t-sky-500" },
  { key: "in_progress", accent: "border-t-amber-500" },
  { key: "review", accent: "border-t-purple-500" },
  { key: "done", accent: "border-t-emerald-500" },
];

/** Зависимости подзадачи, ещё не доведённые до «Готово». */
function openDeps(task: Task, all: Task[]): Task[] {
  return (task.extra?.depends_on ?? [])
    .map((id) => all.find((t) => t.id === id))
    .filter((t): t is Task => !!t && t.status !== "done" && t.status !== "cancelled");
}

/** Подпись для карточки на доске. Длинное ТЗ целиком живёт в description —
 *  title остаётся коротким, иначе колонка канбана превращается в простыню. */
function shortTitle(text: string): string {
  const first = text.split("\n").find((l) => l.trim()) ?? text;
  const line = first.trim();
  if (line.length <= 120) return line.slice(0, 300);
  const cut = line.slice(0, 120);
  const space = cut.lastIndexOf(" ");
  return (space > 40 ? cut.slice(0, space) : cut) + "…";
}

export default function KanbanTab({
  projectId,
  projectName,
  refreshTick,
  jobs = [],
}: {
  projectId: string;
  projectName?: string;
  refreshTick: number;
  jobs?: Job[];
}) {
  const t = useTranslations("kanban");
  const tCommon = useTranslations("common");
  // Какие карточки прямо сейчас разбирает ИИ. Берём из параметров активных
  // job'ов: проработка идёт минутами, и без отметки на карточке непонятно,
  // почему описание не меняется.
  const busyIds = useMemo(() => {
    const ids = new Set<string>();
    for (const j of jobs) {
      if (j.status !== "running" && j.status !== "queued") continue;
      if (j.type !== "enrich_tasks" && j.type !== "plan_task") continue;
      for (const id of j.params?.task_ids ?? []) ids.add(id);
      if (j.params?.task_id) ids.add(j.params.task_id);
    }
    return ids;
  }, [jobs]);

  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    try {
      setTasks(await api<Task[]>(`/projects/${projectId}/tasks`));
    } catch {}
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshTick]);

  async function createTask(text: string, enrich: boolean) {
    // Короткий однострочный ввод ведёт себя как раньше; длинное ТЗ целиком
    // уходит в description, а на карточке остаётся усечённый заголовок.
    const title = shortTitle(text);
    await api(`/projects/${projectId}/tasks`, {
      method: "POST",
      body: JSON.stringify({ title, description: title === text ? "" : text, enrich }),
    });
    setShowCreate(false);
    toast(enrich ? t("createdEnrich") : t("created"));
    load();
  }

  async function drop(status: TaskStatus) {
    if (!dragId) return;
    const task = tasks.find((t) => t.id === dragId);
    setDragId(null);
    if (!task || task.status === status) return;
    setTasks((ts) => ts.map((t) => (t.id === task.id ? { ...t, status } : t)));
    await api(`/projects/${projectId}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    load();
  }

  async function runVerify() {
    try {
      await api(`/projects/${projectId}/tasks/verify`, { method: "POST" });
      toast(t("verifyStarted"));
    } catch (e) {
      toast(e instanceof Error ? e.message : tCommon("error"), "error");
    }
  }

  async function runEnrichAll() {
    try {
      const r = await api<{ job_id: string | null; tasks: number }>(
        `/projects/${projectId}/tasks/enrich`,
        { method: "POST", body: JSON.stringify({}) }
      );
      toast(r.tasks === 0 ? t("enrichNone") : t("enrichStarted", { count: r.tasks }));
    } catch (e) {
      toast(e instanceof Error ? e.message : tCommon("error"), "error");
    }
  }

  const sourceLabel = (s: string) => (t.has(`source.${s}`) ? t(`source.${s}`) : s);
  const selected = tasks.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="space-y-3 h-full flex flex-col">
      <div className="flex gap-2 items-center flex-wrap justify-end">
        <button className="btn btn-ghost" onClick={runEnrichAll} title={t("enrichAllTitle")}>
          {t("enrichAll")}
        </button>
        <button className="btn btn-ghost" onClick={runVerify}>
          {t("verify")}
        </button>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 flex-1 min-h-0 items-start">
        {COLUMNS.map((col) => {
          const colTasks = tasks.filter((t) => t.status === col.key);
          return (
            <div
              key={col.key}
              className={`card border-t-2 ${col.accent} p-3 space-y-2 max-h-full overflow-y-auto`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => drop(col.key)}
            >
              <div className="flex justify-between items-center text-sm font-medium">
                {t(`columns.${col.key}`)}
                <span className="chip">{colTasks.length}</span>
              </div>
              {colTasks.map((task) => {
                const waiting = task.status !== "done" ? openDeps(task, tasks) : [];
                const busy = busyIds.has(task.id);
                return (
                  <div
                    key={task.id}
                    draggable
                    onDragStart={() => setDragId(task.id)}
                    onClick={() => setSelectedId(task.id)}
                    className="border border-[var(--border)] bg-[var(--surface-2)] rounded-lg p-3 space-y-1.5 cursor-pointer hover:border-[var(--accent)]"
                  >
                    <div className="text-sm leading-snug">{task.title}</div>
                    <div className="flex gap-1.5 flex-wrap">
                      <span className="chip">{sourceLabel(task.source)}</span>
                      {task.plan.length > 0 && (
                        <span className="chip">{t("planChip", { count: task.plan.length })}</span>
                      )}
                      {busy ? (
                        <span className="chip pulse text-[var(--accent)]" title={t("busyTitle")}>
                          🧠 RLM
                        </span>
                      ) : (
                        task.extra?.enriched && (
                          <span className="chip text-[var(--accent-2)]">🧠 RLM</span>
                        )
                      )}
                      {task.extra?.planned && (
                        <span className="chip text-[var(--accent)]" title={t("plannedTitle")}>
                          {t("subtasksChip", { count: task.extra.subtasks?.length ?? 0 })}
                        </span>
                      )}
                      {waiting.length > 0 && (
                        <span
                          className="chip text-amber-300"
                          title={t("waitingTitle", { titles: waiting.map((d) => d.title).join("; ") })}
                        >
                          {t("waitingChip", { count: waiting.length })}
                        </span>
                      )}
                      {task.extra?.duplicate_of && (
                        <span className="chip text-amber-300">{t("duplicateChip")}</span>
                      )}
                      {/^\[(ИИ-проверка|AI check)\]/.test(task.report ?? "") && (
                        <span className="chip text-emerald-300">{t("verifiedChip")}</span>
                      )}
                    </div>
                  </div>
                );
              })}
              {colTasks.length === 0 && col.key !== "planned" && (
                <div className="text-xs text-[var(--muted)] text-center py-4">{t("empty")}</div>
              )}
              {/* Постановка задачи живёт здесь, а не в шапке: длинный текст
                  разъезжался бы вместе с остальными кнопками доски. */}
              {col.key === "planned" && (
                <button
                  className="w-full text-sm text-[var(--muted)] hover:text-[var(--accent)] border border-dashed border-[var(--border)] hover:border-[var(--accent)] rounded-lg py-2"
                  onClick={() => setShowCreate(true)}
                >
                  {t("addTask")}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {showCreate && (
        <CreateTaskModal onClose={() => setShowCreate(false)} onCreate={createTask} />
      )}

      {selected && (
        <TaskModal
          projectId={projectId}
          projectName={projectName}
          task={selected}
          allTasks={tasks}
          onOpenTask={(id) => setSelectedId(id)}
          onClose={() => setSelectedId(null)}
          onChanged={(keepOpen) => {
            if (!keepOpen) setSelectedId(null);
            load();
          }}
        />
      )}
    </div>
  );
}

/** Постановка задачи: полноценный textarea без ограничения по длине.
 *  «Добавить» кладёт карточку как есть, «с проработкой» сразу отправляет её
 *  в RLM — исследование кодовой базы, описание со ссылками на файлы и план. */
function CreateTaskModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (text: string, enrich: boolean) => Promise<void>;
}) {
  const t = useTranslations("kanban.create");
  const tCommon = useTranslations("common");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  async function submit(enrich: boolean) {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    try {
      await onCreate(value, enrich);
    } catch (e) {
      setError(e instanceof Error ? e.message : tCommon("error"));
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="font-medium text-lg">{t("title")}</div>
        <textarea
          ref={ref}
          className="input min-h-48 text-sm leading-relaxed"
          placeholder={t("placeholder")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              submit(true);
            }
          }}
        />
        {error && <div className="text-sm text-red-400">{error}</div>}
        <div className="flex justify-end gap-2 items-center">
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>{tCommon("cancel")}</button>
          <button className="btn btn-ghost" onClick={() => submit(false)} disabled={busy || !text.trim()}>
            {t("add")}
          </button>
          <button
            className="btn"
            onClick={() => submit(true)}
            disabled={busy || !text.trim()}
            title="Ctrl+Enter"
          >
            {busy ? t("creating") : t("addEnrich")}
          </button>
        </div>
      </div>
    </div>
  );
}

function TaskModal({
  projectId,
  projectName,
  task,
  allTasks,
  onOpenTask,
  onClose,
  onChanged,
}: {
  projectId: string;
  projectName?: string;
  task: Task;
  allTasks: Task[];
  onOpenTask: (id: string) => void;
  onClose: () => void;
  onChanged: (keepOpen?: boolean) => void;
}) {
  const t = useTranslations("kanban.modal");
  const tKanban = useTranslations("kanban");
  const tCommon = useTranslations("common");
  const tPrompt = useTranslations("taskPrompt");
  const fmt = useFmt();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [notes, setNotes] = useState(task.extra?.notes ?? "");
  const [report, setReport] = useState("");
  const [showDone, setShowDone] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [info, setInfo] = useState("");
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const byId = (id: string) => allTasks.find((t) => t.id === id);
  const deps = (task.extra?.depends_on ?? []).map(byId).filter((t): t is Task => !!t);
  const subtasks = (task.extra?.subtasks ?? []).map(byId).filter((t): t is Task => !!t);

  useEffect(() => {
    setTitle(task.title);
    setDescription(task.description);
    setNotes(task.extra?.notes ?? "");
  }, [task.id, task.title, task.description, task.extra?.notes]);

  useEffect(() => {
    setDetail(null);
    api<TaskDetail>(`/projects/${projectId}/tasks/${task.id}/detail`)
      .then(setDetail)
      .catch(() => {});
  }, [projectId, task.id, task.updated_at]);

  async function save() {
    await api(`/projects/${projectId}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title, description, notes }),
    });
    onChanged();
  }

  async function enrich() {
    setEnriching(true);
    try {
      await api(`/projects/${projectId}/tasks/${task.id}/enrich`, { method: "POST" });
    } finally {
      setEnriching(false);
      onChanged(true);
    }
  }

  async function decompose() {
    setInfo("");
    try {
      await api(`/projects/${projectId}/tasks/${task.id}/plan`, { method: "POST" });
      setInfo(t("plannerStarted"));
    } catch (e) {
      setInfo(e instanceof Error ? e.message : tCommon("error"));
    }
    onChanged(true);
  }

  async function markDone() {
    if (!report.trim()) return;
    await api(`/projects/${projectId}/tasks/${task.id}/done`, {
      method: "POST",
      body: JSON.stringify({ report, files: [] }),
    });
    onChanged();
  }

  async function remove() {
    if (!confirm(t("confirmDelete"))) return;
    await api(`/projects/${projectId}/tasks/${task.id}`, { method: "DELETE" });
    onChanged();
  }

  async function copyPrompt() {
    const ok = await copyToClipboard(taskAsPrompt(task, tPrompt, projectName));
    setInfo(ok ? t("copied") : t("copyFailed"));
  }

  const relationLabel = (r: string) => (tKanban.has(`relation.${r}`) ? tKanban(`relation.${r}`) : r);
  const confidenceLabel = (c: string) => (tKanban.has(`confidence.${c}`) ? tKanban(`confidence.${c}`) : c);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5 space-y-3 max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <input className="input font-medium" value={title} onChange={(e) => setTitle(e.target.value)} />
          <button
            className="btn btn-ghost whitespace-nowrap"
            onClick={enrich}
            disabled={enriching}
            title={t("enrichTitle")}
          >
            🧠 {task.extra?.enriched ? t("reEnrich") : t("enrich")}
          </button>
          {task.status !== "done" && (
            <button
              className="btn btn-ghost whitespace-nowrap"
              onClick={decompose}
              title={t("decomposeTitle")}
            >
              🗂 {task.extra?.planned ? t("replan") : t("decompose")}
            </button>
          )}
          <div className="relative">
            <button
              className="btn btn-ghost px-2.5"
              onClick={() => setMenuOpen((v) => !v)}
              title={tCommon("more")}
            >
              ⋯
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-[55]" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-full mt-1 z-[56] card p-1 w-56 shadow-xl">
                  <button
                    className="w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                    onClick={() => {
                      setMenuOpen(false);
                      copyPrompt();
                    }}
                  >
                    {t("copy")}
                  </button>
                  <button
                    className="w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-[var(--surface-2)] text-red-300"
                    onClick={() => {
                      setMenuOpen(false);
                      remove();
                    }}
                  >
                    {t("deleteTask")}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {info && <div className="text-sm text-[var(--accent)]">{info}</div>}

        {task.extra?.parent_title && (
          <div className="text-xs text-[var(--muted)]">
            {t("subtaskOf")}{" "}
            {task.extra.parent_task && byId(task.extra.parent_task) ? (
              <button
                className="text-[var(--accent)] hover:underline"
                onClick={() => onOpenTask(task.extra!.parent_task!)}
              >
                «{task.extra.parent_title}»
              </button>
            ) : (
              <>«{task.extra.parent_title}»</>
            )}
          </div>
        )}

        {task.extra?.from_material && (
          <div className="text-xs text-[var(--muted)]">
            {t("fromMaterial", { name: task.extra.from_material.filename })}
            {(task.extra.updated_by_materials?.length ?? 0) > 0 &&
              t("clarifiedBy", {
                names: task.extra.updated_by_materials!.map((m) => `«${m.filename}»`).join(", "),
              })}
          </div>
        )}

        {task.extra?.duplicate_of && (
          <div className="text-sm text-amber-300">
            {t("duplicateOf", { title: task.extra.duplicate_of })}
          </div>
        )}

        {deps.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">{t("dependsOn")}</div>
            {deps.map((d) => (
              <button
                key={d.id}
                className="flex items-center gap-2 text-xs w-full text-left px-2 py-1 -mx-2 rounded-lg hover:bg-[var(--surface-2)]"
                onClick={() => onOpenTask(d.id)}
              >
                <span>{d.status === "done" ? "✅" : "⏳"}</span>
                <span className={d.status === "done" ? "text-[var(--muted)] line-through" : ""}>
                  {d.title}
                </span>
              </button>
            ))}
          </div>
        )}

        <textarea
          className="input min-h-36 text-sm leading-relaxed"
          placeholder={t("description")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        {/* Прямая речь людей: проработка это читает и никогда не перезаписывает,
            в отличие от описания, которое она пересобирает целиком. */}
        <div className="space-y-1">
          <div className="text-sm font-medium">
            {t("notes")}{" "}
            <span className="text-xs font-normal text-[var(--muted)]">{t("notesHint")}</span>
          </div>
          <textarea
            className="input min-h-20 text-sm leading-relaxed"
            placeholder={t("notesPlaceholder")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        {(task.extra?.clarifications?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("clarifications")}{" "}
              <span className="text-xs font-normal text-[var(--muted)]">{t("clarificationsHint")}</span>
            </div>
            {task.extra!.clarifications!.map((c, i) => (
              <div
                key={i}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2.5 space-y-1"
              >
                <div className="text-[10px] text-[var(--muted)] font-mono">{c.source}</div>
                <div className="text-xs leading-relaxed whitespace-pre-wrap">{c.text}</div>
              </div>
            ))}
          </div>
        )}

        {(task.extra?.reading || task.extra?.hypothesis?.text) && (
          <div className="space-y-1">
            <div className="text-sm font-medium">{t("reading")}</div>
            {task.extra?.reading && (
              <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
                {task.extra.reading}
              </div>
            )}
            {task.extra?.hypothesis?.text && (
              <div className="text-xs leading-relaxed">
                <span className="chip mr-1.5">
                  {t("hypothesis")} · {confidenceLabel(task.extra.hypothesis.confidence)}
                </span>
                {task.extra.hypothesis.text}
              </div>
            )}
          </div>
        )}

        {task.extra?.plan_summary && (
          <div className="space-y-1">
            <div className="text-sm font-medium">{t("planSummary")}</div>
            <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
              {task.extra.plan_summary}
            </div>
          </div>
        )}

        {subtasks.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("subtasks")}{" "}
              <span className="text-[var(--muted)] font-normal">
                {subtasks.filter((s) => s.status === "done").length}/{subtasks.length}
              </span>
            </div>
            {subtasks.map((s) => (
              <button
                key={s.id}
                className="flex items-center gap-2 text-xs w-full text-left px-2 py-1 -mx-2 rounded-lg hover:bg-[var(--surface-2)]"
                onClick={() => onOpenTask(s.id)}
              >
                <span>{s.status === "done" ? "✅" : s.status === "in_progress" ? "🔧" : "▫️"}</span>
                <span className={s.status === "done" ? "text-[var(--muted)] line-through" : ""}>
                  {s.title}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* План без чекбоксов: их состояние ничем не читалось — декорация.
            Блок остаётся ради старых карточек и подзадач планировщика,
            новые проработки план не заполняют. */}
        {task.plan.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">{t("plan")}</div>
            <ol className="text-sm space-y-1 list-decimal list-inside">
              {task.plan.map((p, i) => (
                <li key={i} className="leading-relaxed">{p.text}</li>
              ))}
            </ol>
          </div>
        )}

        {(task.extra?.open_questions?.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <div className="text-sm font-medium">
              {t("openQuestions")}{" "}
              <span className="text-xs font-normal text-[var(--muted)]">{t("openQuestionsHint")}</span>
            </div>
            {task.extra!.open_questions!.map((q, i) => (
              <div
                key={i}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2.5 space-y-1"
              >
                <div className="text-sm">{q.question}</div>
                <ul className="text-xs text-[var(--muted)] space-y-0.5">
                  {q.options.map((o, j) => (
                    <li key={j}>— {o}</li>
                  ))}
                </ul>
                {q.lean && (
                  <div className="text-xs text-[var(--accent-2)]">{t("lean", { lean: q.lean })}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {(task.extra?.where_to_look?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("whereToLook")}{" "}
              <span className="text-xs font-normal text-[var(--muted)]">{t("whereToLookHint")}</span>
            </div>
            <ul className="text-xs space-y-1">
              {task.extra!.where_to_look!.map((w, idx) => (
                <li key={idx} className="leading-relaxed">
                  <code className="text-[var(--accent)] font-mono break-all">{w.path}</code>
                  <span className="text-[var(--muted)]"> — {w.why}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {task.extra?.reference && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("reference")}{" "}
              <span className="text-xs font-normal text-[var(--muted)]">{t("referenceHint")}</span>
            </div>
            <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
              {task.extra.reference}
            </div>
          </div>
        )}

        {(task.extra?.impact?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("impact")}{" "}
              <span className="text-xs font-normal text-[var(--muted)]">{t("impactHint")}</span>
            </div>
            <ul className="text-xs space-y-1">
              {task.extra!.impact!.map((i, idx) => (
                <li key={idx}>
                  <span className="font-mono">{i.what}</span>
                  <span className="text-[var(--muted)]"> — {i.why}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(task.extra?.how_to_verify?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("howToVerify")}{" "}
              <span className="text-xs font-normal text-[var(--muted)]">{t("howToVerifyHint")}</span>
            </div>
            <ul className="text-xs space-y-1">
              {task.extra!.how_to_verify!.map((v, idx) => (
                <li key={idx} className="leading-relaxed">
                  {v.what}
                  <span className="text-[var(--muted)]"> — {v.how}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(detail ? detail.files.length > 0 : (task.extra?.files?.length ?? 0) > 0) && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              {t("files")}{" "}
              <span className="text-[var(--muted)] font-normal text-xs">{t("filesHint")}</span>
            </div>
            <div className="flex flex-col gap-1">
              {detail
                ? detail.files.slice(0, 15).map((f) => (
                    <div key={f.path} className="text-xs leading-relaxed">
                      <code className="text-[var(--accent)] font-mono break-all">{f.path}</code>
                      {f.role && <span className="text-[var(--muted)]"> — {f.role}</span>}
                    </div>
                  ))
                : task.extra!.files!.slice(0, 12).map((f) => (
                    <code key={f} className="text-xs text-[var(--accent)] font-mono break-all">{f}</code>
                  ))}
            </div>
          </div>
        )}

        {(detail?.worklog.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <div className="text-sm font-medium">{t("worklog")}</div>
            {detail!.worklog.map((w) => (
              <div key={w.id} className="border-l-2 border-[var(--border)] pl-3 space-y-0.5">
                <div className="text-[10px] text-[var(--muted)]">{fmt.date(w.created_at)}</div>
                <div className="text-xs leading-relaxed whitespace-pre-wrap">{w.description}</div>
                {w.files.length > 0 && (
                  <div className="text-[10px] text-[var(--muted)] font-mono break-all">
                    {w.files.slice(0, 8).join(", ")}
                    {w.files.length > 8 ? ` ${t("moreFiles", { count: w.files.length - 8 })}` : ""}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {(task.extra?.related?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">{t("related")}</div>
            {task.extra!.related!.map((r, i) => (
              <div key={i} className="text-xs text-[var(--muted)]">
                <span className="chip mr-1.5">{relationLabel(r.relation)}</span>
                «{r.title}» — {r.note}
              </div>
            ))}
          </div>
        )}

        {task.report && (
          <div className="space-y-1">
            <div className="text-sm font-medium">{t("report")}</div>
            <ReportText text={task.report} />
          </div>
        )}

        {showDone ? (
          <div className="space-y-2">
            <textarea
              className="input min-h-20 text-sm"
              placeholder={t("donePlaceholder")}
              value={report}
              onChange={(e) => setReport(e.target.value)}
            />
            <div className="flex gap-2 justify-end">
              <button className="btn btn-ghost" onClick={() => setShowDone(false)}>{tCommon("cancel")}</button>
              <button className="btn" onClick={markDone}>{t("markDone")}</button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2 justify-end">
            {task.status !== "done" && (
              <button className="btn btn-ghost" onClick={() => setShowDone(true)}>
                {t("markDoneOpen")}
              </button>
            )}
            <button className="btn" onClick={save}>{tCommon("save")}</button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Отчёт: строки с ✓/✗/− рендерим как чек-статусы. */
function ReportText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="text-sm text-[var(--muted)] border border-[var(--border)] rounded-lg p-3 space-y-0.5">
      {lines.map((line, i) => {
        const m = line.match(/^\s*[-•]?\s*([✓✔✗✘×+-])\s+(.*)$/);
        if (m) {
          const ok = "✓✔+".includes(m[1]);
          return (
            <div key={i} className="flex gap-2 items-start">
              <span className={ok ? "text-emerald-300" : "text-red-300"}>{ok ? "✅" : "❌"}</span>
              <span>{m[2]}</span>
            </div>
          );
        }
        return line.trim() ? (
          <div key={i} className="whitespace-pre-wrap">{line}</div>
        ) : (
          <div key={i} className="h-1.5" />
        );
      })}
    </div>
  );
}
