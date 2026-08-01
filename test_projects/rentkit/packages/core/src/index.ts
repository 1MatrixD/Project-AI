/**
 * Публичный API пакета `@rentkit/core`.
 *
 * Всё, что импортируют apps/api и apps/web, реэкспортируется отсюда.
 * Точечные импорты вида `@rentkit/core/pricing` не используем — так проще
 * отслеживать, чем именно пользуются приложения.
 */

export type {
  Booking,
  BookingStatus,
  Customer,
  DateRange,
  DomainEvent,
  Item,
  ItemCategory,
  ItemCondition,
  Quote,
  QuoteLine,
  UserRole,
} from './types.js';

export {
  LOCATION_SCHEDULE,
  MS_IN_DAY,
  MS_IN_HOUR,
  addHours,
  businessHoursBetween,
  daysOfRange,
  isWeekend,
  isWorkingDay,
  nextWorkingOpen,
  rentalDays,
  rentalHours,
  toDate,
} from './dates.js';
export type { DaySchedule } from './dates.js';

export {
  LONG_TERM_DISCOUNT_PCT,
  LONG_TERM_MIN_DAYS,
  WEEKEND_SURCHARGE_PCT,
  formatKop,
  quote,
  quoteTotalKop,
  weekendDaysIn,
} from './pricing.js';
export type { QuoteOptions } from './pricing.js';

export {
  BLOCKING_STATUSES,
  bookingRange,
  freeWindows,
  isBlocking,
  isRangeFree,
  mergeBusy,
  nextFreeSlot,
  overlaps,
} from './availability.js';

export {
  CANCEL_GRACE_HOURS,
  MIN_DEPOSIT_KOP,
  MIN_RATING_FOR_DEPOSIT_DISCOUNT,
  VERIFIED_DEPOSIT_DISCOUNT_PCT,
  depositFor,
  isFreeCancel,
  lateCancelFee,
  settleDeposit,
} from './deposit.js';
export type { DepositSettlement } from './deposit.js';

export {
  GRACE_MINUTES,
  LATE_FEE_MULTIPLIER,
  damageFee,
  graceMs,
  lateFeeFor,
  totalChargesKop,
} from './fees.js';
export type { DamageSeverity } from './fees.js';

export {
  MAX_LEAD_DAYS,
  MAX_RENTAL_DAYS,
  MIN_RENTAL_HOURS,
  formatErrors,
  validateBookingPayload,
  validateRange,
} from './validation.js';
export type { BookingPayload, ValidationError } from './validation.js';

/** Версия контракта. Веб сверяет её с `GET /api/health` при старте. */
export const CORE_CONTRACT_VERSION = '1.4.0';
