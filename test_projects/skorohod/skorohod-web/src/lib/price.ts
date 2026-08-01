import type { Promo } from '@/types';

/**
 * Клиентский предрасчёт корзины.
 *
 * Нужен, чтобы пользователь видел итог сразу, без похода на сервер:
 * дёргать `POST /api/v2/orders/preview` на каждое нажатие «+» — слишком дорого.
 * Финальную сумму всё равно считает бэкенд при создании заказа.
 */

/** Базовая стоимость доставки, копейки. */
export const DELIVERY_BASE_KOP = 14_900;

/** Порог бесплатной доставки, копейки. */
export const FREE_DELIVERY_FROM_KOP = 250_000;

export interface CartLine {
  menu_item_id: string;
  title: string;
  qty: number;
  price_kop: number;
}

export interface PriceBreakdown {
  subtotal_kop: number;
  delivery_kop: number;
  discount_kop: number;
  total_kop: number;
}

/** Сумма позиций корзины без доставки и скидок. */
export function calcSubtotal(lines: CartLine[]): number {
  return lines.reduce((acc, line) => acc + line.price_kop * line.qty, 0);
}

/**
 * Стоимость доставки по тарифу «Скорохода»:
 * фиксированные 149 ₽, при заказе от 2500 ₽ — бесплатно.
 */
export function calcDelivery(subtotalKop: number): number {
  if (subtotalKop >= FREE_DELIVERY_FROM_KOP) return 0;
  return DELIVERY_BASE_KOP;
}

/**
 * Скидка по промокоду. Процент округляем вниз до целых копеек —
 * так же, как это делает бэкенд.
 */
export function calcDiscount(subtotalKop: number, promo: Promo | null): number {
  if (!promo || !promo.active) return 0;
  if (promo.percent !== null) {
    return Math.floor((subtotalKop * promo.percent) / 100);
  }
  if (promo.discount_kop !== null) {
    // Скидка не может превышать стоимость самих блюд.
    return Math.min(promo.discount_kop, subtotalKop);
  }
  return 0;
}

/** Полный расчёт корзины: то, что показываем в сводке и на чекауте. */
export function calcTotals(lines: CartLine[], promo: Promo | null): PriceBreakdown {
  const subtotal_kop = calcSubtotal(lines);
  const delivery_kop = calcDelivery(subtotal_kop);
  const discount_kop = calcDiscount(subtotal_kop, promo);
  const total_kop = subtotal_kop + delivery_kop - discount_kop;

  return { subtotal_kop, delivery_kop, discount_kop, total_kop };
}

/**
 * Проверка применимости промокода.
 * Порог `min_total_kop` сравниваем с итогом заказа — именно эту сумму
 * клиент в результате платит.
 */
export function isPromoApplicable(lines: CartLine[], promo: Promo | null): boolean {
  if (!promo || !promo.active) return false;
  if (promo.expires_at && new Date(promo.expires_at).getTime() < Date.now()) {
    return false;
  }
  const subtotal = calcSubtotal(lines);
  const delivery = calcDelivery(subtotal);
  const total = subtotal + delivery;
  return total >= promo.min_total_kop;
}

/** Сколько не хватает до порога промокода — для подсказки в интерфейсе. */
export function promoGapKop(lines: CartLine[], promo: Promo): number {
  const subtotal = calcSubtotal(lines);
  const total = subtotal + calcDelivery(subtotal);
  return Math.max(0, promo.min_total_kop - total);
}

/** Сколько не хватает до бесплатной доставки. */
export function freeDeliveryGapKop(lines: CartLine[]): number {
  const subtotal = calcSubtotal(lines);
  return Math.max(0, FREE_DELIVERY_FROM_KOP - subtotal);
}
