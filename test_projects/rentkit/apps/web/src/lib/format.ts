import type { DateRange } from '../types';

/** Форматирование для витрины: деньги приходят в копейках, даты — в ISO. */

const RUB = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const RUB_EXACT = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 2,
});

const DATE_TIME = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

const DATE_ONLY = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

/**
 * Копейки → «12 400 ₽». Дробную часть показываем только если она не нулевая:
 * в прайсе почти всё кратно рублю, лишние «,00» шумят.
 */
export function formatKop(kop: number): string {
  const rub = kop / 100;
  const formatted = Number.isInteger(rub) ? RUB.format(rub) : RUB_EXACT.format(rub);
  return formatted.replace(/ ₽/, ' ₽');
}

/** Копейки со знаком — для скидок и штрафов в расшифровке. */
export function formatKopSigned(kop: number): string {
  if (kop === 0) return formatKop(0);
  const sign = kop < 0 ? '−' : '+';
  return `${sign}${formatKop(Math.abs(kop))}`;
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return '—';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return DATE_TIME.format(date);
}

export function formatDayOnly(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : DATE_ONLY.format(date);
}

/** «12 мар, 10:00 — 15 мар, 10:00». Внутри одних суток время слева не дублируем. */
export function formatRange(range: DateRange | null | undefined): string {
  if (!range?.start || !range.end) return 'даты не выбраны';
  const start = new Date(range.start);
  const end = new Date(range.end);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 'даты не выбраны';

  const sameDay = start.toDateString() === end.toDateString();
  if (sameDay) {
    const time = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });
    return `${DATE_TIME.format(start)} — ${time.format(end)}`;
  }
  return `${DATE_TIME.format(start)} — ${DATE_TIME.format(end)}`;
}

/** Склонение: 1 сутки, 2 суток, 5 суток. «Сутки» — pluralia tantum, форма одна. */
export function pluralDays(days: number): string {
  const abs = Math.abs(days) % 100;
  const tail = abs % 10;
  if (abs > 10 && abs < 20) return `${days} суток`;
  if (tail === 1) return `${days} сутки`;
  if (tail >= 2 && tail <= 4) return `${days} суток`;
  return `${days} суток`;
}

export function pluralHours(hours: number): string {
  const abs = Math.abs(hours) % 100;
  const tail = abs % 10;
  if (abs > 10 && abs < 20) return `${hours} часов`;
  if (tail === 1) return `${hours} час`;
  if (tail >= 2 && tail <= 4) return `${hours} часа`;
  return `${hours} часов`;
}

/** Значение для <input type="datetime-local"> — без таймзоны и секунд. */
export function toInputValue(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

export function fromInputValue(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
