"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PlanStep, Task, TaskStatus } from "@/lib/types";

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
};

const RELATION_LABEL: Record<string, string> = {
  duplicate: "дубликат",
  continuation: "продолжение",
  overlaps: "пересекается",
};

export default function KanbanTab({
  projectId,
  refreshTick,
}: {
  projectId: string;
  refreshTick: number;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      setTasks(await api<Task[]>(`/projects/${projectId}/tasks`));
    } catch {}
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshTick]);

  async function createTask(e: React.FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    await api(`/projects/${projectId}/tasks`, {
      method: "POST",
      body: JSON.stringify({ title: newTitle.trim(), enrich: true }),
    });
    setNewTitle("");
    setNotice("Задача создана и отправлена на RLM-проработку — описание и план появятся через минуту-две.");
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
    setNotice("");
    try {
      await api(`/projects/${projectId}/tasks/verify`, { method: "POST" });
      setNotice("ИИ проверяет, какие задачи уже реализованы в коде — прогресс сверху.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Ошибка");
    }
  }

  async function runEnrichAll() {
    setNotice("");
    try {
      await api(`/projects/${projectId}/tasks/enrich`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setNotice("RLM-проработка всех новых задач запущена: исследование кодовой базы → детальные описания и планы со ссылками на файлы.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Ошибка");
    }
  }

  const selected = tasks.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="space-y-3 h-full flex flex-col">
      <div className="flex gap-2 items-center flex-wrap">
        <form onSubmit={createTask} className="flex gap-2 flex-1 min-w-64">
          <input
            className="input"
            placeholder="Короткая задача — ИИ сам проработает её по кодовой базе…"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <button className="btn whitespace-nowrap">+ С проработкой</button>
        </form>
        <button className="btn btn-ghost" onClick={runEnrichAll} title="RLM-исследование кодовой базы для всех непроработанных задач">
          🧠 Проработать новые (RLM)
        </button>
        <button className="btn btn-ghost" onClick={runVerify}>
          🔍 Проверить, что уже сделано
        </button>
      </div>
      {notice && <div className="text-sm text-[var(--accent)]">{notice}</div>}

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
                const planDone = t.plan.filter((p) => p.done).length;
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
                        <span className="chip">
                          план {planDone}/{t.plan.length}
                        </span>
                      )}
                      {t.extra?.enriched && (
                        <span className="chip text-[var(--accent-2)]">🧠 RLM</span>
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
              {colTasks.length === 0 && (
                <div className="text-xs text-[var(--muted)] text-center py-4">Пусто</div>
              )}
            </div>
          );
        })}
      </div>

      {selected && (
        <TaskModal
          projectId={projectId}
          task={selected}
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

function TaskModal({
  projectId,
  task,
  onClose,
  onChanged,
}: {
  projectId: string;
  task: Task;
  onClose: () => void;
  onChanged: (keepOpen?: boolean) => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [report, setReport] = useState("");
  const [showDone, setShowDone] = useState(false);
  const [enriching, setEnriching] = useState(false);

  useEffect(() => {
    setTitle(task.title);
    setDescription(task.description);
  }, [task.id, task.title, task.description]);

  async function save() {
    await api(`/projects/${projectId}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title, description }),
    });
    onChanged();
  }

  async function togglePlanStep(index: number) {
    const plan: PlanStep[] = task.plan.map((p, i) =>
      i === index ? { ...p, done: !p.done } : p
    );
    await api(`/projects/${projectId}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ plan }),
    });
    onChanged(true);
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

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5 space-y-3 max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <input className="input font-medium" value={title} onChange={(e) => setTitle(e.target.value)} />
          <button
            className="btn btn-ghost whitespace-nowrap"
            onClick={enrich}
            disabled={enriching}
            title="RLM-исследование кодовой базы: детальное описание и план со ссылками на файлы"
          >
            🧠 {task.extra?.enriched ? "Переработать" : "Проработать"}
          </button>
        </div>

        {task.extra?.duplicate_of && (
          <div className="text-sm text-amber-300">
            ⚠️ Возможный дубликат: «{task.extra.duplicate_of}»
          </div>
        )}

        <textarea
          className="input min-h-36 text-sm leading-relaxed"
          placeholder="Описание"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        {task.plan.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-sm font-medium">
              План{" "}
              <span className="text-[var(--muted)] font-normal">
                {task.plan.filter((p) => p.done).length}/{task.plan.length}
              </span>
            </div>
            {task.plan.map((p, i) => (
              <label
                key={i}
                className="flex items-start gap-2.5 text-sm cursor-pointer group border border-transparent hover:border-[var(--border)] rounded-lg px-2 py-1.5 -mx-2"
              >
                <input
                  type="checkbox"
                  checked={p.done}
                  onChange={() => togglePlanStep(i)}
                  className="mt-0.5 accent-[var(--accent)]"
                />
                <span className={p.done ? "line-through text-[var(--muted)]" : ""}>{p.text}</span>
              </label>
            ))}
          </div>
        )}

        {(task.extra?.files?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Ключевые файлы</div>
            <div className="flex flex-col gap-0.5">
              {task.extra!.files!.slice(0, 12).map((f) => (
                <code key={f} className="text-xs text-[var(--accent)] font-mono break-all">{f}</code>
              ))}
            </div>
          </div>
        )}

        {(task.extra?.related?.length ?? 0) > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Связанные задачи</div>
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
          <div className="flex gap-2 justify-between">
            <button className="btn btn-ghost text-red-300" onClick={remove}>Удалить</button>
            <div className="flex gap-2">
              {task.status !== "done" && (
                <button className="btn btn-ghost" onClick={() => setShowDone(true)}>
                  Пометить выполненной…
                </button>
              )}
              <button className="btn" onClick={save}>Сохранить</button>
            </div>
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
