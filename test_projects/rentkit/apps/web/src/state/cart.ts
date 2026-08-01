import { useSyncExternalStore } from 'react';
import type { BookingDraft, DateRange, Item } from '../types';

/**
 * Черновик брони («корзина» на один товар) живёт в sessionStorage:
 * закрыли вкладку — черновик ушёл, это осознанно. Между /items/:id и /checkout
 * данные передаём только через него, чтобы не терять выбор при F5.
 */

const STORAGE_KEY = 'rentkit.draft.v3';

const listeners = new Set<() => void>();
let snapshot: BookingDraft | null = null;
let hydrated = false;

function readStorage(): BookingDraft | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BookingDraft;
    if (!parsed?.itemId) return null;
    return parsed;
  } catch {
    // повреждённый черновик лечим сбросом — пользователь просто выберет даты заново
    sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

function commit(next: BookingDraft | null): void {
  snapshot = next;
  hydrated = true;
  try {
    if (next) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // приватный режим Safari: работаем из памяти, но UI не роняем
  }
  for (const listener of listeners) listener();
}

export function getDraft(): BookingDraft | null {
  if (!hydrated) {
    snapshot = readStorage();
    hydrated = true;
  }
  return snapshot;
}

/** Кладём товар в черновик, сохраняя уже выбранные даты, если товар тот же. */
export function setDraftItem(item: Item, range: DateRange | null): void {
  const current = getDraft();
  const keepRange = current?.itemId === item.id && !range;

  commit({
    itemId: item.id,
    sku: item.sku,
    title: item.title,
    dayRateKop: item.dayRateKop,
    hourRateKop: item.hourRateKop,
    depositKop: item.depositKop,
    start: range?.start ?? (keepRange ? current?.start ?? null : null),
    end: range?.end ?? (keepRange ? current?.end ?? null : null),
    savedAt: new Date().toISOString(),
  });
}

export function setDraftRange(range: DateRange | null): void {
  const current = getDraft();
  if (!current) return;
  commit({
    ...current,
    start: range?.start ?? null,
    end: range?.end ?? null,
    savedAt: new Date().toISOString(),
  });
}

export function clearDraft(): void {
  commit(null);
}

/** Интервал из черновика в виде DateRange — или null, если даты ещё не выбраны. */
export function draftRange(draft: BookingDraft | null): DateRange | null {
  if (!draft?.start || !draft.end) return null;
  return { start: draft.start, end: draft.end };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Реактивное чтение черновика в компонентах. */
export function useDraft(): BookingDraft | null {
  return useSyncExternalStore(subscribe, getDraft, () => null);
}
