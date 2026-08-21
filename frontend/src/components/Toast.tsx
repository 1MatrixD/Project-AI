"use client";

import { useEffect, useState } from "react";

/** Глобальные тосты. Раньше уведомления рендерились в теле вкладки: переустановил
 *  плагин, находясь внизу страницы, — сообщение появилось сверху и осталось
 *  незамеченным. Тост всплывает в углу вьюпорта откуда угодно. */

type ToastItem = { id: number; text: string; kind: "info" | "error" };

let nextId = 1;
let listener: ((t: ToastItem) => void) | null = null;
const backlog: ToastItem[] = [];

export function toast(text: string, kind: "info" | "error" = "info") {
  const t: ToastItem = { id: nextId++, text, kind };
  if (listener) listener(t);
  else backlog.push(t); // хост ещё не смонтирован — покажем при монтировании
}

export function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    listener = (t) => {
      setItems((xs) => [...xs, t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), 7000);
    };
    for (const t of backlog.splice(0)) listener(t);
    return () => {
      listener = null;
    };
  }, []);

  if (items.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[100] space-y-2 w-full max-w-sm pointer-events-none">
      {items.map((t) => (
        <div
          key={t.id}
          onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}
          className={`card px-4 py-3 text-sm leading-relaxed shadow-xl cursor-pointer pointer-events-auto ${
            t.kind === "error"
              ? "border-red-400/50 text-red-300"
              : "border-[var(--accent)]/50"
          }`}
          title="Закрыть"
        >
          {t.text}
        </div>
      ))}
    </div>
  );
}
