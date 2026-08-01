/**
 * Доступ к данным по броням и каталогу. Здесь живёт весь SQL прикладных сценариев;
 * агрегаты для отчётов — отдельно, в `routes/reports.ts`. Наружу отдаём доменные
 * типы из `@rentkit/core`: про snake_case колонки не должен знать никто снаружи.
 */

import type { Booking, BookingStatus, Customer, Item, ItemCategory } from '@rentkit/core';
import { query, queryOne } from './client.js';

const ITEM_COLS = 'id, sku, title, category, day_rate_kop, hour_rate_kop, deposit_kop, condition, location_id';
const BOOKING_COLS =
  'id, item_id, customer_id, start_at, end_at, status, quote_kop, deposit_hold_id, picked_up_at, returned_at, created_at';

type Row = Record<string, unknown>;

const iso = (v: unknown): string => (v instanceof Date ? v.toISOString() : String(v));
const isoOrNull = (v: unknown): string | null => (v === null || v === undefined ? null : iso(v));

const toItem = (r: Row): Item => ({
  id: String(r.id), sku: String(r.sku), title: String(r.title),
  category: r.category as ItemCategory, dayRateKop: Number(r.day_rate_kop),
  hourRateKop: Number(r.hour_rate_kop), depositKop: Number(r.deposit_kop),
  condition: r.condition as Item['condition'], locationId: String(r.location_id),
});

const toBooking = (r: Row): Booking => ({
  id: String(r.id), itemId: String(r.item_id), customerId: String(r.customer_id),
  startAt: iso(r.start_at), endAt: iso(r.end_at), status: r.status as BookingStatus,
  quoteKop: Number(r.quote_kop),
  depositHoldId: r.deposit_hold_id === null ? null : String(r.deposit_hold_id),
  pickedUpAt: isoOrNull(r.picked_up_at), returnedAt: isoOrNull(r.returned_at),
  createdAt: iso(r.created_at),
});

const toCustomer = (r: Row): Customer => ({
  id: String(r.id), name: String(r.name), phone: String(r.phone),
  rating: Number(r.rating), verified: Boolean(r.verified),
});

export interface ItemFilter {
  category?: ItemCategory; locationId?: string; search?: string; limit?: number;
}

/** Каталог с фильтрами. Архивные экземпляры не показываем никогда. */
export async function findItems(filter: ItemFilter = {}): Promise<Item[]> {
  const where = ['archived = false'];
  const params: unknown[] = [];
  if (filter.category) where.push(`category = $${params.push(filter.category)}`);
  if (filter.locationId) where.push(`location_id = $${params.push(filter.locationId)}`);
  if (filter.search) {
    const n = params.push(`%${filter.search.toLowerCase()}%`);
    where.push(`(lower(title) LIKE $${n} OR lower(sku) LIKE $${n})`);
  }
  const limit = params.push(Math.min(filter.limit ?? 100, 200));
  const rows = await query<Row>(
    `SELECT ${ITEM_COLS} FROM items WHERE ${where.join(' AND ')} ORDER BY category, title LIMIT $${limit}`,
    params,
  );
  return rows.map(toItem);
}

export async function findItem(id: string): Promise<Item | null> {
  const row = await queryOne<Row>(`SELECT ${ITEM_COLS} FROM items WHERE id = $1`, [id]);
  return row ? toItem(row) : null;
}

export interface BookingFilter {
  itemId?: string;
  customerId?: string;
  /** Один статус или список; отсутствие поля означает «любой статус». */
  status?: BookingStatus | BookingStatus[];
  /** Пересечение с периодом: берём брони, задевающие [from, to). */
  from?: string;
  to?: string;
  limit?: number;
}

export async function findBookings(filter: BookingFilter = {}): Promise<Booking[]> {
  const where = ['1 = 1'];
  const params: unknown[] = [];
  if (filter.itemId) where.push(`item_id = $${params.push(filter.itemId)}`);
  if (filter.customerId) where.push(`customer_id = $${params.push(filter.customerId)}`);
  if (filter.status) {
    const statuses = Array.isArray(filter.status) ? filter.status : [filter.status];
    if (statuses.length > 0) where.push(`status = ANY($${params.push(statuses)})`);
  }
  if (filter.from) where.push(`end_at > $${params.push(filter.from)}`);
  if (filter.to) where.push(`start_at < $${params.push(filter.to)}`);
  const limit = params.push(Math.min(filter.limit ?? 200, 500));
  const rows = await query<Row>(
    `SELECT ${BOOKING_COLS} FROM bookings WHERE ${where.join(' AND ')} ORDER BY start_at DESC LIMIT $${limit}`,
    params,
  );
  return rows.map(toBooking);
}

export async function findBooking(id: string): Promise<Booking | null> {
  const row = await queryOne<Row>(`SELECT ${BOOKING_COLS} FROM bookings WHERE id = $1`, [id]);
  return row ? toBooking(row) : null;
}

export type NewBooking = Pick<
  Booking, 'itemId' | 'customerId' | 'startAt' | 'endAt' | 'status' | 'quoteKop'
> & { comment?: string | null };

export async function insertBooking(data: NewBooking): Promise<Booking> {
  const row = await queryOne<Row>(
    `INSERT INTO bookings (item_id, customer_id, start_at, end_at, status, quote_kop, comment)
     VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING ${BOOKING_COLS}`,
    [data.itemId, data.customerId, data.startAt, data.endAt, data.status, data.quoteKop, data.comment ?? null],
  );
  if (!row) throw new Error('INSERT не вернул строку брони');
  return toBooking(row);
}

export type BookingPatch = Partial<
  Pick<Booking, 'status' | 'quoteKop' | 'depositHoldId' | 'pickedUpAt' | 'returnedAt'>
>;

/** camelCase поля патча → snake_case колонки: quoteKop → quote_kop. */
const toColumn = (key: string): string => key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);

export async function updateBooking(id: string, patch: BookingPatch): Promise<Booking> {
  const sets = ['updated_at = now()'];
  const params: unknown[] = [];
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined) sets.push(`${toColumn(key)} = $${params.push(value)}`);
  }

  const id$ = params.push(id);
  const row = await queryOne<Row>(
    `UPDATE bookings SET ${sets.join(', ')} WHERE id = $${id$} RETURNING ${BOOKING_COLS}`,
    params,
  );
  if (!row) throw new Error(`Бронь ${id} не найдена при обновлении`);
  return toBooking(row);
}

/** Журнал: пишем всё, что меняет состояние брони — нужен для разборов с клиентами. */
export async function insertEvent(
  bookingId: string | null,
  type: string,
  payload: Record<string, unknown> = {},
  actorId: string | null = null,
): Promise<void> {
  await query(
    'INSERT INTO events (booking_id, type, payload, actor_id) VALUES ($1, $2, $3::jsonb, $4)',
    [bookingId, type, JSON.stringify(payload), actorId],
  );
}

export async function findCustomer(id: string): Promise<Customer | null> {
  const row = await queryOne<Row>(
    'SELECT id, name, phone, rating, verified FROM customers WHERE id = $1',
    [id],
  );
  return row ? toCustomer(row) : null;
}

export async function insertPayment(
  bookingId: string,
  kind: 'hold' | 'release' | 'capture' | 'refund',
  amountKop: number,
  externalId: string | null,
): Promise<void> {
  await query(
    'INSERT INTO payments (booking_id, kind, amount_kop, external_id) VALUES ($1, $2, $3, $4)',
    [bookingId, kind, amountKop, externalId],
  );
}
