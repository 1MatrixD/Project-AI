"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fmtDate } from "@/lib/api";
import { toast } from "@/components/Toast";
import { copyToClipboard, taskAsPrompt } from "@/lib/taskPrompt";
import type { Job, Task, TaskStatus } from "@/lib/types";

type TaskDetail = {
  files: { path: string; role: string | null; summary: string | null }[];
  worklog: { id: string; description: string; files: string[]; created_at: string }[];
};

const COLUMNS: { key: TaskStatus; label: string; accent: string }[] = [
  { key: "planned", label: "Запланировано", accent: "border-t-sky-500" },
  { key: "in_progress", label: "В работе", accent: "border-t-amber-500" },
  { key: "review", label: "Ревью", accent: "border-t-purple-500" },
  { key: "done", label: "Готово", accent: "border-t-emerald-500" },
];

const SOURCE_LABEL: Record<string, string> = {
  manual: "вручную",
  chat: "из чата ИИ",
  meeting: "из созвона",
  doc: "из документа",
  git: "из git",
  plan: "из плана",
};

/** Зависимости подзадачи, ещё не доведённые до «Готово». */
function openDeps(task: Task, all: Task[]): Task[] {
  return (task.extra?.depends_on ?? [])
    .map((id) => all.find((t) => t.id === id))
    .filter((t): t is Task => !!t && t.status !== "done" && t.status !== "cancelled");
}

const RELATION_LABEL: Record<string, string> = {
  duplicate: "дубликат",
  continuation: "продолжение",
  overlaps: "пересекается",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "уверенность высокая",
  medium: "уверенность средняя",
  low: "уверенность низкая",
};

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
    toast(
      enrich
        ? "Задача создана и отправлена на RLM-проработку — досье (где смотреть, нюансы, как проверить) появится через минуту-две."
        : "Задача добавлена."
    );
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
      toast("ИИ проверяет, какие задачи уже реализованы в коде — прогресс в шапке (⚙).");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Ошибка", "error");
    }
  }

  async function runEnrichAll() {
    try {
      const r = await api<{ job_id: string | null; tasks: number }>(
        `/projects/${projectId}/tasks/enrich`,
        { method: "POST", body: JSON.stringify({}) }
      );
      toast(
        r.tasks === 0
          ? "Непроработанных задач нет — все открытые карточки уже разобраны RLM."
          : `RLM-проработка запущена, задач: ${r.tasks}. Исследование кодовой базы → досье со ссылками на файлы.`
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Ошибка", "error");
    }
  }

  const selected = tasks.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="space-y-3 h-full flex flex-col">
      <div className="flex gap-2 items-center flex-wrap justify-end">
        <button className="btn btn-ghost" onClick={runEnrichAll} title="RLM-исследование кодовой базы для всех непроработанных задач">
          🧠 Проработать новые (RLM)
        </button>
        <button className="btn btn-ghost" onClick={runVerify}>
          🔍 Проверить, что уже сделано
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
                {col.label}
                <span className="chip">{colTasks.length}</span>
              </div>
              {colTasks.map((t) => {
                const waiting = t.status !== "done" ? openDeps(t, tasks) : [];
                const busy = busyIds.has(t.id);
                return (
                  <div
                    key={t.id}
                    draggable
                    onDragStart={() => setDragId(t.id)}
                    onClick={() => setSelectedId(t.id)}
                    className="border border-[var(--border)] bg-[var(--surface-2)] rounded-lg p-3 space-y-1.5 cursor-pointer hover:border-[var(--accent)]"
                  >
                    <div className="text-sm leading-snug">{t.title}</div>
                    <div className="flex gap-1.5 flex-wrap">
                      <span className="chip">{SOURCE_LABEL[t.source] ?? t.source}</span>
                      {t.plan.length > 0 && (
                        <span className="chip">план · {t.plan.length}</span>
                      )}
                      {busy ? (
                        <span
                          className="chip pulse text-[var(--accent)]"
                          title="Идёт RLM-проработка"
                        >
                          🧠 RLM
                        </span>
                      ) : (
                        t.extra?.enriched && (
                          <span className="chip text-[var(--accent-2)]">🧠 RLM</span>
                        )
                      )}
                      {t.extra?.planned && (
                        <span className="chip text-[var(--accent)]" title="Декомпозирована планировщиком на подзадачи">
                          🗂 {t.extra.subtasks?.length ?? 0} подзадач
                        </span>
                      )}
                      {waiting.length > 0 && (
                        <span
                          className="chip text-amber-300"
                          title={`Сначала: ${waiting.map((d) => d.title).join("; ")}`}
                        >
                          ⛓ ждёт {waiting.length}
                        </span>
                      )}
                      {t.extra?.duplicate_of && (
                        <span className="chip text-amber-300">дубликат?</span>
                      )}
                      {t.report?.startsWith("[ИИ-проверка]") && (
                        <span className="chip text-emerald-300">✓ ИИ-проверка</span>
                      )}
                    </div>
                  </div>
                );
              })}
              {colTasks.length === 0 && col.key !== "planned" && (
                <div className="text-xs text-[var(--muted)] text-center py-4">Пусто</div>
              )}
              {/* Постановка задачи живёт здесь, а не в шапке: длинный текст
                  разъезжался бы вместе с остальными кнопками доски. */}
              {col.key === "planned" && (
                <button
                  className="w-full text-sm text-[var(--muted)] hover:text-[var(--accent)] border border-dashed border-[var(--border)] hover:border-[var(--accent)] rounded-lg py-2"
                  onClick={() => setShowCreate(true)}
                >
                  + Задача
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
      setError(e instanceof Error ? e.message : "Ошибка");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="font-medium text-lg">Новая задача</div>
        <textarea
          ref={ref}
          className="input min-h-48 text-sm leading-relaxed"
          placeholder={
            "Задача своими словами — можно абзацем, длина не ограничена.\n\n" +
            "Не нужно искать файлы и формулировать инженерно: с проработкой ИИ сам " +
            "исследует кодовую базу и соберёт досье — где смотреть, нюансы, " +
            "как проверить и развилки, которые стоит решить до начала."
          }
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
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn btn-ghost" onClick={() => submit(false)} disabled={busy || !text.trim()}>
            Добавить
          </button>
          <button
            className="btn"
            onClick={() => submit(true)}
            disabled={busy || !text.trim()}
            title="Ctrl+Enter"
          >
            {busy ? "Создаю…" : "🧠 Добавить с проработкой"}
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
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
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
  }, [task.id, task.title, task.description]);

  useEffect(() => {
    setDetail(null);
    api<TaskDetail>(`/projects/${projectId}/tasks/${task.id}/detail`)
      .then(setDetail)
      .catch(() => {});
  }, [projectId, task.id, task.updated_at]);

  async function save() {
    await api(`/projects/${projectId}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title, description }),
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
      setInfo("Планировщик запущен: общий план и подзадачи с зависимостями появятся в «Запланировано».");
    } catch (e) {
      setInfo(e instanceof Error ? e.message : "Ошибка");
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
    if (!confirm("Удалить задачу?")) return;
    await api(`/projects/${projectId}/tasks/${task.id}`, { method: "DELETE" });
    onChanged();
  }

  async function copyPrompt() {
    const ok = await copyToClipboard(taskAsPrompt(task, projectName));
    setInfo(
      ok
        ? "Досье скопировано: где смотреть, нюансы, как проверить, развилки и файлы — можно вставлять в Claude Code."
        : "Не удалось скопировать — браузер отказал в доступе к буферу обмена."
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5 space-y-3 max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <input className="input font-medium" value={title} onChange={(e) => setTitle(e.target.value)} />
          <button
            className="btn btn-ghost whitespace-nowrap"
            onClick={enrich}
            disabled={enriching}
            title="RLM-исследование кодовой базы: досье — где смотреть, нюансы, как проверить"
          >
            🧠 {task.extra?.enriched ? "Переработать" : "Проработать"}
          </button>
          {task.status !== "done" && (
            <button
              className="btn btn-ghost whitespace-nowrap"
              onClick={decompose}
              title="Планировщик: ИИ построит общий план и разобьёт задачу на подзадачи с зависимостями"
            >
              🗂 {task.extra?.planned ? "Перепланировать" : "Декомпозировать"}
            </button>
          )}
          <div className="relative">
            <button
              className="btn btn-ghost px-2.5"
              onClick={() => setMenuOpen((v) => !v)}
              title="Ещё"
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
                    📋 Скопировать задачу
                  </button>
                  <button
                    className="w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-[var(--surface-2)] text-red-300"
                    onClick={() => {
                      setMenuOpen(false);
                      remove();
                    }}
                  >
                    Удалить задачу
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {info && <div className="text-sm text-[var(--accent)]">{info}</div>}

        {task.extra?.parent_title && (
          <div className="text-xs text-[var(--muted)]">
            Подзадача из декомпозиции:{" "}
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

        {task.extra?.duplicate_of && (
          <div className="text-sm text-amber-300">
            ⚠️ Возможный дубликат: «{task.extra.duplicate_of}»
          </div>
        )}

        {deps.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Зависит от</div>
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
          placeholder="Описание"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        {(task.extra?.reading || task.extra?.hypothesis?.text) && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Как понята задача</div>
            {task.extra?.reading && (
              <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
                {task.extra.reading}
              </div>
            )}
            {task.extra?.hypothesis?.text && (
              <div className="text-xs leading-relaxed">
                <span className="chip mr-1.5">
                  гипотеза · {CONFIDENCE_LABEL[task.extra.hypothesis.confidence] ?? task.extra.hypothesis.confidence}
                </span>
                {task.extra.hypothesis.text}
              </div>
            )}
          </div>
        )}

        {task.extra?.plan_summary && (
          <div className="space-y-1">
            <div className="text-sm font-medium">План решения</div>
            <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
              {task.extra.plan_summary}
            </div>
          </div>
        )}

        {subtasks.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              Подзадачи{" "}
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
            <div className="text-sm font-medium">План</div>
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
              Решить до начала{" "}
              <span className="text-xs font-normal text-[var(--muted)]">
                — ИИ намеренно не выбирал за тебя
              </span>
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
                  <div className="text-xs text-[var(--accent-2)]">склоняется к: {q.lean}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {(task.extra?.where_to_look?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              Где смотреть{" "}
              <span className="text-xs font-normal text-[var(--muted)]">
                — что проверить в каждом месте
              </span>
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
              Образец рядом{" "}
              <span className="text-xs font-normal text-[var(--muted)]">
                — где то же сделано правильно
              </span>
            </div>
            <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
              {task.extra.reference}
            </div>
          </div>
        )}

        {(task.extra?.impact?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">
              Нюансы{" "}
              <span className="text-xs font-normal text-[var(--muted)]">
                — что заденет работа
              </span>
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
              Как проверить{" "}
              <span className="text-xs font-normal text-[var(--muted)]">
                — что должно стать правдой
              </span>
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
              Файлы задачи{" "}
              <span className="text-[var(--muted)] font-normal text-xs">из карты знаний</span>
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
            <div className="text-sm font-medium">История работ</div>
            {detail!.worklog.map((w) => (
              <div key={w.id} className="border-l-2 border-[var(--border)] pl-3 space-y-0.5">
                <div className="text-[10px] text-[var(--muted)]">{fmtDate(w.created_at)}</div>
                <div className="text-xs leading-relaxed whitespace-pre-wrap">{w.description}</div>
                {w.files.length > 0 && (
                  <div className="text-[10px] text-[var(--muted)] font-mono break-all">
                    {w.files.slice(0, 8).join(", ")}
                    {w.files.length > 8 ? ` и ещё ${w.files.length - 8}` : ""}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {(task.extra?.related?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Связанные темы</div>
            {task.extra!.related!.map((r, i) => (
              <div key={i} className="text-xs text-[var(--muted)]">
                <span className="chip mr-1.5">{RELATION_LABEL[r.relation] ?? r.relation}</span>
                «{r.title}» — {r.note}
              </div>
            ))}
          </div>
        )}

        {task.report && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Отчёт</div>
            <ReportText text={task.report} />
          </div>
        )}

        {showDone ? (
          <div className="space-y-2">
            <textarea
              className="input min-h-20 text-sm"
              placeholder="Что сделано? Отчёт запустит обновление карты знаний."
              value={report}
              onChange={(e) => setReport(e.target.value)}
            />
            <div className="flex gap-2 justify-end">
              <button className="btn btn-ghost" onClick={() => setShowDone(false)}>Отмена</button>
              <button className="btn" onClick={markDone}>✓ Выполнено</button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2 justify-end">
            {task.status !== "done" && (
              <button className="btn btn-ghost" onClick={() => setShowDone(true)}>
                Пометить выполненной…
              </button>
            )}
            <button className="btn" onClick={save}>Сохранить</button>
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
