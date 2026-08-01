import type { DateRange, Item } from '../types';

/**
 * Локальный расчёт витрины — повторяет правила прайсинга, чтобы не дёргать API
 * на каждый клик по календарю. Считаем в копейках, округляем на каждой строке:
 * так сумма строк всегда сходится с итогом, и в расшифровке нет «потерянной копейки».
 */

/** Наценка за каждые выходные сутки в интервале аренды. */
const WEEKEND_SURCHARGE_RATE = 0.2;

const MS_IN_HOUR = 60 * 60 * 1000;
const HOURS_IN_DAY = 24;

/** Минимум, который тарифицируется, даже если технику взяли на час. */
const MIN_BILLABLE_DAYS = 1;

/** Товар в расчёте: берём только тарифные поля, чтобы считать и по черновику брони. */
export type PricedItem = Pick<Item, 'dayRateKop' | 'hourRateKop' | 'depositKop'>;

/** Строка расшифровки для витрины. */
export interface ShopQuoteLine {
  code: string;
  title: string;
  amountKop: number;
}

/** Вью-модель расчёта: то, что показываем в корзине и на карточке. */
export interface ShopQuote {
  hours: number;
  days: number;
  baseKop: number;
  weekendKop: number;
  depositKop: number;
  totalKop: number;
  lines: ShopQuoteLine[];
}

export function isWeekend(date: Date): boolean {
  const day = date.getDay();
  return day === 0 || day === 6;
}

/** Часы аренды с округлением вверх — неполный час тарифицируется как полный. */
export function billableHours(range: DateRange): number {
  const start = new Date(range.start).getTime();
  const end = new Date(range.end).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return Math.ceil((end - start) / MS_IN_HOUR);
}

/** Сутки аренды: неполные сутки считаются полными. */
export function billableDays(hours: number): number {
  if (hours <= 0) return 0;
  return Math.max(MIN_BILLABLE_DAYS, Math.ceil(hours / HOURS_IN_DAY));
}

/**
 * Сколько суток аренды попадает на субботу/воскресенье.
 * Считаем по дате начала каждых расчётных суток.
 */
export function countWeekendDays(startAt: string, days: number): number {
  const cursor = new Date(startAt);
  if (Number.isNaN(cursor.getTime())) return 0;

  let weekend = 0;
  for (let i = 0; i < days; i += 1) {
    const day = new Date(cursor);
    day.setDate(cursor.getDate() + i);
    if (isWeekend(day)) weekend += 1;
  }
  return weekend;
}

/**
 * Полный расчёт стоимости аренды по выбранному интервалу.
 * Депозит в totalKop не входит — он замораживается на карте отдельно.
 */
export function calcQuote(item: PricedItem, range: DateRange | null): ShopQuote {
  const hours = range ? billableHours(range) : 0;
  const days = billableDays(hours);

  if (!range || days === 0) {
    return {
      hours: 0,
      days: 0,
      baseKop: 0,
      weekendKop: 0,
      depositKop: item.depositKop,
      totalKop: 0,
      lines: [],
    };
  }

  const baseKop = days * item.dayRateKop;
  const weekendDays = countWeekendDays(range.start, days);
  const weekendKop = Math.round(weekendDays * item.dayRateKop * WEEKEND_SURCHARGE_RATE);
  const totalKop = baseKop + weekendKop;

  const lines: ShopQuoteLine[] = [
    { code: 'base', title: `Аренда, ${days} сут. × ${item.dayRateKop / 100} ₽`, amountKop: baseKop },
  ];
  if (weekendKop > 0) {
    lines.push({
      code: 'weekend',
      title: `Выходные дни (${weekendDays}), +20%`,
      amountKop: weekendKop,
    });
  }
  lines.push({ code: 'deposit', title: 'Залог (возвращается)', amountKop: item.depositKop });

  return {
    hours,
    days,
    baseKop,
    weekendKop,
    depositKop: item.depositKop,
    totalKop,
    lines,
  };
}

/** Короткий путь для карточек и корзины, когда нужна только итоговая сумма. */
export function estimateTotalKop(item: PricedItem, range: DateRange | null): number {
  return calcQuote(item, range).totalKop;
}

/** Сумма к списанию при оформлении: аренда + заморозка залога. */
export function chargeAtPickupKop(quote: ShopQuote): number {
  return quote.totalKop + quote.depositKop;
}
