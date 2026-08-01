'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { CreateOrderPayload, Order, Promo } from '@/types';
import { apiPost, ApiError } from '@/lib/api';
import { clearCart, readCart, removeItem, addItemQty } from '@/lib/cart';
import { calcTotals } from '@/lib/price';
import { formatKop } from '@/lib/format';
import CartSummary from '@/components/CartSummary';
import PromoInput from '@/components/PromoInput';

/** Чекаут: адрес, комментарий, промокод и отправка заказа на бэк. */
export default function CheckoutPage() {
  const router = useRouter();
  const [cart, setCart] = useState(() => readCart());
  const [address, setAddress] = useState('');
  const [comment, setComment] = useState('');
  const [promo, setPromo] = useState<Promo | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCart(readCart());
    // Последний адрес подставляем автоматически — так быстрее оформлять повторно.
    const saved = window.localStorage.getItem('skh_last_address');
    if (saved) setAddress(saved);
  }, []);

  const totals = calcTotals(cart.lines, promo);
  const canSubmit = cart.lines.length > 0 && address.trim().length >= 5 && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !cart.restaurant_id) return;

    setSubmitting(true);
    setError(null);

    const payload: CreateOrderPayload = {
      restaurant_id: cart.restaurant_id,
      address: address.trim(),
      comment: comment.trim(),
      promo_code: promo?.code ?? null,
      items: cart.lines.map((l) => ({ menu_item_id: l.menu_item_id, qty: l.qty })),
    };

    try {
      const order = await apiPost<Order>('/api/v2/orders', payload);
      window.localStorage.setItem('skh_last_address', payload.address);
      clearCart();
      router.push(`/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось оформить заказ');
      setSubmitting(false);
    }
  }

  if (cart.lines.length === 0) {
    return (
      <div className="skh-card mx-auto max-w-lg p-6 text-center">
        <p className="text-sm text-ink-600">Корзина пуста</p>
        <button
          type="button"
          className="skh-btn-primary mt-4"
          onClick={() => router.push('/')}
        >
          Выбрать ресторан
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <section className="space-y-4">
        <h1 className="text-xl font-semibold">Оформление заказа</h1>

        <div className="skh-card space-y-4 p-4">
          <div>
            <label className="skh-label" htmlFor="address">
              Адрес доставки
            </label>
            <input
              id="address"
              className="skh-input"
              placeholder="ул. Ленина, 15, кв. 42"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="skh-label" htmlFor="comment">
              Комментарий курьеру
            </label>
            <textarea
              id="comment"
              className="skh-input min-h-20 resize-y"
              placeholder="Код домофона, этаж, не звонить в дверь…"
              value={comment}
              maxLength={300}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>

          <PromoInput lines={cart.lines} promo={promo} onApply={setPromo} />
        </div>

        {error && (
          <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
        )}
      </section>

      <aside className="space-y-3 lg:sticky lg:top-[calc(var(--header-h)+16px)] lg:h-fit">
        <CartSummary
          lines={cart.lines}
          promo={promo}
          onInc={(id) => setCart(addItemQty(id, 1))}
          onDec={(id) => setCart(removeItem(id))}
        />
        <button type="submit" className="skh-btn-primary w-full" disabled={!canSubmit}>
          {submitting ? 'Отправляем…' : `Заказать за ${formatKop(totals.total_kop)}`}
        </button>
        <p className="text-center text-xs text-ink-400">
          Нажимая кнопку, вы соглашаетесь с условиями сервиса
        </p>
      </aside>
    </form>
  );
}
