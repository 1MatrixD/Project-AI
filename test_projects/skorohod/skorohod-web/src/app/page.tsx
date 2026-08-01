'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import clsx from 'clsx';
import type { MenuItem, Restaurant } from '@/types';
import { apiGet, ApiError, qs } from '@/lib/api';
import { addItem, readCart, removeItem, subscribeCart } from '@/lib/cart';
import { formatKop } from '@/lib/format';
import CartSummary from '@/components/CartSummary';

const CITY = process.env.NEXT_PUBLIC_DEFAULT_CITY ?? 'msk';

/** Витрина: слева список ресторанов и меню, справа корзина. */
export default function HomePage() {
  const router = useRouter();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuItem[]>([]);
  const [cart, setCart] = useState(() => readCart());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => subscribeCart(() => setCart(readCart())), []);

  useEffect(() => {
    apiGet<Restaurant[]>(`/api/v2/restaurants${qs({ city: CITY })}`)
      .then((list) => {
        setRestaurants(list);
        // Открываем первый работающий ресторан, чтобы страница не была пустой.
        const first = list.find((r) => r.is_open) ?? list[0];
        setActiveId(first ? first.id : null);
      })
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить рестораны'),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!activeId) return;
    apiGet<MenuItem[]>(`/api/v2/restaurants/${activeId}/menu`)
      .then(setMenu)
      .catch(() => setMenu([]));
  }, [activeId]);

  const handleAdd = useCallback((item: MenuItem) => {
    setCart(addItem(item));
  }, []);

  const handleInc = useCallback(
    (menuItemId: string) => {
      const item = menu.find((m) => m.id === menuItemId);
      if (item) setCart(addItem(item));
    },
    [menu],
  );

  const handleDec = useCallback((menuItemId: string) => {
    setCart(removeItem(menuItemId));
  }, []);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section>
        <h1 className="text-xl font-semibold">Рестораны рядом</h1>

        {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}

        <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
          {loading &&
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skh-skeleton h-9 w-36 shrink-0" />
            ))}
          {restaurants.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setActiveId(r.id)}
              disabled={!r.is_open}
              className={clsx(
                'shrink-0 rounded-full border px-3 py-1.5 text-sm transition-colors',
                r.id === activeId
                  ? 'border-brand-500 bg-brand-50 text-brand-700'
                  : 'border-black/10 bg-white text-ink-600 hover:border-brand-300',
                !r.is_open && 'opacity-40',
              )}
              title={r.is_open ? `${r.cuisine} · ~${r.eta_minutes} мин` : 'Сейчас закрыт'}
            >
              {r.title}
              <span className="ml-1.5 text-xs text-ink-400">{r.rating.toFixed(1)}</span>
            </button>
          ))}
        </div>

        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {menu.map((item) => (
            <li key={item.id} className="skh-card flex flex-col p-3">
              <p className="text-sm font-medium">{item.title}</p>
              <p className="mt-1 line-clamp-2 flex-1 text-xs text-ink-400">
                {item.description}
              </p>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-sm font-semibold tabular-nums">
                  {formatKop(item.price_kop)}
                </span>
                <button
                  type="button"
                  className="skh-btn-primary"
                  disabled={!item.is_available}
                  onClick={() => handleAdd(item)}
                >
                  {item.is_available ? 'В корзину' : 'Нет в наличии'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <aside className="lg:sticky lg:top-[calc(var(--header-h)+16px)] lg:h-fit">
        <CartSummary
          lines={cart.lines}
          promo={null}
          onInc={handleInc}
          onDec={handleDec}
          action={
            <button
              type="button"
              className="skh-btn-primary w-full"
              onClick={() => router.push('/checkout')}
            >
              Оформить заказ
            </button>
          }
        />
      </aside>
    </div>
  );
}
