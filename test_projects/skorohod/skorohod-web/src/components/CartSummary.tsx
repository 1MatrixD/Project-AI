'use client';

import clsx from 'clsx';
import type { Promo } from '@/types';
import { calcTotals, freeDeliveryGapKop, type CartLine } from '@/lib/price';
import { formatKop, formatDiscountKop, pluralizeWithCount } from '@/lib/format';

/**
 * Сводка корзины: позиции, доставка, скидка, итог.
 * Все суммы считает lib/price.ts, здесь только отрисовка.
 */

interface Props {
  lines: CartLine[];
  promo: Promo | null;
  /** Кнопка внизу сводки — на витрине это «Оформить», на чекауте её нет. */
  action?: React.ReactNode;
  onInc?: (menuItemId: string) => void;
  onDec?: (menuItemId: string) => void;
  className?: string;
}

export default function CartSummary({
  lines,
  promo,
  action,
  onInc,
  onDec,
  className,
}: Props) {
  const totals = calcTotals(lines, promo);
  const count = lines.reduce((acc, l) => acc + l.qty, 0);
  const freeGap = freeDeliveryGapKop(lines);

  if (lines.length === 0) {
    return (
      <div className={clsx('skh-card p-4 text-sm text-ink-400', className)}>
        Корзина пуста. Выберите блюда в меню слева.
      </div>
    );
  }

  return (
    <div className={clsx('skh-card p-4', className)}>
      <h2 className="text-sm font-semibold">
        Корзина · {pluralizeWithCount(count, ['позиция', 'позиции', 'позиций'])}
      </h2>

      <ul className="mt-3 space-y-2">
        {lines.map((line) => (
          <li key={line.menu_item_id} className="flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate text-ink-600">{line.title}</span>
            {onDec && onInc ? (
              <span className="flex items-center gap-1.5">
                <button
                  type="button"
                  className="h-6 w-6 rounded-md border border-black/10 leading-none"
                  onClick={() => onDec(line.menu_item_id)}
                  aria-label={`Убрать ${line.title}`}
                >
                  −
                </button>
                <span className="w-5 text-center tabular-nums">{line.qty}</span>
                <button
                  type="button"
                  className="h-6 w-6 rounded-md border border-black/10 leading-none"
                  onClick={() => onInc(line.menu_item_id)}
                  aria-label={`Добавить ${line.title}`}
                >
                  +
                </button>
              </span>
            ) : (
              <span className="text-ink-400">× {line.qty}</span>
            )}
            <span className="w-20 text-right tabular-nums">
              {formatKop(line.price_kop * line.qty)}
            </span>
          </li>
        ))}
      </ul>

      <dl className="mt-4 space-y-1.5 border-t border-black/5 pt-3 text-sm">
        <div className="flex justify-between">
          <dt className="text-ink-400">Блюда</dt>
          <dd className="tabular-nums">{formatKop(totals.subtotal_kop)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-ink-400">Доставка</dt>
          <dd className="tabular-nums">
            {totals.delivery_kop === 0 ? 'бесплатно' : formatKop(totals.delivery_kop)}
          </dd>
        </div>
        {totals.discount_kop > 0 && (
          <div className="flex justify-between text-emerald-700">
            <dt>Скидка {promo?.code ? `(${promo.code})` : ''}</dt>
            <dd className="tabular-nums">{formatDiscountKop(totals.discount_kop)}</dd>
          </div>
        )}
        <div className="flex justify-between border-t border-black/5 pt-2 text-base font-semibold">
          <dt>Итого</dt>
          <dd className="tabular-nums">{formatKop(totals.total_kop)}</dd>
        </div>
      </dl>

      {freeGap > 0 && (
        <p className="mt-2 text-xs text-ink-400">
          До бесплатной доставки не хватает {formatKop(freeGap)}
        </p>
      )}

      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
