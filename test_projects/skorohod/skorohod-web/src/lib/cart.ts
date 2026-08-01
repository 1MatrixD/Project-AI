'use client';

import type { MenuItem } from '@/types';
import { calcSubtotal, type CartLine } from '@/lib/price';

/**
 * Корзина живёт в localStorage: пользователь может уйти на страницу заказа
 * и вернуться, ничего не потеряв. Ресторан в корзине всегда один.
 */

const CART_KEY = 'skh_cart_v2';
const CART_EVENT = 'skh:cart-changed';

export interface CartState {
  restaurant_id: string | null;
  lines: CartLine[];
}

const EMPTY: CartState = { restaurant_id: null, lines: [] };

export function readCart(): CartState {
  if (typeof window === 'undefined') return EMPTY;
  try {
    const raw = window.localStorage.getItem(CART_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as CartState;
    if (!Array.isArray(parsed.lines)) return EMPTY;
    return parsed;
  } catch {
    // Битый JSON после старой версии формата — начинаем с чистой корзины.
    return EMPTY;
  }
}

function writeCart(state: CartState): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(CART_KEY, JSON.stringify(state));
  window.dispatchEvent(new CustomEvent(CART_EVENT));
}

/**
 * Добавляет блюдо. Если в корзине лежит другой ресторан — заменяем содержимое:
 * смешанные заказы бэкенд не принимает.
 */
export function addItem(item: MenuItem, qty = 1): CartState {
  const cart = readCart();
  const next: CartState =
    cart.restaurant_id && cart.restaurant_id !== item.restaurant_id
      ? { restaurant_id: item.restaurant_id, lines: [] }
      : { restaurant_id: item.restaurant_id, lines: [...cart.lines] };

  const existing = next.lines.find((l) => l.menu_item_id === item.id);
  if (existing) {
    existing.qty += qty;
  } else {
    next.lines.push({
      menu_item_id: item.id,
      title: item.title,
      qty,
      price_kop: item.price_kop,
    });
  }

  writeCart(next);
  return next;
}

/**
 * Увеличивает количество уже лежащей в корзине позиции.
 * На чекауте меню под рукой нет, поэтому работаем по id строки.
 */
export function addItemQty(menuItemId: string, qty = 1): CartState {
  const cart = readCart();
  const lines = cart.lines.map((line) =>
    line.menu_item_id === menuItemId ? { ...line, qty: line.qty + qty } : line,
  );
  const next: CartState = { restaurant_id: cart.restaurant_id, lines };
  writeCart(next);
  return next;
}

/** Уменьшает количество на 1; на нуле убирает строку целиком. */
export function removeItem(menuItemId: string): CartState {
  const cart = readCart();
  const lines: CartLine[] = [];
  for (const line of cart.lines) {
    if (line.menu_item_id !== menuItemId) {
      lines.push(line);
      continue;
    }
    if (line.qty > 1) lines.push({ ...line, qty: line.qty - 1 });
  }
  const next: CartState = {
    restaurant_id: lines.length ? cart.restaurant_id : null,
    lines,
  };
  writeCart(next);
  return next;
}

export function clearCart(): CartState {
  writeCart(EMPTY);
  return EMPTY;
}

export function cartSubtotalKop(): number {
  return calcSubtotal(readCart().lines);
}

export function cartItemsCount(): number {
  return readCart().lines.reduce((acc, l) => acc + l.qty, 0);
}

/** Подписка на изменения корзины — и из этой вкладки, и из соседней. */
export function subscribeCart(handler: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const onStorage = (e: StorageEvent) => {
    if (e.key === CART_KEY) handler();
  };
  window.addEventListener(CART_EVENT, handler);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(CART_EVENT, handler);
    window.removeEventListener('storage', onStorage);
  };
}
