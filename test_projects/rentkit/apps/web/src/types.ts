import type { Booking, BookingStatus, DateRange, Item } from '@rentkit/core';

// Доменные типы живут в packages/core — здесь только реэкспорт и вью-модели витрины.
export type { Booking, BookingStatus, DateRange, Item, Quote } from '@rentkit/core';

export type Category = Item['category'];
export type Condition = Item['condition'];

export const CATEGORIES: Category[] = ['camera', 'lens', 'light', 'audio', 'grip'];

export const CATEGORY_LABELS: Record<Category, string> = {
  camera: 'Камеры',
  lens: 'Оптика',
  light: 'Свет',
  audio: 'Звук',
  grip: 'Оснастка',
};

export const CONDITION_LABELS: Record<Condition, string> = {
  new: 'новое',
  good: 'рабочее',
  worn: 'с потёртостями',
};

export const STATUS_LABELS: Record<BookingStatus, string> = {
  draft: 'черновик',
  reserved: 'забронировано',
  active: 'на руках',
  returned: 'возвращено',
  cancelled: 'отменено',
  overdue: 'просрочено',
};

/** Фильтры каталога — уходят в query-строку GET /api/items. */
export interface ItemsQuery {
  category?: Category;
  q?: string;
  locationId?: string;
}

/** Фильтры списка броней. */
export interface BookingsQuery {
  status?: BookingStatus;
  customerId?: string;
  q?: string;
}

/** Ответ GET /api/items/:id/availability — занятые интервалы на горизонте. */
export interface AvailabilityResponse {
  itemId: string;
  busy: DateRange[];
  nextFreeAt: string | null;
}

/** Черновик брони в sessionStorage: товар + выбранный интервал. */
export interface BookingDraft {
  itemId: string;
  sku: string;
  title: string;
  dayRateKop: number;
  hourRateKop: number;
  depositKop: number;
  start: string | null;
  end: string | null;
  savedAt: string;
}

/** Контактные данные из формы оформления. */
export interface CustomerForm {
  fullName: string;
  phone: string;
  email: string;
  comment: string;
}

export interface CreateBookingPayload {
  itemId: string;
  startAt: string;
  endAt: string;
  customer: CustomerForm;
}

export interface ReturnPayload {
  bookingId: string;
  condition: Condition;
  lateHours: number;
  damageNote: string;
}

/** Ответ POST /api/returns — финальные суммы считает сервер. */
export interface ReturnReceipt {
  bookingId: string;
  penaltyKop: number;
  depositRefundKop: number;
  closedAt: string;
}

export interface RevenueReport {
  from: string;
  to: string;
  totalKop: number;
  bookings: number;
  byCategory: { category: Category; totalKop: number }[];
}

/** Строка списка «Мои брони»: бронь + подтянутое название товара. */
export interface BookingRow extends Booking {
  itemTitle?: string;
  itemSku?: string;
}
