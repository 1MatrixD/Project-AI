/**
 * Клиенты.
 *
 * `GET /api/customers/:id` — карточка клиента с историей броней и краткой
 * статистикой. Клиент может смотреть только себя, сотрудник — любого.
 */

import { Router } from 'express';
import type { Booking } from '@rentkit/core';
import { depositFor } from '@rentkit/core';
import { customerScope, requireAuth } from '../middleware/auth.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';
import * as repo from '../db/repo.js';

export const customersRouter = Router();

/** Сколько последних броней показываем в карточке. */
const HISTORY_LIMIT = 50;

interface CustomerStats {
  total: number;
  active: number;
  cancelled: number;
  overdueEver: number;
  spentKop: number;
}

function buildStats(bookings: Booking[]): CustomerStats {
  const stats: CustomerStats = { total: 0, active: 0, cancelled: 0, overdueEver: 0, spentKop: 0 };

  for (const booking of bookings) {
    stats.total += 1;
    if (booking.status === 'active' || booking.status === 'reserved') stats.active += 1;
    if (booking.status === 'cancelled') stats.cancelled += 1;
    if (booking.status === 'overdue') stats.overdueEver += 1;
    if (booking.status === 'returned' || booking.status === 'active') {
      stats.spentKop += booking.quoteKop;
    }
  }

  return stats;
}

/** Карточка клиента: профиль, статистика и последние брони. */
customersRouter.get(
  '/:id',
  requireAuth,
  asyncHandler(async (req, res) => {
    const scope = customerScope(req);
    if (scope !== null && scope !== req.params.id) {
      throw ApiError.forbidden('Доступна только своя карточка');
    }

    const customer = await repo.findCustomer(req.params.id);
    if (!customer) throw ApiError.notFound('Клиент');

    const bookings = await repo.findBookings({ customerId: customer.id, limit: HISTORY_LIMIT });
    res.json({
      customer,
      stats: buildStats(bookings),
      bookings,
    });
  }),
);

/**
 * Размер депозита для конкретного клиента и товара.
 * Веб дёргает этот маршрут на странице оформления, чтобы показать сумму холда
 * до создания брони.
 */
customersRouter.get(
  '/:id/deposit/:itemId',
  requireAuth,
  asyncHandler(async (req, res) => {
    const scope = customerScope(req);
    if (scope !== null && scope !== req.params.id) {
      throw ApiError.forbidden('Доступен только свой расчёт депозита');
    }

    const customer = await repo.findCustomer(req.params.id);
    if (!customer) throw ApiError.notFound('Клиент');

    const item = await repo.findItem(req.params.itemId);
    if (!item) throw ApiError.notFound('Товар');

    res.json({
      customerId: customer.id,
      itemId: item.id,
      baseDepositKop: item.depositKop,
      depositKop: depositFor(item, customer),
      verified: customer.verified,
      rating: customer.rating,
    });
  }),
);

/** Активные брони клиента — для виджета «сейчас у вас на руках». */
customersRouter.get(
  '/:id/active',
  requireAuth,
  asyncHandler(async (req, res) => {
    const scope = customerScope(req);
    if (scope !== null && scope !== req.params.id) {
      throw ApiError.forbidden('Доступны только свои брони');
    }

    const bookings = await repo.findBookings({
      customerId: req.params.id,
      status: ['reserved', 'active', 'overdue'],
    });
    res.json({ bookings, total: bookings.length });
  }),
);
