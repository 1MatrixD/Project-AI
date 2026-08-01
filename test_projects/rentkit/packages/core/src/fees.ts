/**
 * Штрафы: просрочка возврата и повреждения техники.
 *
 * Суммы удерживаются из депозита при приёмке. Если удержание больше холда — остаток
 * выставляется клиенту счётом, но это уже вне зоны ответственности core.
 */

import type { Item } from './types.js';

/**
 * Льготный период после планового возврата.
 * Клиент может опоздать на два часа — пробки у пункта выдачи обычное дело,
 * штраф за это не берём.
 */
export const GRACE_MINUTES = 120;

/** Коэффициент штрафа: сутки просрочки стоят полтора дневных тарифа. */
export const LATE_FEE_MULTIPLIER = 1.5;

/** Тяжесть повреждения, выставляется приёмщиком при возврате. */
export type DamageSeverity = 'scratch' | 'minor' | 'major' | 'total';

/** Доля от депозита, которая удерживается за повреждение. */
const DAMAGE_SHARE: Record<DamageSeverity, number> = {
  scratch: 0.05,
  minor: 0.2,
  major: 0.6,
  total: 1,
};

/** Изношенная техника дешевле в ремонте — за царапины с неё спрашиваем мягче. */
const CONDITION_FACTOR: Record<Item['condition'], number> = {
  new: 1,
  good: 0.9,
  worn: 0.7,
};

/**
 * Штраф за просрочку возврата.
 *
 * Считается по полным суткам просрочки, уже очищенным от льготного периода и
 * нерабочих часов пункта выдачи: подсчёт `daysLate` — задача вызывающего кода.
 * Итог ограничен сверху суммой депозита по товару.
 */
export function lateFeeFor(daysLate: number, item: Item): number {
  if (!Number.isFinite(daysLate) || daysLate <= 0) return 0;
  const days = Math.ceil(daysLate);
  const raw = Math.round(days * item.dayRateKop * LATE_FEE_MULTIPLIER);
  return Math.min(raw, item.depositKop);
}

/**
 * Стоимость повреждения: доля депозита по шкале тяжести с поправкой на износ.
 * Полная утрата (`total`) поправкой на износ не смягчается — комплект нужно
 * закупать заново по рыночной цене.
 */
export function damageFee(item: Item, severity: DamageSeverity): number {
  const share = DAMAGE_SHARE[severity];
  if (!share) return 0;
  if (severity === 'total') return item.depositKop;

  const factor = CONDITION_FACTOR[item.condition] ?? 1;
  return Math.round(item.depositKop * share * factor);
}

/** Перевод льготного периода в миллисекунды — удобно для сравнения дат. */
export function graceMs(): number {
  return GRACE_MINUTES * 60 * 1000;
}

/**
 * Суммарное удержание при приёмке возврата: просрочка плюс повреждения,
 * но не больше заблокированного депозита.
 */
export function totalChargesKop(lateKop: number, damageKop: number, depositKop: number): number {
  const sum = Math.max(0, Math.round(lateKop)) + Math.max(0, Math.round(damageKop));
  return Math.min(sum, Math.max(0, Math.round(depositKop)));
}
