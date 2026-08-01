'use client';

import clsx from 'clsx';
import type { OrderStatus } from '@/types';
import { STATUS_META, TIMELINE_STEPS, stepIndex, isFinal } from '@/lib/statuses';

/**
 * Вертикальный таймлайн заказа.
 * Шаги и подписи берём из lib/statuses.ts — там полная карта статусов.
 */

interface Props {
  status: OrderStatus;
  /** Время создания заказа: подписываем им первый шаг. */
  createdAt?: string;
  className?: string;
}

export default function Timeline({ status, createdAt, className }: Props) {
  const current = stepIndex(status);

  // Отменённый заказ и возврат выпадают из «счастливого пути»:
  // рисуем короткую плашку вместо ленты шагов.
  if (current === -1 && isFinal(status)) {
    const meta = STATUS_META[status];
    return (
      <div className={clsx('skh-card p-4', className)}>
        <p className="text-sm font-medium text-rose-700">{meta.label}</p>
        <p className="mt-1 text-sm text-ink-400">{meta.hint}</p>
      </div>
    );
  }

  return (
    <ol className={clsx('relative space-y-0', className)}>
      {TIMELINE_STEPS.map((step, i) => {
        const meta = STATUS_META[step];
        const done = current > i;
        const active = current === i;
        const isLast = i === TIMELINE_STEPS.length - 1;

        return (
          <li key={step} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast && (
              <span
                className={clsx(
                  'absolute left-[7px] top-4 h-full w-px',
                  done ? 'bg-brand-500' : 'bg-black/10',
                )}
                aria-hidden
              />
            )}

            <span
              className={clsx(
                'relative z-10 mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2',
                done && 'border-brand-500 bg-brand-500',
                active && 'border-brand-500 bg-white animate-pulse-dot',
                !done && !active && 'border-black/15 bg-white',
              )}
              aria-hidden
            />

            <div className="min-w-0 flex-1">
              <p
                className={clsx(
                  'text-sm leading-5',
                  active ? 'font-semibold text-ink-900' : 'text-ink-600',
                  !done && !active && 'text-ink-400',
                )}
              >
                {meta.label}
              </p>
              {active && <p className="mt-0.5 text-xs text-ink-400">{meta.hint}</p>}
              {i === 0 && createdAt && (
                <p className="mt-0.5 text-xs text-ink-400">{createdAt}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
