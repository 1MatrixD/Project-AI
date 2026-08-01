/**
 * Отчёты для сотрудников.
 *
 * `GET /api/reports/revenue` — выручка по периодам плюс топ товаров за тот же период.
 *
 * Агрегаты считаются прямо в Postgres: выгружать все брони в Node и складывать
 * в памяти на объёмах пункта выдачи бессмысленно, а по мере роста базы — вредно.
 */

import { Router } from 'express';
import { MS_IN_DAY, formatKop } from '@rentkit/core';
import { requireStaff } from '../middleware/auth.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';
import { query } from '../db/client.js';

export const reportsRouter = Router();

type Granularity = 'day' | 'week' | 'month';

const GRANULARITIES: Granularity[] = ['day', 'week', 'month'];

/** Период по умолчанию — последние 30 суток. */
const DEFAULT_PERIOD_DAYS = 30;

/** Брони в этих статусах считаются состоявшимися и попадают в выручку. */
const REVENUE_STATUSES = ['active', 'returned', 'overdue'];

interface Period {
  from: string;
  to: string;
}

function parsePeriod(q: Record<string, unknown>): Period {
  const now = Date.now();
  const from = typeof q.from === 'string' ? q.from : new Date(now - DEFAULT_PERIOD_DAYS * MS_IN_DAY).toISOString();
  const to = typeof q.to === 'string' ? q.to : new Date(now).toISOString();

  if (Number.isNaN(Date.parse(from)) || Number.isNaN(Date.parse(to))) {
    throw ApiError.badRequest('Параметры from и to должны быть датами ISO 8601');
  }
  if (Date.parse(to) <= Date.parse(from)) {
    throw ApiError.badRequest('Параметр to должен быть позже from');
  }
  return { from, to };
}

function parseGranularity(value: unknown): Granularity {
  if (value === undefined) return 'day';
  if (typeof value !== 'string' || !GRANULARITIES.includes(value as Granularity)) {
    throw ApiError.badRequest('Параметр granularity: day, week или month');
  }
  return value as Granularity;
}

interface BucketRow {
  bucket: Date;
  bookings: number;
  revenue_kop: number;
}

interface TopRow {
  item_id: string;
  title: string;
  category: string;
  bookings: number;
  revenue_kop: number;
}

/**
 * Выручка за период.
 *
 * Бронь попадает в выручку по дате начала аренды и в той сумме, которая была
 * зафиксирована при подтверждении (`quote_kop`). Штрафы и удержания из депозита
 * сюда не входят — они проходят отдельной строкой в отчёте по платежам.
 */
reportsRouter.get(
  '/revenue',
  requireStaff,
  asyncHandler(async (req, res) => {
    const period = parsePeriod(req.query as Record<string, unknown>);
    const granularity = parseGranularity(req.query.granularity);

    const buckets = await query<BucketRow>(
      `SELECT date_trunc($3, start_at)          AS bucket,
              count(*)::int                     AS bookings,
              coalesce(sum(quote_kop), 0)::int  AS revenue_kop
         FROM bookings
        WHERE start_at >= $1 AND start_at < $2
          AND status = ANY($4)
        GROUP BY 1
        ORDER BY 1`,
      [period.from, period.to, granularity, REVENUE_STATUSES],
    );

    const top = await query<TopRow>(
      `SELECT b.item_id, i.title, i.category,
              count(*)::int                       AS bookings,
              coalesce(sum(b.quote_kop), 0)::int  AS revenue_kop
         FROM bookings b
         JOIN items i ON i.id = b.item_id
        WHERE b.start_at >= $1 AND b.start_at < $2
          AND b.status = ANY($3)
        GROUP BY b.item_id, i.title, i.category
        ORDER BY revenue_kop DESC
        LIMIT 10`,
      [period.from, period.to, REVENUE_STATUSES],
    );

    const totalKop = buckets.reduce((acc, row) => acc + Number(row.revenue_kop), 0);
    const totalBookings = buckets.reduce((acc, row) => acc + Number(row.bookings), 0);

    res.json({
      period,
      granularity,
      buckets: buckets.map((row) => ({
        bucket: row.bucket instanceof Date ? row.bucket.toISOString() : String(row.bucket),
        bookings: Number(row.bookings),
        revenueKop: Number(row.revenue_kop),
      })),
      topItems: top.map((row) => ({
        itemId: row.item_id,
        title: row.title,
        category: row.category,
        bookings: Number(row.bookings),
        revenueKop: Number(row.revenue_kop),
      })),
      totals: {
        bookings: totalBookings,
        revenueKop: totalKop,
        revenueLabel: formatKop(totalKop),
        averageCheckKop: totalBookings > 0 ? Math.round(totalKop / totalBookings) : 0,
      },
    });
  }),
);

/** Сводка по статусам броней за период — что сейчас в работе, что просрочено. */
reportsRouter.get(
  '/statuses',
  requireStaff,
  asyncHandler(async (req, res) => {
    const period = parsePeriod(req.query as Record<string, unknown>);
    const rows = await query<{ status: string; count: number }>(
      `SELECT status, count(*)::int AS count
         FROM bookings
        WHERE start_at >= $1 AND start_at < $2
        GROUP BY status ORDER BY count DESC`,
      [period.from, period.to],
    );
    res.json({ period, statuses: rows });
  }),
);
