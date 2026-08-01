/**
 * Конфигурация API.
 *
 * Читается один раз при старте процесса. Если обязательной переменной нет — падаем
 * сразу, а не через полчаса на первом запросе к базе. Значения по умолчанию заданы
 * только для локальной разработки, в проде всё приходит из окружения.
 */

export type AppEnv = 'development' | 'test' | 'production';

export interface AppConfig {
  env: AppEnv;
  port: number;
  databaseUrl: string;
  pgPoolMax: number;
  jwtSecret: string;
  jwtIssuer: string;
  paymentsKey: string;
  paymentsBaseUrl: string;
  corsOrigins: string[];
  smtpUrl: string | null;
  smsGatewayUrl: string | null;
  notifyFrom: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}

function required(name: string, fallback?: string): string {
  const value = process.env[name] ?? fallback;
  if (value === undefined || value === '') {
    throw new Error(`Не задана переменная окружения ${name}. Смотри .env.example`);
  }
  return value;
}

function optional(name: string): string | null {
  const value = process.env[name];
  return value === undefined || value === '' ? null : value;
}

function toInt(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readEnv(): AppEnv {
  const raw = process.env.NODE_ENV ?? 'development';
  if (raw === 'production' || raw === 'test') return raw;
  return 'development';
}

function loadConfig(): AppConfig {
  const env = readEnv();
  const isProd = env === 'production';

  const config: AppConfig = {
    env,
    port: toInt(process.env.PORT ?? '8030', 8030),
    databaseUrl: required('DATABASE_URL', isProd ? undefined : 'postgres://rentkit@localhost:5432/rentkit'),
    pgPoolMax: toInt(process.env.PG_POOL_MAX ?? '10', 10),
    jwtSecret: required('JWT_SECRET', isProd ? undefined : 'change-me'),
    jwtIssuer: process.env.JWT_ISSUER ?? 'rentkit',
    paymentsKey: required('PAYMENTS_KEY', isProd ? undefined : 'change-me'),
    paymentsBaseUrl: process.env.PAYMENTS_BASE_URL ?? 'https://sandbox.payments.example/v2',
    corsOrigins: (process.env.CORS_ORIGINS ?? 'http://localhost:5173')
      .split(',')
      .map((origin) => origin.trim())
      .filter(Boolean),
    smtpUrl: optional('SMTP_URL'),
    smsGatewayUrl: optional('SMS_GATEWAY_URL'),
    notifyFrom: process.env.NOTIFY_FROM ?? 'rentkit@example.com',
    logLevel: (process.env.LOG_LEVEL as AppConfig['logLevel']) ?? (isProd ? 'info' : 'debug'),
  };

  if (isProd && config.jwtSecret === 'change-me') {
    throw new Error('JWT_SECRET оставлен дефолтным в production');
  }
  if (isProd && config.paymentsKey === 'change-me') {
    throw new Error('PAYMENTS_KEY оставлен дефолтным в production');
  }

  return config;
}

export const config = loadConfig();

/** Срок жизни токена сотрудника — рабочая смена с запасом. */
export const TOKEN_TTL_SECONDS = 12 * 60 * 60;

/** Часовой пояс пункта выдачи. Используется в отчётах при группировке по дням. */
export const LOCATION_TZ = 'Europe/Moscow';

export function isProduction(): boolean {
  return config.env === 'production';
}
