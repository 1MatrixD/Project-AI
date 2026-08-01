/**
 * Приёмка возврата.
 *
 * `POST /api/returns` — сотрудник принимает технику: фиксирует факт возврата,
 * считает штраф за просрочку и стоимость повреждений, удерживает их из депозита
 * и снимает холд. Клиенту уходит уведомление с суммой удержания.
 */

import { Router } from 'express';
import type { DamageSeverity } from '@rentkit/core';
import { damageFee, totalChargesKop } from '@rentkit/core';
import { requireStaff } from '../middleware/auth.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';
import * as bookingService from '../services/booking.service.js';
import * as depositService from '../services/deposit.service.js';
import { calcLateFee, describeLateFee } from '../services/late-fee.service.js';
import { notifyBooking } from '../services/notify.service.js';
import * as repo from '../db/repo.js';

export const returnsRouter = Router();

const SEVERITIES: DamageSeverity[] = ['scratch', 'minor', 'major', 'total'];

interface ReturnPayload {
  bookingId?: string;
  returnedAt?: string;
  damage?: DamageSeverity | null;
  note?: string;
}

function parseSeverity(value: unknown): DamageSeverity | null {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value !== 'string' || !SEVERITIES.includes(value as DamageSeverity)) {
    throw ApiError.badRequest(`Неизвестная степень повреждения «${String(value)}»`);
  }
  return value as DamageSeverity;
}

/**
 * Принять технику обратно.
 *
 * Возврат возможен только по брони, выданной на руки (`active`) или просроченной
 * (`overdue`). Порядок действий: считаем удержания → снимаем холд с удержанием →
 * переводим бронь в `returned` → пишем событие и уведомляем клиента.
 */
returnsRouter.post(
  '/',
  requireStaff,
  asyncHandler(async (req, res) => {
    const body = (req.body ?? {}) as ReturnPayload;
    if (!body.bookingId) throw ApiError.badRequest('Не передан bookingId');

    const returnedAt = body.returnedAt ?? new Date().toISOString();
    if (Number.isNaN(Date.parse(returnedAt))) {
      throw ApiError.badRequest('Некорректная дата возврата');
    }

    const booking = await bookingService.requireBooking(body.bookingId);
    if (booking.status !== 'active' && booking.status !== 'overdue') {
      throw ApiError.conflict(`Нельзя принять возврат по брони в статусе «${booking.status}»`);
    }

    const item = await repo.findItem(booking.itemId);
    if (!item) throw ApiError.notFound('Товар брони');
    const customer = await repo.findCustomer(booking.customerId);
    if (!customer) throw ApiError.notFound('Клиент брони');

    const severity = parseSeverity(body.damage);
    const lateFee = calcLateFee(booking, item, returnedAt);
    const damageKop = severity ? damageFee(item, severity) : 0;

    const heldKop = await depositService.heldAmountFor(booking);
    const chargesKop = totalChargesKop(lateFee.feeKop, damageKop, heldKop);

    const settlement = await depositService.release(booking, chargesKop);

    const updated = await repo.updateBooking(booking.id, {
      status: 'returned',
      returnedAt,
    });

    await repo.insertEvent(
      booking.id,
      'booking.returned',
      {
        returnedAt,
        daysLate: lateFee.daysLate,
        lateFeeKop: lateFee.feeKop,
        damage: severity,
        damageKop,
        chargedKop: settlement.chargedKop,
        refundKop: settlement.refundKop,
        note: body.note ?? null,
      },
      req.user?.id ?? null,
    );

    await notifyBooking('booking.returned', {
      booking: updated,
      customer,
      item,
      amountKop: settlement.chargedKop,
    });

    res.json({
      booking: updated,
      lateFee: {
        daysLate: lateFee.daysLate,
        amountKop: lateFee.feeKop,
        description: describeLateFee(lateFee),
      },
      damage: { severity, amountKop: damageKop },
      deposit: {
        heldKop,
        chargedKop: settlement.chargedKop,
        refundKop: settlement.refundKop,
      },
    });
  }),
);

/**
 * Предварительный расчёт удержаний без фиксации возврата.
 * Приёмщик показывает клиенту сумму до того, как нажать «Принять».
 */
returnsRouter.post(
  '/preview',
  requireStaff,
  asyncHandler(async (req, res) => {
    const body = (req.body ?? {}) as ReturnPayload;
    if (!body.bookingId) throw ApiError.badRequest('Не передан bookingId');

    const booking = await bookingService.requireBooking(body.bookingId);
    const item = await repo.findItem(booking.itemId);
    if (!item) throw ApiError.notFound('Товар брони');

    const returnedAt = body.returnedAt ?? new Date().toISOString();
    const severity = parseSeverity(body.damage);
    const lateFee = calcLateFee(booking, item, returnedAt);
    const damageKop = severity ? damageFee(item, severity) : 0;
    const heldKop = await depositService.heldAmountFor(booking);

    res.json({
      lateFee,
      damageKop,
      heldKop,
      chargesKop: totalChargesKop(lateFee.feeKop, damageKop, heldKop),
    });
  }),
);
