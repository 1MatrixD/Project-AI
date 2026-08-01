import type { BookingStatus } from '../types';
import { STATUS_LABELS } from '../types';

interface Props {
  status: BookingStatus;
  /** Компактный вариант для строк таблицы. */
  dense?: boolean;
  title?: string;
}

/** Цвета согласованы с легендой в админке приёмки. */
const STYLES: Record<BookingStatus, string> = {
  draft: 'bg-slate-100 text-slate-600 border-slate-200',
  reserved: 'bg-brand-50 text-brand-700 border-brand-200',
  active: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  returned: 'bg-slate-100 text-slate-500 border-slate-200',
  cancelled: 'bg-slate-50 text-slate-400 border-slate-200 line-through',
  overdue: 'bg-red-50 text-red-700 border-red-200',
};

const DOTS: Record<BookingStatus, string> = {
  draft: 'bg-slate-400',
  reserved: 'bg-brand-500',
  active: 'bg-emerald-500',
  returned: 'bg-slate-400',
  cancelled: 'bg-slate-300',
  overdue: 'bg-red-500',
};

/** Подсказки, чтобы сотрудник в пункте выдачи не гадал, что значит статус. */
const HINTS: Record<BookingStatus, string> = {
  draft: 'Черновик: клиент выбрал даты, но не подтвердил бронь',
  reserved: 'Бронь подтверждена, техника ждёт выдачи',
  active: 'Техника на руках у клиента',
  returned: 'Возврат принят, залог разморожен',
  cancelled: 'Бронь отменена',
  overdue: 'Срок аренды истёк, техника не сдана — начисляется штраф',
};

export default function StatusBadge({ status, dense = false, title }: Props) {
  const size = dense ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${STYLES[status]} ${size}`}
      title={title ?? HINTS[status]}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOTS[status]}`} aria-hidden />
      {STATUS_LABELS[status]}
    </span>
  );
}

/** Статусы, при которых бронь ещё можно отменить со стороны клиента. */
export function isCancellable(status: BookingStatus): boolean {
  return status === 'draft' || status === 'reserved';
}

/** Статусы, которые попадают в очередь приёмки. */
export function isReturnable(status: BookingStatus): boolean {
  return status === 'active' || status === 'overdue';
}
