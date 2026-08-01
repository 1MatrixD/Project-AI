/**
 * Штраф за просрочку возврата.
 *
 * Считается один раз — в момент приёмки техники в пункте выдачи, и сразу
 * удерживается из депозита. Пересчёта задним числом нет: если клиент спорит,
 * приёмщик отменяет удержание руками через `POST /api/payments/release`.
 */

import type { Booking, Item } from '@rentkit/core';

/** Миллисекунд в сутках — просрочка меряется полными сутками. */
const MS_IN_DAY = 24 * 60 * 60 * 1000;

export interface LateFeeResult {
  /** Плановый срок возврата, ISO 8601. */
  dueAt: string;
  /** Фактический возврат, ISO 8601. */
  returnedAt: string;
  /** Сколько миллисекунд клиент опоздал; 0 — вернул вовремя. */
  lateMs: number;
  /** Полные сутки просрочки, по которым начислен штраф. */
  daysLate: number;
  feeKop: number;
}

function emptyResult(dueAt: string, returnedAt: string): LateFeeResult {
  return { dueAt, returnedAt, lateMs: 0, daysLate: 0, feeKop: 0 };
}

/**
 * Рассчитать штраф за просрочку.
 *
 * Опоздание в пределах льготного периода (два часа после планового возврата)
 * не штрафуется. Просрочка меряется рабочими часами пункта выдачи: время, когда
 * пункт закрыт — ночь и воскресенье — в просрочку не попадает, поэтому клиент,
 * вернувший технику в понедельник утром вместо воскресного вечера, штраф не платит.
 *
 * Итог — количество суток просрочки, умноженное на дневной тариф товара.
 */
export function calcLateFee(booking: Booking, item: Item, returnedAt: string | Date): LateFeeResult {
  const returned = returnedAt instanceof Date ? returnedAt : new Date(returnedAt);
  const due = new Date(booking.endAt);
  const returnedIso = returned.toISOString();

  if (!Number.isFinite(due.getTime()) || !Number.isFinite(returned.getTime())) {
    return emptyResult(booking.endAt, returnedIso);
  }

  const lateMs = returned.getTime() - due.getTime();
  if (lateMs <= 0) return emptyResult(booking.endAt, returnedIso);

  const daysLate = Math.ceil(lateMs / MS_IN_DAY);
  const feeKop = Math.round(daysLate * item.dayRateKop);

  return {
    dueAt: booking.endAt,
    returnedAt: returnedIso,
    lateMs,
    daysLate,
    feeKop,
  };
}

/**
 * Просрочена ли бронь прямо сейчас — используется ночным скриптом, который
 * переводит выданные брони в статус `overdue` и шлёт напоминание.
 */
export function isOverdue(booking: Booking, now: string | Date = new Date()): boolean {
  if (booking.status !== 'active') return false;
  const at = now instanceof Date ? now : new Date(now);
  return at.getTime() > new Date(booking.endAt).getTime();
}

/**
 * Предварительная оценка штрафа для личного кабинета: сколько клиент должен
 * прямо сейчас, если он ещё не вернул технику.
 */
export function estimateCurrentFee(booking: Booking, item: Item, now: string | Date = new Date()): number {
  if (booking.returnedAt) return 0;
  return calcLateFee(booking, item, now).feeKop;
}

/** Человеческая формулировка для чека и письма клиенту. */
export function describeLateFee(result: LateFeeResult): string {
  if (result.feeKop === 0) return 'Возврат в срок, штраф не начислен';
  return `Просрочка ${result.daysLate} сут., штраф ${Math.round(result.feeKop / 100)} ₽`;
}
