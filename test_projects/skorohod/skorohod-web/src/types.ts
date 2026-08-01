/**
 * Типы контракта с skorohod-api (FastAPI).
 * Все денежные поля — целые копейки, суффикс `_kop`.
 */

/** Полный набор статусов заказа, который может прислать бэкенд. */
export type OrderStatus =
  | 'created'
  | 'paid'
  | 'cooking'
  | 'courier_assigned'
  | 'at_restaurant'
  | 'picked_up'
  | 'delivering'
  | 'delivered'
  | 'cancelled'
  | 'refunded';

export interface MenuItem {
  id: string;
  restaurant_id: string;
  title: string;
  description: string;
  price_kop: number;
  image_url: string | null;
  /** Блюдо временно недоступно (стоп-лист кухни). */
  is_available: boolean;
  category: string;
}

export interface Restaurant {
  id: string;
  title: string;
  cuisine: string;
  rating: number;
  /** Средняя длительность доставки в минутах по данным аналитики. */
  eta_minutes: number;
  logo_url: string | null;
  city: string;
  is_open: boolean;
}

export interface OrderItem {
  menu_item_id: string;
  title: string;
  qty: number;
  /** Цена за единицу на момент оформления. */
  price_kop: number;
}

export interface Courier {
  name: string;
  phone: string;
  lat: number;
  lon: number;
}

export interface Order {
  id: string;
  status: OrderStatus;
  subtotal_kop: number;
  delivery_kop: number;
  discount_kop: number;
  total_kop: number;
  promo_code: string | null;
  items: OrderItem[];
  restaurant: Pick<Restaurant, 'id' | 'title' | 'logo_url'>;
  courier: Courier | null;
  created_at: string;
}

export interface Promo {
  code: string;
  /** Скидка в процентах, если задана. Взаимоисключима с `discount_kop`. */
  percent: number | null;
  discount_kop: number | null;
  /** Минимальная сумма заказа, при которой промокод применим. */
  min_total_kop: number;
  active: boolean;
  expires_at: string | null;
}

/** Строка отчёта `GET /api/admin/reports/couriers?date=`. */
export interface CourierReportRow {
  courier_id: string;
  name: string;
  orders_count: number;
  delivered_count: number;
  cancelled_count: number;
  avg_delivery_minutes: number;
  earnings_kop: number;
}

/** Тело `POST /api/v2/orders`. */
export interface CreateOrderPayload {
  restaurant_id: string;
  address: string;
  comment: string;
  promo_code: string | null;
  items: Array<{ menu_item_id: string; qty: number }>;
}

/** Событие `courier_position` из SSE-стрима заказа. */
export interface CourierPositionEvent {
  lat: number;
  lon: number;
  /** ISO-время замера на стороне курьерского приложения. */
  at: string;
}
