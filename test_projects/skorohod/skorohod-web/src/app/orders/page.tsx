'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import type { Order, OrderStatus } from '@/types';
import { apiGet, ApiError, qs } from '@/lib/api';
import { isFinal, STATUS_META } from '@/lib/statuses';
import { pluralizeWithCount } from '@/lib/format';
import OrderCard from '@/components/OrderCard';

type Filter = 'active' | 'all';

/** Список заказов пользователя. */
export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [filter, setFilter] = useState<Filter>('active');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    apiGet<Order[]>(`/api/v2/orders${qs({ limit: 50 })}`)
      .then(setOrders)
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить заказы'),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Активные заказы обновляем сами: пользователь может держать вкладку открытой,
  // а SSE тут не поднимаем — слишком много одновременных стримов.
  useEffect(() => {
    const hasActive = orders.some((o) => !isFinal(o.status));
    if (!hasActive) return;
    const id = setInterval(load, 20_000);
    return () => clearInterval(id);
  }, [orders, load]);

  const visible = orders.filter((o) => (filter === 'active' ? !isFinal(o.status) : true));

  const byStatus = visible.reduce<Partial<Record<OrderStatus, number>>>((acc, o) => {
    acc[o.status] = (acc[o.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="mx-auto max-w-3xl">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-xl font-semibold">Мои заказы</h1>
        <div className="flex gap-1 rounded-lg bg-black/5 p-0.5 text-sm">
          {(['active', 'all'] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={clsx(
                'rounded-md px-3 py-1 transition-colors',
                filter === f ? 'bg-white text-ink-900 shadow-sm' : 'text-ink-400',
              )}
            >
              {f === 'active' ? 'Активные' : 'Все'}
            </button>
          ))}
        </div>
      </div>

      {/* Сводка по статусам — подписи берём из общей карты статусов. */}
      {visible.length > 0 && (
        <p className="mt-2 text-xs text-ink-400">
          {pluralizeWithCount(visible.length, ['заказ', 'заказа', 'заказов'])}
          {Object.entries(byStatus).length > 0 && ' · '}
          {Object.entries(byStatus)
            .map(([s, n]) => `${STATUS_META[s as OrderStatus].label}: ${n}`)
            .join(', ')}
        </p>
      )}

      {error && <p className="mt-4 text-sm text-rose-600">{error}</p>}

      {loading && orders.length === 0 && (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skh-skeleton h-40 w-full" />
          ))}
        </div>
      )}

      {!loading && visible.length === 0 && !error && (
        <div className="skh-card mt-4 p-6 text-center text-sm text-ink-400">
          {filter === 'active'
            ? 'Активных заказов нет. Загляните в раздел «Все».'
            : 'Вы пока ничего не заказывали.'}
        </div>
      )}

      <div className="mt-4 space-y-3">
        {visible.map((order) => (
          <OrderCard key={order.id} order={order} onChanged={load} />
        ))}
      </div>
    </div>
  );
}
