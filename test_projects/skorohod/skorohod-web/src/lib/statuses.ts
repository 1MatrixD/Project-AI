import type { OrderStatus } from '@/types';

/**
 * Карта статусов заказа — соответствует enum'у OrderStatus в skorohod-api.
 * Используется таймлайном и списком заказов.
 */

export interface StatusMeta {
  /** Подпись для пользователя. */
  label: string;
  /** Короткое пояснение под подписью на странице трекинга. */
  hint: string;
  /** Тон бейджа: влияет на цвет фона. */
  tone: 'neutral' | 'progress' | 'success' | 'danger';
}

export const STATUS_META: Record<OrderStatus, StatusMeta> = {
  created: {
    label: 'Создан',
    hint: 'Ждём подтверждения оплаты',
    tone: 'neutral',
  },
  paid: {
    label: 'Оплачен',
    hint: 'Передаём заказ в ресторан',
    tone: 'progress',
  },
  cooking: {
    label: 'Готовится',
    hint: 'Ресторан взял заказ в работу',
    tone: 'progress',
  },
  courier_assigned: {
    label: 'Курьер назначен',
    hint: 'Курьер выехал к ресторану',
    tone: 'progress',
  },
  at_restaurant: {
    label: 'Курьер в ресторане',
    hint: 'Ждёт, когда заказ отдадут',
    tone: 'progress',
  },
  picked_up: {
    label: 'Забран курьером',
    hint: 'Заказ у курьера',
    tone: 'progress',
  },
  delivering: {
    label: 'В пути',
    hint: 'Курьер везёт заказ к вам',
    tone: 'progress',
  },
  delivered: {
    label: 'Доставлен',
    hint: 'Приятного аппетита!',
    tone: 'success',
  },
  cancelled: {
    label: 'Отменён',
    hint: 'Заказ отменён',
    tone: 'danger',
  },
  refunded: {
    label: 'Возврат',
    hint: 'Деньги вернутся на карту в течение 3 дней',
    tone: 'danger',
  },
};

/**
 * Порядок шагов «счастливого пути» для таймлайна.
 * Отменённых и возвратов тут нет — они рисуются отдельной плашкой.
 */
export const TIMELINE_STEPS: OrderStatus[] = [
  'created',
  'paid',
  'cooking',
  'courier_assigned',
  'at_restaurant',
  'picked_up',
  'delivering',
  'delivered',
];

const FINAL_STATUSES: ReadonlySet<OrderStatus> = new Set<OrderStatus>([
  'delivered',
  'cancelled',
  'refunded',
]);

/** Заказ больше не изменится: можно закрыть SSE-подписку. */
export function isFinal(status: OrderStatus): boolean {
  return FINAL_STATUSES.has(status);
}

/** Индекс шага в таймлайне; -1 для статусов вне счастливого пути. */
export function stepIndex(status: OrderStatus): number {
  return TIMELINE_STEPS.indexOf(status);
}

/** Отменить можно, пока курьер не забрал заказ. */
export function isCancellable(status: OrderStatus): boolean {
  return ['created', 'paid', 'cooking', 'courier_assigned', 'at_restaurant'].includes(status);
}

export function statusLabel(status: OrderStatus): string {
  return STATUS_META[status]?.label ?? 'Неизвестно';
}

export function toneClass(tone: StatusMeta['tone']): string {
  switch (tone) {
    case 'success':
      return 'bg-emerald-100 text-emerald-800';
    case 'danger':
      return 'bg-rose-100 text-rose-800';
    case 'progress':
      return 'bg-brand-100 text-brand-700';
    default:
      return 'bg-black/5 text-ink-600';
  }
}
