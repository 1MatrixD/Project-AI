/**
 * Каталог техники.
 *
 * `GET /api/items`                  — витрина с фильтрами;
 * `GET /api/items/:id`              — карточка товара;
 * `GET /api/items/:id/availability` — занятые интервалы и ближайшее свободное окно.
 *
 * Каталог публичный: токен не обязателен, но если он есть — разбираем его,
 * чтобы в будущем показывать персональные цены.
 */

import { Router } from 'express';
import type { DateRange } from '@rentkit/core';
import { BLOCKING_STATUSES, MS_IN_DAY, freeWindows, mergeBusy, nextFreeSlot } from '@rentkit/core';
import { optionalAuth } from '../middleware/auth.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';
import * as inventory from '../services/inventory.service.js';
import * as repo from '../db/repo.js';

export const itemsRouter = Router();

/** Горизонт календаря по умолчанию — 30 суток вперёд от текущего момента. */
const DEFAULT_HORIZON_DAYS = 30;

function parsePeriod(query: Record<string, unknown>): DateRange {
  const now = Date.now();
  const from = typeof query.from === 'string' ? query.from : new Date(now).toISOString();
  const to =
    typeof query.to === 'string'
      ? query.to
      : new Date(now + DEFAULT_HORIZON_DAYS * MS_IN_DAY).toISOString();

  if (Number.isNaN(Date.parse(from)) || Number.isNaN(Date.parse(to))) {
    throw ApiError.badRequest('Параметры from и to должны быть датами ISO 8601');
  }
  if (Date.parse(to) <= Date.parse(from)) {
    throw ApiError.badRequest('Параметр to должен быть позже from');
  }
  return { start: from, end: to };
}

itemsRouter.get(
  '/',
  optionalAuth,
  asyncHandler(async (req, res) => {
    const filter = inventory.parseCatalogQuery(req.query as Record<string, unknown>);
    const items = await inventory.listCatalog(filter);
    res.json({ items, total: items.length });
  }),
);

itemsRouter.get(
  '/:id',
  optionalAuth,
  asyncHandler(async (req, res) => {
    const item = await inventory.getItemCard(req.params.id);
    res.json({ item });
  }),
);

/**
 * Занятость экземпляра на период.
 *
 * Занятыми считаются брони в блокирующих статусах: подтверждённые, выданные на руки
 * и просроченные. Черновики и отменённые брони календарь не занимают.
 */
itemsRouter.get(
  '/:id/availability',
  optionalAuth,
  asyncHandler(async (req, res) => {
    const item = await inventory.requireItem(req.params.id);
    const period = parsePeriod(req.query as Record<string, unknown>);

    const bookings = await repo.findBookings({
      itemId: item.id,
      status: BLOCKING_STATUSES,
      from: period.start,
      to: period.end,
    });

    const busy = mergeBusy(bookings);
    const free = freeWindows(busy, period);

    const hoursRaw = req.query.hours;
    const hours = typeof hoursRaw === 'string' ? Number.parseInt(hoursRaw, 10) : 24;
    if (!Number.isFinite(hours) || hours <= 0) {
      throw ApiError.badRequest('Параметр hours должен быть положительным числом');
    }

    res.json({
      itemId: item.id,
      period,
      busy,
      free,
      nextFreeSlot: nextFreeSlot(busy, period.start, hours),
    });
  }),
);

/** Сводка по категориям для дашборда сотрудников. */
itemsRouter.get(
  '/meta/summary',
  optionalAuth,
  asyncHandler(async (req, res) => {
    const locationId = typeof req.query.locationId === 'string' ? req.query.locationId : undefined;
    const summary = await inventory.categorySummary(locationId);
    res.json({ summary });
  }),
);
