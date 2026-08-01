/**
 * Занятость техники.
 *
 * Экземпляр один, поэтому любая пересекающаяся бронь в блокирующем статусе делает
 * товар недоступным. Календарь на витрине строится из `mergeBusy()`.
 */

import type { Booking, BookingStatus, DateRange } from './types.js';
import { MS_IN_HOUR, toDate } from './dates.js';

/**
 * Статусы, которые занимают технику.
 *
 * `reserved` — бронь подтверждена, экземпляр отложен на складе;
 * `active` — выдан на руки;
 * `overdue` — просрочен, физически всё ещё у клиента, а значит недоступен.
 *
 * `draft`, `cancelled` и `returned` занятости не создают.
 */
export const BLOCKING_STATUSES: BookingStatus[] = ['reserved', 'active', 'overdue'];

/** Блокирует ли бронь товар на своём интервале. */
export function isBlocking(status: BookingStatus): boolean {
  return BLOCKING_STATUSES.includes(status);
}

/**
 * Пересекаются ли два полуинтервала [start, end).
 * Стык впритык пересечением не считается: возврат в 18:00 и выдача в 18:00 допустимы.
 */
export function overlaps(a: DateRange, b: DateRange): boolean {
  const aStart = toDate(a.start).getTime();
  const aEnd = toDate(a.end).getTime();
  const bStart = toDate(b.start).getTime();
  const bEnd = toDate(b.end).getTime();
  return aStart < bEnd && bStart < aEnd;
}

/** Бронь как интервал занятости. */
export function bookingRange(booking: Booking): DateRange {
  return { start: booking.startAt, end: booking.endAt };
}

/**
 * Свернуть брони в список непересекающихся занятых интервалов.
 * Учитываются только блокирующие статусы, соседние и пересекающиеся окна склеиваются.
 */
export function mergeBusy(bookings: Booking[]): DateRange[] {
  const ranges = bookings
    .filter((b) => isBlocking(b.status))
    .map(bookingRange)
    .filter((r) => toDate(r.end).getTime() > toDate(r.start).getTime())
    .sort((a, b) => toDate(a.start).getTime() - toDate(b.start).getTime());

  const merged: DateRange[] = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && toDate(range.start).getTime() <= toDate(last.end).getTime()) {
      if (toDate(range.end).getTime() > toDate(last.end).getTime()) last.end = range.end;
      continue;
    }
    merged.push({ start: range.start, end: range.end });
  }
  return merged;
}

/** Свободен ли интервал относительно уже занятых окон. */
export function isRangeFree(busy: DateRange[], range: DateRange): boolean {
  return !busy.some((b) => overlaps(b, range));
}

/**
 * Ближайшее окно длиной `hours`, начиная с момента `from`.
 * Возвращает `null`, если в пределах 60 суток свободного окна нет.
 */
export function nextFreeSlot(busy: DateRange[], from: string | Date, hours: number): DateRange | null {
  if (hours <= 0) return null;

  const sorted = [...busy].sort(
    (a, b) => toDate(a.start).getTime() - toDate(b.start).getTime(),
  );
  const limit = toDate(from).getTime() + 60 * 24 * MS_IN_HOUR;
  let cursor = toDate(from).getTime();

  for (const window of sorted) {
    const windowStart = toDate(window.start).getTime();
    const windowEnd = toDate(window.end).getTime();
    if (windowEnd <= cursor) continue;

    if (windowStart - cursor >= hours * MS_IN_HOUR) {
      return {
        start: new Date(cursor).toISOString(),
        end: new Date(cursor + hours * MS_IN_HOUR).toISOString(),
      };
    }
    cursor = Math.max(cursor, windowEnd);
    if (cursor > limit) return null;
  }

  if (cursor > limit) return null;
  return {
    start: new Date(cursor).toISOString(),
    end: new Date(cursor + hours * MS_IN_HOUR).toISOString(),
  };
}

/** Инвертировать занятость в свободные окна внутри запрошенного периода. */
export function freeWindows(busy: DateRange[], period: DateRange): DateRange[] {
  const out: DateRange[] = [];
  let cursor = toDate(period.start).getTime();
  const end = toDate(period.end).getTime();

  const sorted = [...busy].sort(
    (a, b) => toDate(a.start).getTime() - toDate(b.start).getTime(),
  );

  for (const window of sorted) {
    const windowStart = toDate(window.start).getTime();
    const windowEnd = toDate(window.end).getTime();
    if (windowEnd <= cursor) continue;
    if (windowStart >= end) break;
    if (windowStart > cursor) {
      out.push({ start: new Date(cursor).toISOString(), end: new Date(windowStart).toISOString() });
    }
    cursor = Math.max(cursor, windowEnd);
  }

  if (cursor < end) {
    out.push({ start: new Date(cursor).toISOString(), end: new Date(end).toISOString() });
  }
  return out;
}
