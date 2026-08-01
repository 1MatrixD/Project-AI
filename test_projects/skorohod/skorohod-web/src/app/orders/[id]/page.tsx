'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import type { Courier, Order } from '@/types';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import { useOrderStream } from '@/lib/useOrderStream';
import { isCancellable } from '@/lib/statuses';
import { formatKop, formatDateTime, formatDiscountKop } from '@/lib/format';
import OrderStatusBadge from '@/components/OrderStatusBadge';
import Timeline from '@/components/Timeline';
import CourierMap from '@/components/CourierMap';

/** Трекинг заказа: статус, таймлайн, карта курьера. */
export default function OrderTrackingPage() {
  const params = useParams<{ id: string }>();
  const orderId = params.id;

  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    apiGet<Order>(`/api/v2/orders/${orderId}`)
      .then(setOrder)
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : 'Заказ не найден'),
      );
  }, [orderId]);

  const stream = useOrderStream(orderId, order?.status ?? null);
  const status = stream.status ?? order?.status ?? 'created';

  // Позиция курьера из стрима свежее, чем из GET-запроса.
  const courier: Courier | null = order?.courier
    ? {
        ...order.courier,
        lat: stream.position?.lat ?? order.courier.lat,
        lon: stream.position?.lon ?? order.courier.lon,
      }
    : null;

  async function handleCancel() {
    if (!order || !window.confirm('Отменить заказ?')) return;
    setCancelling(true);
    try {
      const updated = await apiPost<Order>(`/api/v2/orders/${order.id}/cancel`);
      setOrder(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось отменить заказ');
    } finally {
      setCancelling(false);
    }
  }

  if (error) {
    return <p className="mx-auto max-w-lg text-sm text-rose-600">{error}</p>;
  }

  if (!order) {
    return <div className="skh-skeleton mx-auto h-64 max-w-3xl" />;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{order.restaurant.title}</h1>
          <p className="mt-0.5 text-xs text-ink-400">
            Заказ №{order.id.slice(0, 8)} от {formatDateTime(order.created_at)}
          </p>
        </div>
        <OrderStatusBadge status={status} withDot />
      </header>

      <div className="grid gap-5 sm:grid-cols-[220px_1fr]">
        <Timeline status={status} createdAt={formatDateTime(order.created_at)} />

        <div className="space-y-4">
          <CourierMap courier={courier} />

          {courier && (
            <div className="skh-card flex items-center justify-between p-3 text-sm">
              <span>
                Курьер <span className="font-medium">{courier.name}</span>
              </span>
              <a href={`tel:${courier.phone}`} className="skh-btn-ghost">
                Позвонить
              </a>
            </div>
          )}
        </div>
      </div>

      <section className="skh-card p-4">
        <h2 className="text-sm font-semibold">Состав заказа</h2>
        <ul className="mt-2 space-y-1 text-sm">
          {order.items.map((item) => (
            <li key={item.menu_item_id} className="flex justify-between text-ink-600">
              <span>
                {item.title} × {item.qty}
              </span>
              <span className="tabular-nums">{formatKop(item.price_kop * item.qty)}</span>
            </li>
          ))}
        </ul>

        <dl className="mt-3 space-y-1 border-t border-black/5 pt-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-ink-400">Доставка</dt>
            <dd className="tabular-nums">{formatKop(order.delivery_kop)}</dd>
          </div>
          {order.discount_kop > 0 && (
            <div className="flex justify-between text-emerald-700">
              <dt>Скидка {order.promo_code ? `(${order.promo_code})` : ''}</dt>
              <dd className="tabular-nums">{formatDiscountKop(order.discount_kop)}</dd>
            </div>
          )}
          <div className="flex justify-between pt-1 font-semibold">
            <dt>Итого</dt>
            <dd className="tabular-nums">{formatKop(order.total_kop)}</dd>
          </div>
        </dl>
      </section>

      {isCancellable(status) && (
        <button
          type="button"
          className="skh-btn-ghost"
          onClick={handleCancel}
          disabled={cancelling}
        >
          {cancelling ? 'Отменяем…' : 'Отменить заказ'}
        </button>
      )}

      {stream.state === 'error' && (
        <p className="text-xs text-ink-400">
          Связь с сервером потеряна, переподключаемся… (попытка {stream.retries})
        </p>
      )}
    </div>
  );
}
