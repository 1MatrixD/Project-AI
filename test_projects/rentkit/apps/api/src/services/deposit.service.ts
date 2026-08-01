/**
 * Депозит: блокировка суммы на карте клиента и снятие блокировки.
 *
 * Мы не списываем депозит, а держим холд у платёжного провайдера. Идентификатор
 * холда хранится в `bookings.deposit_hold_id`; пока он не null — деньги клиента
 * заморожены. Все операции дублируются строкой в таблице `payments`.
 */

import type { Booking, Customer, Item } from '@rentkit/core';
import { depositFor, settleDeposit } from '@rentkit/core';
import { config } from '../config.js';
import { ApiError } from '../middleware/errors.js';
import * as repo from '../db/repo.js';

export interface HoldResult {
  holdId: string;
  amountKop: number;
}

export interface ReleaseResult {
  holdId: string;
  chargedKop: number;
  refundKop: number;
}

/** Запрос к платёжному провайдеру. Ответ провайдера нам интересен только по `id`. */
async function callProvider(path: string, payload: Record<string, unknown>): Promise<string> {
  const url = `${config.paymentsBaseUrl}${path}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${config.paymentsKey}`,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw ApiError.payment(`Платёжный провайдер ответил ${response.status}`, { path });
  }

  const data = (await response.json()) as { id?: string };
  if (!data.id) throw ApiError.payment('Провайдер не вернул идентификатор операции', { path });
  return data.id;
}

/** Сумма депозита по товару и клиенту — с учётом скидки за рейтинг. */
export function amountFor(item: Item, customer: Customer | null): number {
  return depositFor(item, customer);
}

/**
 * Заблокировать депозит на карте клиента и записать идентификатор холда в бронь.
 * Повторный вызов по брони с уже существующим холдом — ошибка: два холда на одну
 * бронь означают двойную заморозку денег.
 */
export async function hold(booking: Booking, amountKop: number): Promise<HoldResult> {
  if (booking.depositHoldId) {
    throw ApiError.conflict('По брони уже есть активный холд депозита', {
      bookingId: booking.id,
      holdId: booking.depositHoldId,
    });
  }
  if (amountKop <= 0) {
    throw ApiError.badRequest('Сумма депозита должна быть больше нуля');
  }

  const holdId = await callProvider('/holds', {
    amount: amountKop,
    currency: 'RUB',
    reference: booking.id,
  });

  await repo.updateBooking(booking.id, { depositHoldId: holdId });
  await repo.insertPayment(booking.id, 'hold', amountKop, holdId);
  await repo.insertEvent(booking.id, 'deposit.held', { holdId, amountKop });

  return { holdId, amountKop };
}

/**
 * Снять блокировку депозита.
 *
 * `chargesKop` — сколько удерживаем в нашу пользу (штраф за просрочку, повреждения).
 * Удержанная часть списывается (capture), остаток размораживается и возвращается
 * клиенту. После вызова `deposit_hold_id` брони обнуляется.
 */
export async function release(booking: Booking, chargesKop = 0): Promise<ReleaseResult> {
  const holdId = booking.depositHoldId;
  if (!holdId) {
    throw ApiError.conflict('По брони нет активного холда депозита', { bookingId: booking.id });
  }

  const heldKop = await heldAmountFor(booking);
  const settlement = settleDeposit(heldKop, chargesKop);

  if (settlement.chargedKop > 0) {
    const captureId = await callProvider(`/holds/${holdId}/capture`, {
      amount: settlement.chargedKop,
    });
    await repo.insertPayment(booking.id, 'capture', settlement.chargedKop, captureId);
  }

  await callProvider(`/holds/${holdId}/release`, { amount: settlement.refundKop });
  await repo.updateBooking(booking.id, { depositHoldId: null });
  await repo.insertPayment(booking.id, 'release', settlement.refundKop, holdId);
  await repo.insertEvent(booking.id, 'deposit.released', {
    holdId,
    chargedKop: settlement.chargedKop,
    refundKop: settlement.refundKop,
  });

  return { holdId, chargedKop: settlement.chargedKop, refundKop: settlement.refundKop };
}

/**
 * Сколько денег заморожено по брони: депозит товара с учётом статуса клиента.
 * Провайдер сумму холда наружу не отдаёт, поэтому считаем по тем же правилам,
 * что и при блокировке.
 */
export async function heldAmountFor(booking: Booking): Promise<number> {
  const item = await repo.findItem(booking.itemId);
  const customer = await repo.findCustomer(booking.customerId);
  if (!item) throw ApiError.notFound('Товар брони');
  return depositFor(item, customer);
}
