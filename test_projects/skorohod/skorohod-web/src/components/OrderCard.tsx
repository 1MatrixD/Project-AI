'use client';

import { useState } from 'react';
import Link from 'next/link';
import clsx from 'clsx';
import type { Order } from '@/types';
import { apiPost, ApiError } from '@/lib/api';
import { STATUS_META, toneClass, isCancellable } from '@/lib/statuses';
import { formatKop, formatDateTime, pluralizeWithCount } from '@/lib/format';

/** Карточка заказа в списке /orders. */

interface Props {
  order: Order;
  /** Дёргается после успешного повтора/отмены, чтобы список перезапросил данные. */
  onChanged?: () => void;
}

export default function OrderCard({ order, onChanged }: Props) {
  const [busy, setBusy] = useState<'repeat' | 'cancel' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const meta = STATUS_META[order.status];
  const itemsCount = order.items.reduce((acc, i) => acc + i.qty, 0);

  // Повторить можно всё, что содержит позиции: складываем те же блюда в новый заказ.
  const canRepeat = order.items.length > 0;

  async function handleRepeat() {
    setBusy('repeat');
    setError(null);
    try {
      await apiPost<Order>(`/api/v2/orders/${order.id}/repeat`);
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось повторить заказ');
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    if (!window.confirm('Отменить заказ?')) return;
    setBusy('cancel');
    setError(null);
    try {
      await apiPost<Order>(`/api/v2/orders/${order.id}/cancel`);
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось отменить заказ');
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="skh-card p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/orders/${order.id}`}
            className="text-sm font-semibold hover:text-brand-600"
          >
            {order.restaurant.title}
          </Link>
          <p className="mt-0.5 text-xs text-ink-400">
            {formatDateTime(order.created_at)} · {pluralizeWithCount(itemsCount, ['блюдо', 'блюда', 'блюд'])}
          </p>
        </div>
        <span
          className={clsx(
            'shrink-0 rounded-full px-2.5 py-1 text-xs font-medium',
            toneClass(meta.tone),
          )}
        >
          {meta.label}
        </span>
      </header>

      <ul className="mt-3 space-y-1">
        {order.items.slice(0, 3).map((item) => (
          <li key={item.menu_item_id} className="flex justify-between text-sm text-ink-600">
            <span className="truncate">
              {item.title} × {item.qty}
            </span>
            <span className="tabular-nums">{formatKop(item.price_kop * item.qty)}</span>
          </li>
        ))}
        {order.items.length > 3 && (
          <li className="text-xs text-ink-400">и ещё {order.items.length - 3}…</li>
        )}
      </ul>

      <footer className="mt-4 flex items-center justify-between gap-2 border-t border-black/5 pt-3">
        <span className="text-sm font-semibold tabular-nums">{formatKop(order.total_kop)}</span>
        <div className="flex gap-2">
          {isCancellable(order.status) && (
            <button
              type="button"
              className="skh-btn-ghost"
              onClick={handleCancel}
              disabled={busy !== null}
            >
              {busy === 'cancel' ? 'Отменяем…' : 'Отменить'}
            </button>
          )}
          {canRepeat && (
            <button
              type="button"
              className="skh-btn-primary"
              onClick={handleRepeat}
              disabled={busy !== null}
            >
              {busy === 'repeat' ? 'Повторяем…' : 'Повторить'}
            </button>
          )}
        </div>
      </footer>

      {error && <p className="mt-2 text-xs text-rose-600">{error}</p>}
    </article>
  );
}
