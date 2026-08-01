/**
 * Расчёт стоимости аренды.
 *
 * Единственный источник правды по деньгам: и API, и веб обязаны звать `quote()`,
 * а не считать сумму у себя. Порядок применения правил важен — сначала база,
 * затем выходная наценка, и только потом скидка за длительный срок.
 */

import type { Customer, DateRange, Item, Quote, QuoteLine } from './types.js';
import { daysOfRange, isWeekend, rentalDays, rentalHours } from './dates.js';
import { depositFor } from './deposit.js';

/** Наценка за каждые сутки, попадающие на субботу или воскресенье, в процентах. */
export const WEEKEND_SURCHARGE_PCT = 20;

/**
 * Скидка за длительный срок аренды, в процентах.
 * Ввели с сентября вместе с корпоративными тарифами — до этого длинные брони
 * считались по обычному дневному тарифу.
 */
export const LONG_TERM_DISCOUNT_PCT = 15;

/** С какого количества суток включается скидка за длительный срок. */
export const LONG_TERM_MIN_DAYS = 7;

export interface QuoteOptions {
  /** Клиент, для которого считаем: влияет на размер депозита. */
  customer?: Customer | null;
  /** Дополнительные строки: доставка, расходники, страховка. */
  extraLines?: QuoteLine[];
}

/** Пустой расчёт — для некорректного или нулевого интервала. */
function emptyQuote(depositKop: number): Quote {
  return {
    hours: 0,
    days: 0,
    baseKop: 0,
    weekendKop: 0,
    longTermDiscountKop: 0,
    depositKop,
    totalKop: 0,
    lines: [],
  };
}

/**
 * Сколько суток аренды попадает на выходные.
 * Считаем по каждому дню отдельно: бронь с пятницы по понедельник даёт два выходных дня.
 */
export function weekendDaysIn(range: DateRange): number {
  return daysOfRange(range).filter((day) => isWeekend(day)).length;
}

/**
 * Полный расчёт стоимости аренды.
 *
 * 1. База — расчётные сутки × дневной тариф.
 * 2. Выходная наценка — +20 % дневного тарифа за каждые выходные сутки.
 * 3. Скидка за длительный срок — −15 % от суммы аренды с наценкой при сроке от 7 суток.
 * 4. Депозит показывается отдельно и в `totalKop` не входит.
 */
export function quote(item: Item, range: DateRange, opts: QuoteOptions = {}): Quote {
  const depositKop = depositFor(item, opts.customer);
  const hours = rentalHours(range);
  if (hours === 0) return emptyQuote(depositKop);

  const days = rentalDays(range);
  const lines: QuoteLine[] = [];

  const baseKop = days * item.dayRateKop;
  lines.push({
    code: 'BASE',
    title: `Аренда, ${days} сут. × ${Math.round(item.dayRateKop / 100)} ₽`,
    amountKop: baseKop,
  });

  const weekendDays = weekendDaysIn(range);
  const weekendKop = Math.round((weekendDays * item.dayRateKop * WEEKEND_SURCHARGE_PCT) / 100);
  if (weekendKop > 0) {
    lines.push({
      code: 'WEEKEND',
      title: `Наценка за выходные, ${weekendDays} дн.`,
      amountKop: weekendKop,
    });
  }

  const subtotalKop = baseKop + weekendKop;
  const longTermDiscountKop =
    days >= LONG_TERM_MIN_DAYS
      ? Math.floor((subtotalKop * LONG_TERM_DISCOUNT_PCT) / 100)
      : 0;
  if (longTermDiscountKop > 0) {
    lines.push({
      code: 'LONG_TERM',
      title: `Скидка за срок от ${LONG_TERM_MIN_DAYS} суток`,
      amountKop: -longTermDiscountKop,
    });
  }

  const extra = opts.extraLines ?? [];
  for (const line of extra) lines.push(line);
  const extraKop = extra.reduce((acc, line) => acc + line.amountKop, 0);

  lines.push({ code: 'DEPOSIT', title: 'Депозит (блокируется на карте)', amountKop: depositKop });

  return {
    hours,
    days,
    baseKop,
    weekendKop,
    longTermDiscountKop,
    depositKop,
    totalKop: subtotalKop - longTermDiscountKop + extraKop,
    lines,
  };
}

/** Короткая сумма без разбивки — для списков и виджетов каталога. */
export function quoteTotalKop(item: Item, range: DateRange, customer?: Customer | null): number {
  return quote(item, range, { customer }).totalKop;
}

/** Форматирование копеек в рубли для писем и SMS: 1234500 → «12 345 ₽». */
export function formatKop(amountKop: number): string {
  const rub = Math.round(amountKop / 100);
  return `${rub.toLocaleString('ru-RU')} ₽`;
}
