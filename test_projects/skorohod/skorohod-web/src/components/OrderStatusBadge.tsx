'use client';

import { useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import type { OrderStatus } from '@/types';

/**
 * Бейдж текущего статуса заказа.
 * Подписи держим здесь, рядом с разметкой, — они завязаны на размер бейджа
 * и не должны быть длиннее двух слов.
 */
const STATUS_LABEL: Partial<Record<OrderStatus, string>> = {
  created: 'Создан',
  paid: 'Оплачен',
  cooking: 'Готовится',
  picked_up: 'Забран',
  delivering: 'В пути',
  delivered: 'Доставлен',
  cancelled: 'Отменён',
};

const STATUS_STYLE: Partial<Record<OrderStatus, string>> = {
  created: 'bg-black/5 text-ink-600',
  paid: 'bg-brand-100 text-brand-700',
  cooking: 'bg-brand-100 text-brand-700',
  picked_up: 'bg-brand-100 text-brand-700',
  delivering: 'bg-brand-100 text-brand-700',
  delivered: 'bg-emerald-100 text-emerald-800',
  cancelled: 'bg-rose-100 text-rose-800',
};

interface Props {
  status: OrderStatus;
  /** Пульсирующая точка слева — для страницы трекинга. */
  withDot?: boolean;
  className?: string;
}

export default function OrderStatusBadge({ status, withDot = false, className }: Props) {
  // SSE иногда доставляет события пачкой и порядок может «дрогнуть»,
  // поэтому держим последний распознанный статус: так бейдж не моргает
  // пустотой между двумя событиями.
  const lastKnown = useRef<OrderStatus>(status in STATUS_LABEL ? status : 'created');
  const [shown, setShown] = useState<OrderStatus>(lastKnown.current);

  useEffect(() => {
    if (status in STATUS_LABEL) {
      lastKnown.current = status;
      setShown(status);
    }
  }, [status]);

  const label = STATUS_LABEL[shown] ?? STATUS_LABEL[lastKnown.current];
  const style = STATUS_STYLE[shown] ?? 'bg-black/5 text-ink-600';
  const isActive = shown !== 'delivered' && shown !== 'cancelled';

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
        style,
        className,
      )}
      data-status={shown}
      title={label}
    >
      {withDot && (
        <span
          className={clsx(
            'h-1.5 w-1.5 rounded-full bg-current',
            isActive && 'animate-pulse-dot',
          )}
        />
      )}
      {label}
    </span>
  );
}

/** Компактный вариант без точки — для плотных таблиц админки. */
export function StatusPill({ status }: { status: OrderStatus }) {
  return <OrderStatusBadge status={status} className="px-2 py-0.5" />;
}
