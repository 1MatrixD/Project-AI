'use client';

import { useEffect, useRef, useState } from 'react';
import type { CourierPositionEvent, OrderStatus } from '@/types';
import { apiUrl, getToken } from '@/lib/api';
import { isFinal } from '@/lib/statuses';

/**
 * Подписка на SSE-стрим заказа: `GET /api/v2/orders/{id}/stream`.
 * Бэкенд шлёт два типа событий — `status` и `courier_position`.
 *
 * EventSource не умеет заголовки, поэтому токен уезжает query-параметром;
 * на бэке он проверяется тем же зависимостью, что и Authorization.
 */

const MIN_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;

export type StreamState = 'connecting' | 'open' | 'closed' | 'error';

export interface OrderStreamResult {
  status: OrderStatus | null;
  position: CourierPositionEvent | null;
  state: StreamState;
  /** Сколько раз переподключались — показываем в отладочной плашке. */
  retries: number;
}

const DEBUG = process.env.NEXT_PUBLIC_DEBUG_STREAM === '1';

export function useOrderStream(orderId: string, initialStatus: OrderStatus | null): OrderStreamResult {
  const [status, setStatus] = useState<OrderStatus | null>(initialStatus);
  const [position, setPosition] = useState<CourierPositionEvent | null>(null);
  const [state, setState] = useState<StreamState>('connecting');
  const [retries, setRetries] = useState(0);

  const backoffRef = useRef(MIN_BACKOFF_MS);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const stoppedRef = useRef(false);

  useEffect(() => {
    if (!orderId) return;
    stoppedRef.current = false;

    const closeSource = () => {
      sourceRef.current?.close();
      sourceRef.current = null;
    };

    const connect = () => {
      if (stoppedRef.current) return;
      setState('connecting');

      const token = getToken();
      const url = apiUrl(`/api/v2/orders/${orderId}/stream${token ? `?token=${token}` : ''}`);
      const es = new EventSource(url);
      sourceRef.current = es;

      es.onopen = () => {
        // Успешное подключение сбрасывает задержку переподключения.
        backoffRef.current = MIN_BACKOFF_MS;
        setState('open');
      };

      es.addEventListener('status', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { status: OrderStatus };
        if (DEBUG) console.debug('[stream] status', payload.status);
        setStatus(payload.status);
        if (isFinal(payload.status)) {
          // Заказ дошёл до терминального статуса — стрим больше не нужен.
          stoppedRef.current = true;
          closeSource();
          setState('closed');
        }
      });

      es.addEventListener('courier_position', (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as CourierPositionEvent;
        setPosition(payload);
      });

      es.onerror = () => {
        closeSource();
        if (stoppedRef.current) return;
        setState('error');
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS);
        setRetries((n) => n + 1);
        if (DEBUG) console.debug('[stream] reconnect in', delay);
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      stoppedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      closeSource();
    };
  }, [orderId]);

  return { status, position, state, retries };
}
