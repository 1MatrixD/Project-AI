import type {
  AvailabilityResponse,
  Booking,
  BookingsQuery,
  CreateBookingPayload,
  Item,
  ItemsQuery,
  Quote,
  ReturnPayload,
  ReturnReceipt,
  RevenueReport,
} from '../types';

const BASE_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8030').replace(/\/+$/, '');
const TIMEOUT_MS = 8000;

/** Ошибка API с кодом от бэка: показываем текст пользователю, код — в логи. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Сеть отвалилась или таймаут — есть смысл предложить «Повторить». */
  get isOffline(): boolean {
    return this.status === 0;
  }
}

function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

function parseBody(text: string): any {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init.headers ?? {}),
      },
    });

    const body = parseBody(await response.text());

    if (!response.ok) {
      throw new ApiError(
        response.status,
        body?.code ?? 'http_error',
        body?.message ?? `Запрос ${path} завершился с кодом ${response.status}`,
        body?.details,
      );
    }

    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'timeout', 'Сервер не ответил за 8 секунд. Попробуйте ещё раз.');
    }
    throw new ApiError(0, 'network', 'Нет связи с сервисом бронирования. Проверьте интернет.');
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  items: {
    list(query: ItemsQuery = {}): Promise<Item[]> {
      return request<Item[]>(`/api/items${buildQuery({ ...query })}`);
    },
    get(id: string): Promise<Item> {
      return request<Item>(`/api/items/${encodeURIComponent(id)}`);
    },
    availability(id: string, days = 14): Promise<AvailabilityResponse> {
      return request<AvailabilityResponse>(
        `/api/items/${encodeURIComponent(id)}/availability${buildQuery({ days })}`,
      );
    },
  },

  bookings: {
    list(query: BookingsQuery = {}): Promise<Booking[]> {
      return request<Booking[]>(`/api/bookings${buildQuery({ ...query })}`);
    },
    create(payload: CreateBookingPayload): Promise<Booking> {
      return request<Booking>('/api/bookings', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    cancel(id: string, reason?: string): Promise<Booking> {
      return request<Booking>(`/api/bookings/${encodeURIComponent(id)}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason: reason ?? 'client_cancel' }),
      });
    },
    /** Пересчёт брони на сервере — источник истины по деньгам. */
    quote(id: string, range: { startAt: string; endAt: string }): Promise<Quote> {
      return request<Quote>(`/api/bookings/${encodeURIComponent(id)}/quote`, {
        method: 'POST',
        body: JSON.stringify(range),
      });
    },
  },

  returns: {
    create(payload: ReturnPayload): Promise<ReturnReceipt> {
      return request<ReturnReceipt>('/api/returns', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
  },

  reports: {
    revenue(from: string, to: string): Promise<RevenueReport> {
      return request<RevenueReport>(`/api/reports/revenue${buildQuery({ from, to })}`);
    },
  },
};
