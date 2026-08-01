/**
 * Брони.
 *
 * `POST   /api/bookings`            — создать бронь;
 * `GET    /api/bookings`            — список (клиент видит только свои);
 * `GET    /api/bookings/:id`        — детали;
 * `POST   /api/bookings/:id/cancel` — отменить;
 * `POST   /api/bookings/:id/quote`  — пересчитать стоимость.
 */

import { Router } from 'express';
import type { BookingStatus, DateRange } from '@rentkit/core';
import { assertOwnsBooking, customerScope, requireAuth } from '../middleware/auth.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';
import * as bookingService from '../services/booking.service.js';
import { notifyBooking } from '../services/notify.service.js';
import * as repo from '../db/repo.js';

export const bookingsRouter = Router();

const ALL_STATUSES: BookingStatus[] = [
  'draft', 'reserved', 'active', 'returned', 'cancelled', 'overdue',
];

function parseStatus(value: unknown): BookingStatus | undefined {
  if (typeof value !== 'string') return undefined;
  if (!ALL_STATUSES.includes(value as BookingStatus)) {
    throw ApiError.badRequest(`Неизвестный статус «${value}»`);
  }
  return value as BookingStatus;
}

/** Создать бронь: расчёт стоимости, холд депозита и письмо клиенту. */
bookingsRouter.post(
  '/',
  requireAuth,
  asyncHandler(async (req, res) => {
    const scope = customerScope(req);
    const payload = scope ? { ...req.body, customerId: scope } : req.body;

    const created = await bookingService.create(payload, req.user?.id ?? null);
    await notifyBooking('booking.created', {
      booking: created.booking,
      customer: created.customer,
      item: created.item,
      amountKop: created.quote.depositKop,
    });

    res.status(201).json({ booking: created.booking, quote: created.quote });
  }),
);

bookingsRouter.get(
  '/',
  requireAuth,
  asyncHandler(async (req, res) => {
    const scope = customerScope(req);
    const bookings = await repo.findBookings({
      customerId: scope ?? (typeof req.query.customerId === 'string' ? req.query.customerId : undefined),
      itemId: typeof req.query.itemId === 'string' ? req.query.itemId : undefined,
      status: parseStatus(req.query.status),
      from: typeof req.query.from === 'string' ? req.query.from : undefined,
      to: typeof req.query.to === 'string' ? req.query.to : undefined,
    });
    res.json({ bookings, total: bookings.length });
  }),
);

bookingsRouter.get(
  '/:id',
  requireAuth,
  asyncHandler(async (req, res) => {
    const booking = await bookingService.requireBooking(req.params.id);
    assertOwnsBooking(req, booking.customerId);

    const item = await repo.findItem(booking.itemId);
    const customer = await repo.findCustomer(booking.customerId);
    res.json({ booking, item, customer });
  }),
);

/**
 * Отменить бронь.
 *
 * Меняем статус на `cancelled`, снимаем холд депозита с карты клиента, пишем
 * событие в журнал и отправляем уведомление. Выданную на руки технику отменить
 * нельзя — по ней оформляется возврат.
 */
bookingsRouter.post(
  '/:id/cancel',
  requireAuth,
  asyncHandler(async (req, res) => {
    const booking = await bookingService.requireBooking(req.params.id);
    assertOwnsBooking(req, booking.customerId);

    if (booking.status === 'cancelled') {
      throw ApiError.conflict('Бронь уже отменена');
    }
    if (booking.status === 'returned') {
      throw ApiError.conflict('Бронь закрыта возвратом, отменять нечего');
    }
    if (booking.status === 'active' || booking.status === 'overdue') {
      throw ApiError.conflict('Техника на руках — оформите возврат, а не отмену');
    }

    const reason = typeof req.body?.reason === 'string' ? req.body.reason : 'клиент отменил';
    const updated = await repo.updateBooking(booking.id, { status: 'cancelled' });
    await repo.insertEvent(booking.id, 'booking.cancelled', { reason }, req.user?.id ?? null);

    const item = await repo.findItem(booking.itemId);
    const customer = await repo.findCustomer(booking.customerId);
    if (item && customer) {
      await notifyBooking('booking.cancelled', { booking: updated, customer, item });
    }

    res.json({ booking: updated });
  }),
);

/**
 * Пересчитать стоимость брони.
 * Если в теле переданы новые даты — считаем по ним, не сохраняя изменения:
 * веб показывает клиенту цену переноса до подтверждения.
 */
bookingsRouter.post(
  '/:id/quote',
  requireAuth,
  asyncHandler(async (req, res) => {
    const booking = await bookingService.requireBooking(req.params.id);
    assertOwnsBooking(req, booking.customerId);

    let range: DateRange | undefined;
    if (typeof req.body?.startAt === 'string' && typeof req.body?.endAt === 'string') {
      range = { start: req.body.startAt, end: req.body.endAt };
    }

    const quote = await bookingService.requote(booking.id, range);
    res.json({ bookingId: booking.id, quote });
  }),
);

/** Выдача техники на руки. Делает сотрудник пункта выдачи по факту приезда клиента. */
bookingsRouter.post(
  '/:id/pickup',
  requireAuth,
  asyncHandler(async (req, res) => {
    const at = typeof req.body?.at === 'string' ? req.body.at : new Date().toISOString();
    const booking = await bookingService.markPickedUp(req.params.id, at, req.user?.id ?? null);
    res.json({ booking });
  }),
);
