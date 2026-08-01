/**
 * Ручные операции с депозитом.
 *
 * `POST /api/payments/hold`    — заблокировать депозит по брони;
 * `POST /api/payments/release` — снять блокировку (с удержанием или без).
 *
 * В обычном сценарии холд ставится автоматически при создании брони, а снимается
 * при приёмке возврата. Эти два маршрута — для разбора нестандартных ситуаций,
 * поэтому доступны только сотрудникам пункта выдачи.
 */

import { Router } from 'express';
import { requireStaff } from '../middleware/auth.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';
import * as bookingService from '../services/booking.service.js';
import * as depositService from '../services/deposit.service.js';
import * as repo from '../db/repo.js';

export const paymentsRouter = Router();

interface HoldPayload {
  bookingId?: string;
  /** Если не передана — считаем депозит по товару и рейтингу клиента. */
  amountKop?: number;
}

interface ReleasePayload {
  bookingId?: string;
  /** Сколько удержать в пользу пункта выдачи; остальное вернуть клиенту. */
  chargesKop?: number;
  reason?: string;
}

function requireBookingId(value: unknown): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw ApiError.badRequest('Не передан bookingId');
  }
  return value;
}

/**
 * Заблокировать депозит по брони.
 * Если по брони уже есть активный холд — вернётся 409, повторная блокировка
 * заморозила бы деньги клиента дважды.
 */
paymentsRouter.post(
  '/hold',
  requireStaff,
  asyncHandler(async (req, res) => {
    const body = (req.body ?? {}) as HoldPayload;
    const booking = await bookingService.requireBooking(requireBookingId(body.bookingId));

    if (booking.status === 'cancelled' || booking.status === 'returned') {
      throw ApiError.conflict(`Бронь в статусе «${booking.status}», депозит не нужен`);
    }

    const item = await repo.findItem(booking.itemId);
    if (!item) throw ApiError.notFound('Товар брони');
    const customer = await repo.findCustomer(booking.customerId);

    const amountKop =
      typeof body.amountKop === 'number' && Number.isFinite(body.amountKop)
        ? Math.round(body.amountKop)
        : depositService.amountFor(item, customer);

    const result = await depositService.hold(booking, amountKop);
    res.status(201).json({ bookingId: booking.id, hold: result });
  }),
);

/**
 * Снять блокировку депозита.
 * `chargesKop` удерживается в пользу пункта выдачи, остаток возвращается клиенту.
 * Без активного холда операция бессмысленна и отвечает 409.
 */
paymentsRouter.post(
  '/release',
  requireStaff,
  asyncHandler(async (req, res) => {
    const body = (req.body ?? {}) as ReleasePayload;
    const booking = await bookingService.requireBooking(requireBookingId(body.bookingId));

    const chargesKop =
      typeof body.chargesKop === 'number' && Number.isFinite(body.chargesKop)
        ? Math.max(0, Math.round(body.chargesKop))
        : 0;

    const settlement = await depositService.release(booking, chargesKop);
    await repo.insertEvent(
      booking.id,
      'deposit.released.manual',
      { reason: body.reason ?? 'ручное снятие', chargedKop: settlement.chargedKop },
      req.user?.id ?? null,
    );

    res.json({ bookingId: booking.id, settlement });
  }),
);

/** История платёжных операций по брони — для разбора спорных ситуаций. */
paymentsRouter.get(
  '/:bookingId',
  requireStaff,
  asyncHandler(async (req, res) => {
    const booking = await bookingService.requireBooking(req.params.bookingId);
    res.json({
      bookingId: booking.id,
      depositHoldId: booking.depositHoldId,
      heldKop: booking.depositHoldId ? await depositService.heldAmountFor(booking) : 0,
    });
  }),
);
