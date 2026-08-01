'use client';

import { useState } from 'react';
import clsx from 'clsx';
import type { Promo } from '@/types';
import { apiGet, ApiError, qs } from '@/lib/api';
import { isPromoApplicable, promoGapKop, type CartLine } from '@/lib/price';
import { formatKop } from '@/lib/format';

/**
 * Ввод промокода на чекауте.
 * Код проверяем на бэке (`GET /api/admin/promos?code=` доступен и клиенту),
 * а применимость к текущей корзине считаем локально — мгновенная подсказка.
 */

interface Props {
  lines: CartLine[];
  promo: Promo | null;
  onApply: (promo: Promo | null) => void;
}

export default function PromoInput({ lines, promo, onApply }: Props) {
  const [code, setCode] = useState(promo?.code ?? '');
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCheck() {
    const normalized = code.trim().toUpperCase();
    if (!normalized) return;

    setChecking(true);
    setError(null);
    try {
      const found = await apiGet<Promo[]>(`/api/admin/promos${qs({ code: normalized })}`);
      const item = found.find((p) => p.code === normalized) ?? null;
      if (!item) {
        setError('Такого промокода нет');
        onApply(null);
        return;
      }
      if (!item.active) {
        setError('Промокод больше не действует');
        onApply(null);
        return;
      }
      onApply(item);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось проверить промокод');
      onApply(null);
    } finally {
      setChecking(false);
    }
  }

  function handleReset() {
    setCode('');
    setError(null);
    onApply(null);
  }

  const applicable = promo ? isPromoApplicable(lines, promo) : false;
  const gap = promo ? promoGapKop(lines, promo) : 0;

  return (
    <div>
      <label className="skh-label" htmlFor="promo">
        Промокод
      </label>
      <div className="flex gap-2">
        <input
          id="promo"
          className="skh-input uppercase"
          placeholder="SKOROHOD10"
          value={code}
          autoComplete="off"
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void handleCheck();
            }
          }}
        />
        {promo ? (
          <button type="button" className="skh-btn-ghost" onClick={handleReset}>
            Убрать
          </button>
        ) : (
          <button
            type="button"
            className="skh-btn-ghost"
            onClick={() => void handleCheck()}
            disabled={checking || !code.trim()}
          >
            {checking ? 'Проверяем…' : 'Применить'}
          </button>
        )}
      </div>

      {error && <p className="mt-1.5 text-xs text-rose-600">{error}</p>}

      {promo && !error && (
        <p
          className={clsx(
            'mt-1.5 text-xs',
            applicable ? 'text-emerald-700' : 'text-ink-400',
          )}
        >
          {applicable
            ? 'Промокод подойдёт — скидка учтена в итоге'
            : `Добавьте ещё на ${formatKop(gap)}, чтобы промокод сработал`}
        </p>
      )}
    </div>
  );
}
