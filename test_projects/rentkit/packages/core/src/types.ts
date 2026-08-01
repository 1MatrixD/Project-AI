/**
 * Доменные типы RentKit.
 *
 * Общий контракт для API и веба. Всё, что связано с деньгами, хранится в копейках
 * (суффикс `*Kop`) и всегда целым числом — никаких float-рублей в домене.
 * Все даты — строки ISO 8601 в UTC, конвертацией в локальное время занимается клиент.
 */

/** Категория товара в каталоге. Используется для фильтров и отчётов. */
export type ItemCategory = 'camera' | 'lens' | 'light' | 'audio' | 'grip';

/** Состояние техники. Влияет на размер депозита и на приёмку возврата. */
export type ItemCondition = 'new' | 'good' | 'worn';

/** Единица проката. Один физический экземпляр, а не модель. */
export interface Item {
  id: string;
  /** Артикул, наклеен на кофр. Уникален в пределах пункта выдачи. */
  sku: string;
  title: string;
  category: ItemCategory;
  /** Базовый тариф за сутки. */
  dayRateKop: number;
  /** Почасовой тариф: продления в день выдачи, внутренние пересчёты. */
  hourRateKop: number;
  /** Базовый депозит до скидок за рейтинг клиента. */
  depositKop: number;
  condition: ItemCondition;
  /** Пункт выдачи, к которому физически привязан экземпляр. */
  locationId: string;
}

/**
 * Жизненный цикл брони:
 * draft → reserved → active → returned
 *                 ↘ cancelled
 *                   active → overdue → returned
 */
export type BookingStatus =
  | 'draft'
  | 'reserved'
  | 'active'
  | 'returned'
  | 'cancelled'
  | 'overdue';

export interface Booking {
  id: string;
  itemId: string;
  customerId: string;
  /** Плановое начало аренды, ISO 8601. */
  startAt: string;
  /** Плановый возврат, ISO 8601. */
  endAt: string;
  status: BookingStatus;
  /** Стоимость аренды на момент подтверждения, без депозита. */
  quoteKop: number;
  /** Идентификатор холда у платёжного провайдера, null — холда нет. */
  depositHoldId: string | null;
  /** Фактическая выдача на руки. */
  pickedUpAt: string | null;
  /** Фактический возврат в пункт выдачи. */
  returnedAt: string | null;
  createdAt: string;
}

export interface Customer {
  id: string;
  name: string;
  phone: string;
  /** Рейтинг 0..5, пересчитывается после каждого возврата. */
  rating: number;
  /** Паспорт проверен сотрудником пункта выдачи. */
  verified: boolean;
}

/** Полуинтервал [start, end): конец не включается. */
export interface DateRange {
  start: string;
  end: string;
}

/** Строка расчёта. Отрицательный `amountKop` — скидка. */
export interface QuoteLine {
  code: string;
  title: string;
  amountKop: number;
}

/**
 * Расчёт стоимости аренды.
 * `totalKop` — сумма к оплате за аренду; депозит в неё не входит и холдируется отдельно.
 */
export interface Quote {
  /** Полная длительность в часах, округление вверх. */
  hours: number;
  /** Расчётное количество суток, минимум 1. */
  days: number;
  baseKop: number;
  weekendKop: number;
  /** Всегда неотрицательное число: величина скидки, а не итог со знаком. */
  longTermDiscountKop: number;
  depositKop: number;
  totalKop: number;
  lines: QuoteLine[];
}

/** Роли в системе: сотрудник пункта выдачи и клиент. */
export type UserRole = 'staff' | 'customer';

/** Событие в журнале брони — то, что пишется в таблицу `events`. */
export interface DomainEvent {
  id: string;
  bookingId: string | null;
  type: string;
  payload: Record<string, unknown>;
  createdAt: string;
}
