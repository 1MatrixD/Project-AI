export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("projectai_token");
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem("projectai_token", token);
  else localStorage.removeItem("projectai_token");
}

/** Язык интерфейса → Accept-Language: бэкенд отдаёт ошибки и подписи на языке
 *  экрана. Берётся из <html lang>, который layout выставляет по локали next-intl. */
export function langHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const lang = document.documentElement.lang;
  return lang ? { "Accept-Language": lang } : {};
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    ...langHeaders(),
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData) && options.body) {
    headers["Content-Type"] = "application/json";
  }
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}/api${path}`, { ...options, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    setToken(null);
    if (!location.pathname.startsWith("/login")) location.href = "/login";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type SseEvent = {
  type: string;
  text?: string;
  name?: string;
  input?: string;
  detail?: string;
  meta?: Record<string, unknown>;
  job?: {
    id: string;
    type: string;
    status: string;
    progress: number;
    detail?: string;
    error?: string | null;
  };
};

async function readSseBody(res: Response, onEvent: (e: SseEvent) => void): Promise<void> {
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch {}
        }
      }
    }
  }
}

/** POST + чтение SSE-стрима (fetch, т.к. EventSource не умеет POST). */
export async function streamSse(
  path: string,
  body: unknown,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_URL}/api${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...langHeaders(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  await readSseBody(res, onEvent);
}

/** GET SSE-поток событий (fetch вместо EventSource — нужен заголовок Authorization). */
export async function streamEvents(
  path: string,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_URL}/api${path}`, {
    headers: { ...langHeaders(), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    signal,
  });
  await readSseBody(res, onEvent);
}
