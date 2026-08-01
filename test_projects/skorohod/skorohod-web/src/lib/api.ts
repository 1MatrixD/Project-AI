/**
 * Тонкая обёртка над fetch для похода в skorohod-api.
 * Базовый URL берём из окружения, токен — из localStorage.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8020';
const TOKEN_KEY = 'skh_token';

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
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(TOKEN_KEY);
}

/** Полный URL для эндпоинта API — пригождается ещё и для EventSource. */
export function apiUrl(path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${BASE_URL}${clean}`;
}

function buildHeaders(hasBody: boolean): HeadersInit {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (hasBody) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

async function parseError(res: Response): Promise<ApiError> {
  let code = 'unknown';
  let message = `Ошибка ${res.status}`;
  let details: unknown = null;
  try {
    const body = await res.json();
    // FastAPI отдаёт либо {detail: "..."}, либо наш {error: {code, message}}
    if (body?.error?.code) {
      code = body.error.code;
      message = body.error.message ?? message;
      details = body.error.details ?? null;
    } else if (typeof body?.detail === 'string') {
      message = body.detail;
    } else if (Array.isArray(body?.detail)) {
      code = 'validation_error';
      message = 'Проверьте заполненные поля';
      details = body.detail;
    }
  } catch {
    // тело не JSON — оставляем сообщение по статусу
  }
  return new ApiError(res.status, code, message, details);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method,
    headers: buildHeaders(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  });

  if (res.status === 401) {
    // Токен протух — чистим, чтобы страница ушла на форму входа.
    clearToken();
    throw new ApiError(401, 'unauthorized', 'Нужно войти заново');
  }

  if (!res.ok) {
    throw await parseError(res);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>('GET', path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body ?? {});
}

/** Собирает query-строку, отбрасывая пустые значения. */
export function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    sp.set(key, String(value));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}
