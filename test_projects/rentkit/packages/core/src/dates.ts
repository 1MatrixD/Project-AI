/**
 * Работа с датами и расписанием пункта выдачи.
 *
 * Пункт выдачи один и работает по фиксированному графику, поэтому расписание живёт
 * константой, а не в базе. Когда появятся филиалы — переедет в таблицу `locations`.
 */

import type { DateRange } from './types.js';

export const MS_IN_HOUR = 60 * 60 * 1000;
export const MS_IN_DAY = 24 * MS_IN_HOUR;

/** Окно работы: часы в локальном времени пункта выдачи. */
export interface DaySchedule {
  open: number;
  close: number;
}

/**
 * График пункта выдачи: пн–сб 10:00–20:00, воскресенье — выходной.
 * Ключ — индекс дня недели как в `Date#getDay()` (0 — воскресенье).
 */
export const LOCATION_SCHEDULE: Record<number, DaySchedule | null> = {
  0: null,
  1: { open: 10, close: 20 },
  2: { open: 10, close: 20 },
  3: { open: 10, close: 20 },
  4: { open: 10, close: 20 },
  5: { open: 10, close: 20 },
  6: { open: 10, close: 20 },
};

export function toDate(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

/** Суббота или воскресенье — по ним считается выходная наценка. */
export function isWeekend(value: string | Date): boolean {
  const day = toDate(value).getDay();
  return day === 0 || day === 6;
}

/** Работает ли пункт выдачи в этот день. */
export function isWorkingDay(value: string | Date): boolean {
  return LOCATION_SCHEDULE[toDate(value).getDay()] != null;
}

/** Длительность аренды в часах, округление вверх. */
export function rentalHours(range: DateRange): number {
  const start = toDate(range.start).getTime();
  const end = toDate(range.end).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return Math.ceil((end - start) / MS_IN_HOUR);
}

/**
 * Расчётное количество суток: неполные сутки округляются вверх,
 * минимальный срок аренды — одни сутки.
 */
export function rentalDays(range: DateRange): number {
  const hours = rentalHours(range);
  if (hours === 0) return 0;
  return Math.max(1, Math.ceil(hours / 24));
}

/**
 * Сколько рабочих часов пункта выдачи укладывается между двумя моментами.
 * Нерабочие часы (ночь, воскресенье) не считаются. Если `b` раньше `a` — вернёт 0.
 */
export function businessHoursBetween(a: string | Date, b: string | Date): number {
  const from = toDate(a);
  const to = toDate(b);
  if (to.getTime() <= from.getTime()) return 0;

  let total = 0;
  const cursor = new Date(from.getFullYear(), from.getMonth(), from.getDate());

  while (cursor.getTime() < to.getTime()) {
    const schedule = LOCATION_SCHEDULE[cursor.getDay()];
    if (schedule) {
      const open = new Date(cursor);
      open.setHours(schedule.open, 0, 0, 0);
      const close = new Date(cursor);
      close.setHours(schedule.close, 0, 0, 0);

      const left = Math.max(open.getTime(), from.getTime());
      const right = Math.min(close.getTime(), to.getTime());
      if (right > left) total += (right - left) / MS_IN_HOUR;
    }
    cursor.setDate(cursor.getDate() + 1);
  }

  return Math.round(total * 100) / 100;
}

/**
 * Ближайший момент, когда пункт выдачи открыт.
 * Если сейчас рабочее время — вернёт исходную дату без изменений.
 */
export function nextWorkingOpen(value: string | Date): Date {
  const dt = new Date(toDate(value).getTime());

  for (let guard = 0; guard < 14; guard += 1) {
    const schedule = LOCATION_SCHEDULE[dt.getDay()];
    if (schedule) {
      const open = new Date(dt);
      open.setHours(schedule.open, 0, 0, 0);
      const close = new Date(dt);
      close.setHours(schedule.close, 0, 0, 0);

      if (dt.getTime() < open.getTime()) return open;
      if (dt.getTime() < close.getTime()) return dt;
    }
    dt.setDate(dt.getDate() + 1);
    dt.setHours(0, 0, 0, 0);
  }

  return dt;
}

/** Список календарных дат аренды — по одной на каждые расчётные сутки. */
export function daysOfRange(range: DateRange): Date[] {
  const days = rentalDays(range);
  const start = toDate(range.start);
  const out: Date[] = [];
  for (let i = 0; i < days; i += 1) {
    out.push(new Date(start.getTime() + i * MS_IN_DAY));
  }
  return out;
}

/** Сдвиг даты на N часов, удобно для расчётов сроков возврата. */
export function addHours(value: string | Date, hours: number): Date {
  return new Date(toDate(value).getTime() + hours * MS_IN_HOUR);
}
