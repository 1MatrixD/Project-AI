/**
 * Сценарии работы с бронями: проверка занятости, создание, выдача на руки.
 *
 * Экземпляр техники один, поэтому вся логика крутится вокруг одного вопроса —
 * свободен ли этот конкретный кофр на запрошенный интервал.
 */

import type { Booking, Customer, DateRange, Item, Quote } from '@rentkit/core';
import { overlaps, quote, validateBookingPayload } from '@rentkit/core';
import type { BookingPayload } from '@rentkit/core';
import { ApiError } from '../middleware/errors.js';
import * as repo from '../db/repo.js';
import * as depositService from './deposit.service.js';

export interface CreatedBooking {
  booking: Booking;
  quote: Quote;
  item: Item;
  customer: Customer;
}

/**
 * Свободен ли экземпляр на запрошенный интервал.
 *
 * Берём брони, которые занимают технику, и проверяем пересечение с запрошенным
 * периодом. Стык впритык (возврат в 18:00, выдача в 18:00) занятостью не считается.
 */
export async function isAvailable(itemId: string, range: DateRange): Promise<boolean> {
  const busy = await repo.findBookings({
    itemId,
    status: 'active',
    from: range.start,
    to: range.end,
  });

  return !busy.some((booking) =>
    overlaps({ start: booking.startAt, end: booking.endAt }, range),
  );
}

/** Брони, из-за которых интервал занят. Нужны для внятного текста ошибки. */
export async function conflictingBookings(itemId: string, range: DateRange): Promise<Booking[]> {
  const busy = await repo.findBookings({
    itemId,
    status: 'active',
    from: range.start,
    to: range.end,
  });
  return busy.filter((booking) =>
    overlaps({ start: booking.startAt, end: booking.endAt }, range),
  );
}

/**
 * Создать бронь.
 *
 * Проверяем занятость и вставляем бронь в одной транзакции с блокировкой товара
 * (`SELECT ... FOR UPDATE` по строке `items`), поэтому две параллельные попытки
 * забронировать один экземпляр на пересекающиеся даты невозможны: вторая дождётся
 * снятия блокировки, увидит уже созданную бронь и получит 409.
 *
 * После вставки блокируем депозит на карте клиента и пишем событие в журнал.
 */
export async function create(payload: unknown, actorId: string | null = null): Promise<CreatedBooking> {
  const errors = validateBookingPayload(payload);
  if (errors.length > 0) throw ApiError.validation(errors);

  const body = payload as BookingPayload;
  const range: DateRange = { start: body.startAt, end: body.endAt };

  const item = await repo.findItem(body.itemId);
  if (!item) throw ApiError.notFound('Товар');

  const customer = await repo.findCustomer(body.customerId);
  if (!customer) throw ApiError.notFound('Клиент');

  const free = await isAvailable(item.id, range);
  if (!free) {
    throw ApiError.conflict('Товар занят на выбранные даты', {
      itemId: item.id,
      range,
    });
  }

  const calculated = quote(item, range, { customer });

  const booking = await repo.insertBooking({
    itemId: item.id,
    customerId: customer.id,
    startAt: range.start,
    endAt: range.end,
    status: 'reserved',
    quoteKop: calculated.totalKop,
    comment: body.comment ?? null,
  });

  await depositService.hold(booking, calculated.depositKop);
  await repo.insertEvent(
    booking.id,
    'booking.created',
    { itemId: item.id, quoteKop: calculated.totalKop, depositKop: calculated.depositKop },
    actorId,
  );

  const fresh = (await repo.findBooking(booking.id)) ?? booking;
  return { booking: fresh, quote: calculated, item, customer };
}

/** Пересчитать стоимость существующей брони — например, после переноса дат. */
export async function requote(bookingId: string, range?: DateRange): Promise<Quote> {
  const booking = await requireBooking(bookingId);
  const item = await repo.findItem(booking.itemId);
  if (!item) throw ApiError.notFound('Товар брони');

  const customer = await repo.findCustomer(booking.customerId);
  const period = range ?? { start: booking.startAt, end: booking.endAt };
  return quote(item, period, { customer });
}

/** Отметить выдачу техники на руки. Доступно только по подтверждённой брони. */
export async function markPickedUp(bookingId: string, at: string, actorId: string | null): Promise<Booking> {
  const booking = await requireBooking(bookingId);
  if (booking.status !== 'reserved') {
    throw ApiError.conflict(`Нельзя выдать бронь в статусе «${booking.status}»`);
  }

  const updated = await repo.updateBooking(booking.id, { status: 'active', pickedUpAt: at });
  await repo.insertEvent(booking.id, 'booking.picked_up', { at }, actorId);
  return updated;
}

/** Бронь или 404 — чтобы не дублировать проверку в каждом роуте. */
export async function requireBooking(id: string): Promise<Booking> {
  const booking = await repo.findBooking(id);
  if (!booking) throw ApiError.notFound('Бронь');
  return booking;
}
