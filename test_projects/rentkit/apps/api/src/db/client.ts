/**
 * Пул соединений с Postgres.
 *
 * Один пул на процесс. Прямых обращений к `pool` из роутов быть не должно —
 * все запросы живут в `repo.ts`, чтобы SQL не расползался по кодовой базе.
 */

import pg from 'pg';
import { config } from '../config.js';

const { Pool } = pg;

/** Пул создаётся лениво: тесты подменяют DATABASE_URL до первого запроса. */
export const pool = new Pool({
  connectionString: config.databaseUrl,
  max: config.pgPoolMax,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
  application_name: 'rentkit-api',
});

pool.on('error', (err) => {
  console.error('[db] соединение из пула упало:', err.message);
});

/** Запрос дольше этого порога попадает в лог как медленный. */
export const SLOW_QUERY_MS = 300;

/**
 * Выполнить запрос и вернуть строки.
 * Параметры передаём только через плейсхолдеры `$1..$n` — никакой конкатенации.
 */
export async function query<T extends pg.QueryResultRow = pg.QueryResultRow>(
  text: string,
  params: unknown[] = [],
): Promise<T[]> {
  const startedAt = Date.now();
  try {
    const result = await pool.query<T>(text, params as never[]);
    const ms = Date.now() - startedAt;
    if (ms > SLOW_QUERY_MS) {
      console.warn(`[db] медленный запрос ${ms}ms: ${text.slice(0, 90).replace(/\s+/g, ' ')}`);
    }
    return result.rows;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`[db] ошибка запроса: ${message}`);
    throw err;
  }
}

/** Первая строка результата либо `null`. */
export async function queryOne<T extends pg.QueryResultRow = pg.QueryResultRow>(
  text: string,
  params: unknown[] = [],
): Promise<T | null> {
  const rows = await query<T>(text, params);
  return rows[0] ?? null;
}

/**
 * Выполнить набор запросов в одной транзакции.
 * При исключении делается ROLLBACK, соединение в любом случае возвращается в пул.
 */
export async function withTransaction<T>(
  fn: (client: pg.PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await fn(client);
    await client.query('COMMIT');
    return result;
  } catch (err) {
    await client.query('ROLLBACK').catch(() => undefined);
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Заблокировать строку товара до конца транзакции.
 * Используется там, где нужно исключить одновременную работу с одним экземпляром.
 */
export async function lockItemRow(client: pg.PoolClient, itemId: string): Promise<void> {
  await client.query('SELECT id FROM items WHERE id = $1 FOR UPDATE', [itemId]);
}

/** Проверка живости базы для `GET /api/health`. */
export async function ping(): Promise<boolean> {
  try {
    await pool.query('SELECT 1');
    return true;
  } catch {
    return false;
  }
}

/** Аккуратно закрыть пул при остановке процесса. */
export async function closePool(): Promise<void> {
  await pool.end();
}
