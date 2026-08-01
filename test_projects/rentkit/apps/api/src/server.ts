/**
 * Точка входа API.
 *
 * Собирает express-приложение, вешает middleware и роутеры, поднимает сервер
 * на порту из конфигурации (по умолчанию 8030 — на него ходит веб-клиент).
 */

import express from 'express';
import cors from 'cors';
import { CORE_CONTRACT_VERSION } from '@rentkit/core';
import { config } from './config.js';
import { errorHandler, notFoundHandler, requestLogger } from './middleware/errors.js';
import { closePool, ping } from './db/client.js';
import { itemsRouter } from './routes/items.js';
import { bookingsRouter } from './routes/bookings.js';
import { returnsRouter } from './routes/returns.js';
import { paymentsRouter } from './routes/payments.js';
import { customersRouter } from './routes/customers.js';
import { reportsRouter } from './routes/reports.js';

export function createApp(): express.Express {
  const app = express();

  app.disable('x-powered-by');
  app.set('trust proxy', true);

  app.use(
    cors({
      origin: config.corsOrigins,
      credentials: true,
      methods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    }),
  );
  app.use(express.json({ limit: '256kb' }));
  app.use(requestLogger);

  /** Health-чек для мониторинга и для веба: он сверяет версию контракта при старте. */
  app.get('/api/health', async (_req, res) => {
    const dbAlive = await ping();
    res.status(dbAlive ? 200 : 503).json({
      status: dbAlive ? 'ok' : 'degraded',
      env: config.env,
      contractVersion: CORE_CONTRACT_VERSION,
      uptimeSec: Math.round(process.uptime()),
    });
  });

  app.use('/api/items', itemsRouter);
  app.use('/api/bookings', bookingsRouter);
  app.use('/api/returns', returnsRouter);
  app.use('/api/payments', paymentsRouter);
  app.use('/api/customers', customersRouter);
  app.use('/api/reports', reportsRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

/** Аккуратная остановка: перестаём принимать запросы, потом закрываем пул. */
function installShutdownHooks(server: ReturnType<express.Express['listen']>): void {
  let stopping = false;

  const stop = (signal: string) => {
    if (stopping) return;
    stopping = true;
    console.log(`[api] получен ${signal}, останавливаемся`);

    server.close(async () => {
      await closePool();
      console.log('[api] пул соединений закрыт, выходим');
      process.exit(0);
    });

    setTimeout(() => {
      console.error('[api] не уложились в 10 секунд, выходим принудительно');
      process.exit(1);
    }, 10_000).unref();
  };

  process.on('SIGINT', () => stop('SIGINT'));
  process.on('SIGTERM', () => stop('SIGTERM'));
  process.on('unhandledRejection', (reason) => {
    console.error('[api] необработанный rejection:', reason);
  });
}

export function start(): void {
  const app = createApp();
  const server = app.listen(config.port, () => {
    console.log(`[api] RentKit API слушает :${config.port} (${config.env})`);
    console.log(`[api] CORS разрешён для: ${config.corsOrigins.join(', ') || '—'}`);
  });

  installShutdownHooks(server);
}

start();
