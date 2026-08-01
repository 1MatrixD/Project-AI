"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Task, TaskStatus } from "@/lib/types";

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

export default function KanbanTab({
  projectId,
  refreshTick,
}: {
  projectId: string;
  refreshTick: number;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Task | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [verifyBusy, setVerifyBusy] = useState(false);
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
      body: JSON.stringify({ title: newTitle.trim() }),
    });
    setNewTitle("");
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
    setVerifyBusy(true);
    setNotice("");
    try {
      await api(`/projects/${projectId}/tasks/verify`, { method: "POST" });
      setNotice("ИИ проверяет, какие задачи уже реализованы в коде — следи за прогрессом сверху.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setVerifyBusy(false);
    }
  }

  return (
    <div className="space-y-3 h-full flex flex-col">
      <div className="flex gap-2 items-center flex-wrap">
        <form onSubmit={createTask} className="flex gap-2 flex-1 min-w-64">
          <input
            className="input"
            placeholder="Новая задача…"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <button className="btn whitespace-nowrap">Добавить</button>
        </form>
        <button className="btn btn-ghost" onClick={runVerify} disabled={verifyBusy}>
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
              {colTasks.map((t) => (
                <div
                  key={t.id}
                  draggable
                  onDragStart={() => setDragId(t.id)}
                  onClick={() => setSelected(t)}
                  className="border border-[var(--border)] bg-[var(--surface-2)] rounded-lg p-3 space-y-1.5 cursor-pointer hover:border-[var(--accent)]"
                >
                  <div className="text-sm leading-snug">{t.title}</div>
                  <div className="flex gap-1.5 flex-wrap">
                    <span className="chip">{SOURCE_LABEL[t.source] ?? t.source}</span>
                    {t.plan.length > 0 && <span className="chip">план: {t.plan.length} шагов</span>}
                    {t.report?.startsWith("[ИИ-проверка]") && (
                      <span className="chip text-emerald-300">✓ ИИ-проверка</span>
                    )}
                  </div>
                </div>
              ))}
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
          onClose={() => setSelected(null)}
          onChanged={() => {
            setSelected(null);
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
  onChanged: () => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [report, setReport] = useState("");
  const [showDone, setShowDone] = useState(false);

  async function save() {
    await api(`/projects/${projectId}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title, description }),
    });
    onChanged();
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
      <div className="card w-full max-w-xl p-5 space-y-3 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <input className="input font-medium" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea
          className="input min-h-32 text-sm"
          placeholder="Описание"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        {task.plan.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium">План</div>
            <ol className="list-decimal list-inside text-sm text-[var(--muted)] space-y-0.5">
              {task.plan.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </div>
        )}
        {task.report && (
          <div className="space-y-1">
            <div className="text-sm font-medium">Отчёт</div>
            <div className="text-sm text-[var(--muted)] whitespace-pre-wrap border border-[var(--border)] rounded-lg p-3">
              {task.report}
            </div>
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
