/**
 * Проверки входных данных.
 *
 * Намеренно без внешних зависимостей: core тянут и API, и веб, и на клиенте лишние
 * 40 килобайт схема-валидатора не нужны. Все функции возвращают массив ошибок;
 * пустой массив означает, что данные корректны.
 */

import type { DateRange } from './types.js';
import { MS_IN_DAY, MS_IN_HOUR, toDate } from './dates.js';

export interface ValidationError {
  /** Путь до поля, как его ждёт веб: `startAt`, `range.end`, `customerId`. */
  field: string;
  /** Машинный код: `required`, `invalid_format`, `out_of_range`. */
  code: string;
  /** Человеческое сообщение, показывается пользователю как есть. */
  message: string;
}

/** Минимальный срок аренды — 2 часа. */
export const MIN_RENTAL_HOURS = 2;

/** Максимальный срок одной брони — 30 суток, дальше оформляется договор. */
export const MAX_RENTAL_DAYS = 30;

/** Насколько далеко вперёд принимаем брони. */
export const MAX_LEAD_DAYS = 180;

const ISO_RE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/;

function isIsoDateTime(value: unknown): value is string {
  return typeof value === 'string' && ISO_RE.test(value) && !Number.isNaN(Date.parse(value));
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Проверка интервала аренды: обе границы — корректный ISO 8601, конец строго позже
 * начала, длительность укладывается в разрешённые рамки.
 */
export function validateRange(range: DateRange, now: string | Date = new Date()): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!isIsoDateTime(range?.start)) {
    errors.push({ field: 'start', code: 'invalid_format', message: 'Некорректная дата начала' });
  }
  if (!isIsoDateTime(range?.end)) {
    errors.push({ field: 'end', code: 'invalid_format', message: 'Некорректная дата возврата' });
  }
  if (errors.length > 0) return errors;

  const start = toDate(range.start).getTime();
  const end = toDate(range.end).getTime();
  const at = toDate(now).getTime();

  if (end <= start) {
    errors.push({ field: 'end', code: 'out_of_range', message: 'Возврат должен быть позже выдачи' });
    return errors;
  }

  const hours = (end - start) / MS_IN_HOUR;
  if (hours < MIN_RENTAL_HOURS) {
    errors.push({
      field: 'end',
      code: 'out_of_range',
      message: `Минимальный срок аренды — ${MIN_RENTAL_HOURS} часа`,
    });
  }
  if (hours / 24 > MAX_RENTAL_DAYS) {
    errors.push({
      field: 'end',
      code: 'out_of_range',
      message: `Максимальный срок брони — ${MAX_RENTAL_DAYS} суток`,
    });
  }
  if (start - at > MAX_LEAD_DAYS * MS_IN_DAY) {
    errors.push({
      field: 'start',
      code: 'out_of_range',
      message: `Бронировать можно не более чем за ${MAX_LEAD_DAYS} дней`,
    });
  }

  return errors;
}

/** Тело запроса на создание брони — то, что приходит в `POST /api/bookings`. */
export interface BookingPayload {
  itemId: string;
  customerId: string;
  startAt: string;
  endAt: string;
  comment?: string;
}

/**
 * Проверка тела запроса на создание брони: обязательные поля на месте,
 * идентификаторы непустые, интервал корректный.
 */
export function validateBookingPayload(
  payload: unknown,
  now: string | Date = new Date(),
): ValidationError[] {
  const errors: ValidationError[] = [];
  if (typeof payload !== 'object' || payload === null) {
    return [{ field: 'body', code: 'required', message: 'Пустое тело запроса' }];
  }

  const body = payload as Partial<BookingPayload>;

  if (!isNonEmptyString(body.itemId)) {
    errors.push({ field: 'itemId', code: 'required', message: 'Не выбран товар' });
  }
  if (!isNonEmptyString(body.customerId)) {
    errors.push({ field: 'customerId', code: 'required', message: 'Не указан клиент' });
  }
  if (body.comment !== undefined && typeof body.comment !== 'string') {
    errors.push({ field: 'comment', code: 'invalid_format', message: 'Комментарий должен быть строкой' });
  }
  if (typeof body.comment === 'string' && body.comment.length > 500) {
    errors.push({ field: 'comment', code: 'out_of_range', message: 'Комментарий длиннее 500 символов' });
  }

  const rangeErrors = validateRange({ start: body.startAt as string, end: body.endAt as string }, now);
  for (const err of rangeErrors) {
    errors.push({ ...err, field: err.field === 'start' ? 'startAt' : 'endAt' });
  }

  return errors;
}

/** Собрать ошибки в одну строку — для логов и текста исключения. */
export function formatErrors(errors: ValidationError[]): string {
  return errors.map((e) => `${e.field}: ${e.message}`).join('; ');
}
