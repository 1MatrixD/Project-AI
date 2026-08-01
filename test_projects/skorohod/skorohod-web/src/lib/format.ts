/** Форматтеры для отображения данных API. Деньги всегда приходят в копейках. */

const MONEY_FMT = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const MONEY_FMT_FRACTION = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Копейки → строка вида «1 249 ₽».
 * Копейки показываем только если они ненулевые (скидки часто дают дробь).
 */
export function formatKop(kop: number): string {
  const rub = kop / 100;
  const body = kop % 100 === 0 ? MONEY_FMT.format(rub) : MONEY_FMT_FRACTION.format(rub);
  return `${body} ₽`;
}

/** То же самое, но со знаком минус впереди — для строк скидки. */
export function formatDiscountKop(kop: number): string {
  if (kop <= 0) return formatKop(0);
  return `−${formatKop(kop)}`;
}

const DATE_TIME_FMT = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit',
  month: 'long',
  hour: '2-digit',
  minute: '2-digit',
});

const TIME_FMT = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  hour: '2-digit',
  minute: '2-digit',
});

/** ISO-строка от API → «14 марта, 19:32» по Москве. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return DATE_TIME_FMT.format(d);
}

/** Только время, для шагов таймлайна. */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return TIME_FMT.format(d);
}

/**
 * Русская плюрализация: pluralize(3, ['заказ', 'заказа', 'заказов']).
 * Формы: 1 / 2-4 / 5-20.
 */
export function pluralize(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n) % 100;
  const tail = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (tail > 1 && tail < 5) return forms[1];
  if (tail === 1) return forms[0];
  return forms[2];
}

/** «3 заказа» — число вместе с правильной формой слова. */
export function pluralizeWithCount(n: number, forms: [string, string, string]): string {
  return `${n} ${pluralize(n, forms)}`;
}

/** Минуты → «1 ч 20 мин» для отчётов админки. */
export function formatMinutes(minutes: number): string {
  const total = Math.round(minutes);
  if (total < 60) return `${total} мин`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m === 0 ? `${h} ч` : `${h} ч ${m} мин`;
}

/** Дата в формате, который ждёт админский отчёт: YYYY-MM-DD. */
export function toApiDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
