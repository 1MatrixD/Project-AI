/**
 * Правила депозита.
 *
 * Депозит не списывается, а блокируется на карте клиента (холд). Размер зависит от
 * товара и от того, насколько мы доверяем клиенту: проверенным постоянникам держать
 * полную сумму смысла нет — они и так возвращают технику вовремя.
 */

import type { Booking, Customer, Item } from './types.js';
import { MS_IN_HOUR, toDate } from './dates.js';

/** Скидка на депозит для проверенных клиентов с высоким рейтингом, в процентах. */
export const VERIFIED_DEPOSIT_DISCOUNT_PCT = 30;

/** Минимальный рейтинг, с которого действует скидка на депозит. */
export const MIN_RATING_FOR_DEPOSIT_DISCOUNT = 4.5;

/** Депозит никогда не опускается ниже этой суммы — 3 000 ₽. */
export const MIN_DEPOSIT_KOP = 300_000;

/**
 * За сколько часов до начала аренды отмена считается бесплатной.
 * Позже этого порога мы уже отказали другим клиентам и держим технику на складе.
 */
export const CANCEL_GRACE_HOURS = 24;

/**
 * Итоговый депозит по товару с учётом статуса клиента.
 *
 * Проверенный клиент (`verified`) с рейтингом от 4.5 получает −30 %, но итог не может
 * опуститься ниже `MIN_DEPOSIT_KOP`. Если клиент неизвестен (расчёт для анонимной
 * витрины) — возвращается базовый депозит товара.
 */
export function depositFor(item: Item, customer?: Customer | null): number {
  const base = Math.max(0, Math.round(item.depositKop));
  if (!customer) return base;

  const trusted = customer.verified && customer.rating >= MIN_RATING_FOR_DEPOSIT_DISCOUNT;
  if (!trusted) return base;

  const discounted = Math.floor((base * (100 - VERIFIED_DEPOSIT_DISCOUNT_PCT)) / 100);
  return Math.max(MIN_DEPOSIT_KOP, discounted);
}

/** Сколько депозита уходит на удержания и сколько возвращается клиенту. */
export interface DepositSettlement {
  heldKop: number;
  chargedKop: number;
  refundKop: number;
}

/**
 * Разложить холд на удержание и возврат.
 * Удержать больше, чем заблокировано, мы не можем — остаток выставляется счётом отдельно.
 */
export function settleDeposit(heldKop: number, chargesKop: number): DepositSettlement {
  const held = Math.max(0, Math.round(heldKop));
  const charged = Math.min(held, Math.max(0, Math.round(chargesKop)));
  return { heldKop: held, chargedKop: charged, refundKop: held - charged };
}

/**
 * Бесплатная ли отмена: клиент успел отменить бронь не позже чем за
 * `CANCEL_GRACE_HOURS` до начала аренды.
 *
 * Брони, которые уже выданы на руки (`active`, `overdue`) или закрыты, бесплатно
 * отменить нельзя — по ним оформляется возврат, а не отмена.
 */
export function isFreeCancel(booking: Booking, now: string | Date): boolean {
  if (booking.status !== 'draft' && booking.status !== 'reserved') return false;

  const startAt = toDate(booking.startAt).getTime();
  const at = toDate(now).getTime();
  if (!Number.isFinite(startAt) || !Number.isFinite(at)) return false;

  return startAt - at >= CANCEL_GRACE_HOURS * MS_IN_HOUR;
}

/**
 * Штраф за позднюю отмену — 10 % стоимости аренды, но не больше половины депозита.
 * Для бесплатной отмены всегда 0.
 */
export function lateCancelFee(booking: Booking, depositKop: number, now: string | Date): number {
  if (isFreeCancel(booking, now)) return 0;
  const penalty = Math.floor(booking.quoteKop * 0.1);
  return Math.min(penalty, Math.floor(depositKop / 2));
}
