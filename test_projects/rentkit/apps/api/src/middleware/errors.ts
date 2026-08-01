/**
 * Ошибки API.
 *
 * Наружу всегда отдаём один формат: `{ error: { code, message, details } }`.
 * Веб разбирает `code`, а `message` показывает пользователю как есть,
 * поэтому в сообщениях не должно быть внутренних деталей и SQL.
 */

import type { NextFunction, Request, Response } from 'express';
import type { ValidationError } from '@rentkit/core';
import { config } from '../config.js';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details ?? null;
  }

  static badRequest(message: string, details?: unknown): ApiError {
    return new ApiError(400, 'bad_request', message, details);
  }

  static unauthorized(message = 'Требуется авторизация'): ApiError {
    return new ApiError(401, 'unauthorized', message);
  }

  static forbidden(message = 'Недостаточно прав'): ApiError {
    return new ApiError(403, 'forbidden', message);
  }

  static notFound(what = 'Объект'): ApiError {
    return new ApiError(404, 'not_found', `${what} не найден`);
  }

  static conflict(message: string, details?: unknown): ApiError {
    return new ApiError(409, 'conflict', message, details);
  }

  static validation(errors: ValidationError[]): ApiError {
    return new ApiError(422, 'validation_failed', 'Данные не прошли проверку', errors);
  }

  static payment(message: string, details?: unknown): ApiError {
    return new ApiError(502, 'payment_provider_error', message, details);
  }
}

/** Обёртка для async-обработчиков: express 4 сам промисы не ловит. */
export function asyncHandler<T extends Request>(
  handler: (req: T, res: Response, next: NextFunction) => Promise<unknown>,
) {
  return (req: T, res: Response, next: NextFunction): void => {
    handler(req, res, next).catch(next);
  };
}

/** 404 для несуществующих маршрутов — вешается последним перед errorHandler. */
export function notFoundHandler(req: Request, _res: Response, next: NextFunction): void {
  next(new ApiError(404, 'route_not_found', `Маршрут ${req.method} ${req.path} не найден`));
}

/**
 * Финальный обработчик ошибок. Всё, что не `ApiError`, считаем внутренней ошибкой
 * и наружу подробности не отдаём — только в лог.
 */
export function errorHandler(
  err: unknown,
  req: Request,
  res: Response,
  _next: NextFunction,
): void {
  if (err instanceof ApiError) {
    if (err.status >= 500) {
      console.error(`[api] ${req.method} ${req.path} → ${err.code}`, err.details);
    }
    res.status(err.status).json({
      error: { code: err.code, message: err.message, details: err.details },
    });
    return;
  }

  const message = err instanceof Error ? err.message : String(err);
  console.error(`[api] необработанная ошибка на ${req.method} ${req.path}: ${message}`);
  if (err instanceof Error && err.stack && config.logLevel === 'debug') {
    console.error(err.stack);
  }

  res.status(500).json({
    error: {
      code: 'internal_error',
      message: 'Внутренняя ошибка сервиса',
      details: config.env === 'production' ? null : message,
    },
  });
}

/** Запрос ушёл дольше этого — пишем предупреждение в лог. */
export const SLOW_REQUEST_MS = 800;

/** Простое логирование запросов: метод, путь, статус, длительность. */
export function requestLogger(req: Request, res: Response, next: NextFunction): void {
  const startedAt = Date.now();
  res.on('finish', () => {
    const ms = Date.now() - startedAt;
    const line = `[api] ${req.method} ${req.originalUrl} ${res.statusCode} ${ms}ms`;
    if (ms > SLOW_REQUEST_MS) console.warn(`${line} (медленно)`);
    else if (config.logLevel === 'debug') console.log(line);
  });
  next();
}
