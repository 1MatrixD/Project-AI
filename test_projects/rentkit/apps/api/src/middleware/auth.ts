/**
 * Авторизация по JWT.
 *
 * Токен выдаёт внутренний сервис учёток, мы только проверяем подпись HS256 и
 * издателя. В токене лежат `sub` (идентификатор пользователя), `role` и, для
 * клиентов, `customerId` — по нему ограничиваем доступ к чужим броням.
 */

import type { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import type { UserRole } from '@rentkit/core';
import { config } from '../config.js';
import { ApiError } from './errors.js';

export interface AuthUser {
  id: string;
  role: UserRole;
  customerId: string | null;
  name: string;
}

declare module 'express-serve-static-core' {
  interface Request {
    user?: AuthUser;
  }
}

interface TokenPayload {
  sub: string;
  role: UserRole;
  customerId?: string;
  name?: string;
}

function readBearer(req: Request): string | null {
  const header = req.headers.authorization;
  if (!header || typeof header !== 'string') return null;
  const [scheme, token] = header.split(' ');
  if (!token || scheme.toLowerCase() !== 'bearer') return null;
  return token.trim();
}

function verify(token: string): AuthUser {
  let payload: TokenPayload;
  try {
    payload = jwt.verify(token, config.jwtSecret, {
      algorithms: ['HS256'],
      issuer: config.jwtIssuer,
    }) as TokenPayload;
  } catch (err) {
    const reason = err instanceof Error ? err.message : 'неизвестная ошибка';
    throw ApiError.unauthorized(`Токен отклонён: ${reason}`);
  }

  if (!payload.sub || (payload.role !== 'staff' && payload.role !== 'customer')) {
    throw ApiError.unauthorized('В токене нет роли или идентификатора');
  }

  return {
    id: payload.sub,
    role: payload.role,
    customerId: payload.customerId ?? (payload.role === 'customer' ? payload.sub : null),
    name: payload.name ?? payload.sub,
  };
}

/** Пускает и без токена, но если токен есть — разбирает его. Для публичного каталога. */
export function optionalAuth(req: Request, _res: Response, next: NextFunction): void {
  const token = readBearer(req);
  if (!token) {
    next();
    return;
  }
  try {
    req.user = verify(token);
    next();
  } catch (err) {
    next(err);
  }
}

/** Требует любого авторизованного пользователя. */
export function requireAuth(req: Request, _res: Response, next: NextFunction): void {
  const token = readBearer(req);
  if (!token) {
    next(ApiError.unauthorized('Не передан заголовок Authorization'));
    return;
  }
  try {
    req.user = verify(token);
    next();
  } catch (err) {
    next(err);
  }
}

/**
 * Требует сотрудника пункта выдачи.
 * Ставится на возвраты, отмены, ручные операции с депозитом и отчёты.
 */
export function requireStaff(req: Request, res: Response, next: NextFunction): void {
  requireAuth(req, res, (err?: unknown) => {
    if (err) {
      next(err);
      return;
    }
    if (req.user?.role !== 'staff') {
      next(ApiError.forbidden('Операция доступна только сотрудникам пункта выдачи'));
      return;
    }
    next();
  });
}

/**
 * Клиент видит только свои брони, сотрудник — все.
 * Возвращает идентификатор клиента, которым надо ограничить выборку, либо `null`.
 */
export function customerScope(req: Request): string | null {
  if (!req.user || req.user.role === 'staff') return null;
  return req.user.customerId;
}

/** Проверка доступа к конкретной брони по её владельцу. */
export function assertOwnsBooking(req: Request, ownerId: string): void {
  const scope = customerScope(req);
  if (scope !== null && scope !== ownerId) {
    throw ApiError.forbidden('Бронь принадлежит другому клиенту');
  }
}
