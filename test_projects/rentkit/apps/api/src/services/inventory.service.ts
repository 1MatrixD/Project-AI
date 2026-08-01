/**
 * Каталог техники.
 *
 * Отдаёт витрину: список карточек с тарифами и депозитом. Занятость экземпляра
 * запрашивается отдельно — `GET /api/items/:id/availability`, потому что календарь
 * нужен только на странице конкретного товара.
 */

import type { Item, ItemCategory } from '@rentkit/core';
import { formatKop } from '@rentkit/core';
import { ApiError } from '../middleware/errors.js';
import * as repo from '../db/repo.js';

/** Карточка товара в том виде, в каком её ждёт веб. */
export interface CatalogEntry {
  id: string;
  sku: string;
  title: string;
  category: ItemCategory;
  dayRateKop: number;
  hourRateKop: number;
  depositKop: number;
  condition: Item['condition'];
  locationId: string;
  /** Готовая подпись для списка: «3 500 ₽ / сутки». */
  priceLabel: string;
}

export interface CatalogFilter {
  category?: ItemCategory;
  locationId?: string;
  search?: string;
  limit?: number;
}

const CATEGORIES: ItemCategory[] = ['camera', 'lens', 'light', 'audio', 'grip'];

function parseCategory(value: unknown): ItemCategory | undefined {
  if (typeof value !== 'string') return undefined;
  const category = value as ItemCategory;
  if (!CATEGORIES.includes(category)) {
    throw ApiError.badRequest(`Неизвестная категория «${value}»`);
  }
  return category;
}

function toEntry(item: Item): CatalogEntry {
  return {
    id: item.id,
    sku: item.sku,
    title: item.title,
    category: item.category,
    dayRateKop: item.dayRateKop,
    hourRateKop: item.hourRateKop,
    depositKop: item.depositKop,
    condition: item.condition,
    locationId: item.locationId,
    priceLabel: `${formatKop(item.dayRateKop)} / сутки`,
  };
}

/**
 * Список товаров для витрины.
 * Фильтры: категория, пункт выдачи, поиск по названию и артикулу.
 */
export async function listCatalog(filter: CatalogFilter = {}): Promise<CatalogEntry[]> {
  const items = await repo.findItems({
    category: filter.category,
    locationId: filter.locationId,
    search: filter.search,
    limit: filter.limit,
  });
  return items.map(toEntry);
}

/** Разбор query-параметров каталога в фильтр. Ошибки — сразу 400. */
export function parseCatalogQuery(query: Record<string, unknown>): CatalogFilter {
  const limitRaw = typeof query.limit === 'string' ? Number.parseInt(query.limit, 10) : undefined;
  if (limitRaw !== undefined && (!Number.isFinite(limitRaw) || limitRaw <= 0)) {
    throw ApiError.badRequest('Параметр limit должен быть положительным числом');
  }

  return {
    category: parseCategory(query.category),
    locationId: typeof query.locationId === 'string' ? query.locationId : undefined,
    search: typeof query.q === 'string' && query.q.trim() ? query.q.trim() : undefined,
    limit: limitRaw,
  };
}

/** Карточка одного товара. Бросает 404, если экземпляра нет или он в архиве. */
export async function getItemCard(id: string): Promise<CatalogEntry> {
  const item = await repo.findItem(id);
  if (!item) throw ApiError.notFound('Товар');
  return toEntry(item);
}

/** Сырой товар для внутренних расчётов — цены, депозита, штрафа. */
export async function requireItem(id: string): Promise<Item> {
  const item = await repo.findItem(id);
  if (!item) throw ApiError.notFound('Товар');
  return item;
}

/** Сводка по каталогу для дашборда сотрудников. */
export async function categorySummary(locationId?: string): Promise<Record<ItemCategory, number>> {
  const items = await repo.findItems({ locationId, limit: 200 });
  const summary = { camera: 0, lens: 0, light: 0, audio: 0, grip: 0 } as Record<ItemCategory, number>;
  for (const item of items) summary[item.category] += 1;
  return summary;
}
