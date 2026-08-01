"use client";

const MAP: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  created: { label: "Создан", cls: "text-sky-300 border-sky-800" },
  indexing: { label: "Индексация…", cls: "text-amber-300 border-amber-800", pulse: true },
  ready: { label: "Готов", cls: "text-emerald-300 border-emerald-800" },
  error: { label: "Ошибка", cls: "text-red-300 border-red-800" },
  queued: { label: "В очереди", cls: "text-sky-300 border-sky-800" },
  running: { label: "Выполняется…", cls: "text-amber-300 border-amber-800", pulse: true },
  done: { label: "Готово", cls: "text-emerald-300 border-emerald-800" },
  cancelled: { label: "Отменено", cls: "text-zinc-400 border-zinc-700" },
  uploaded: { label: "Загружен", cls: "text-sky-300 border-sky-800" },
  processing: { label: "Обработка…", cls: "text-amber-300 border-amber-800", pulse: true },
};

export default function StatusBadge({ status }: { status: string }) {
  const m = MAP[status] ?? { label: status, cls: "text-zinc-300 border-zinc-700" };
  return <span className={`chip ${m.cls} ${m.pulse ? "pulse" : ""}`}>{m.label}</span>;
}
