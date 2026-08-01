import { useMemo } from 'react';
import { formatDate, fromInputValue, toInputValue } from '../lib/format';
import { billableDays, billableHours } from '../lib/price';
import type { DateRange } from '../types';

interface Props {
  value: DateRange | null;
  onChange: (range: DateRange | null) => void;
  /** Занятые интервалы с сервера — по ним подсвечиваем конфликт. */
  busy?: DateRange[];
  minHours?: number;
  maxDays?: number;
  disabled?: boolean;
}

/** Пересечение двух интервалов: касание границами конфликтом не считаем. */
export function overlaps(a: DateRange, b: DateRange): boolean {
  const aStart = new Date(a.start).getTime();
  const aEnd = new Date(a.end).getTime();
  const bStart = new Date(b.start).getTime();
  const bEnd = new Date(b.end).getTime();
  return aStart < bEnd && bStart < aEnd;
}

const DEFAULT_MIN_HOURS = 4;
const DEFAULT_MAX_DAYS = 30;

export default function DateRangePicker({
  value,
  onChange,
  busy = [],
  minHours = DEFAULT_MIN_HOURS,
  maxDays = DEFAULT_MAX_DAYS,
  disabled = false,
}: Props) {
  const conflicts = useMemo(
    () => (value ? busy.filter((slot) => overlaps(slot, value)) : []),
    [busy, value],
  );

  const hours = value ? billableHours(value) : 0;
  const days = billableDays(hours);

  const error = useMemo(() => {
    if (!value) return null;
    if (hours <= 0) return 'Дата возврата должна быть позже даты выдачи';
    if (hours < minHours) return `Минимальный срок аренды — ${minHours} часа`;
    if (days > maxDays) return `Максимальный срок онлайн-брони — ${maxDays} суток, дальше через менеджера`;
    if (new Date(value.start).getTime() < Date.now() - 60 * 60 * 1000) {
      return 'Начало аренды в прошлом — выберите ближайшее время';
    }
    if (conflicts.length > 0) return 'В этот интервал техника уже забронирована';
    return null;
  }, [conflicts.length, days, hours, maxDays, minHours, value]);

  function patch(part: 'start' | 'end', raw: string): void {
    const iso = fromInputValue(raw);
    const next: DateRange = {
      start: part === 'start' ? iso ?? '' : value?.start ?? '',
      end: part === 'end' ? iso ?? '' : value?.end ?? '',
    };
    onChange(next.start && next.end ? next : null);
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="label">Выдача</span>
          <input
            type="datetime-local"
            className={`field ${error && hours <= 0 ? 'field-invalid' : ''}`}
            value={toInputValue(value?.start ?? null)}
            onChange={(event) => patch('start', event.target.value)}
            disabled={disabled}
            step={3600}
          />
        </label>
        <label className="block">
          <span className="label">Возврат</span>
          <input
            type="datetime-local"
            className={`field ${error ? 'field-invalid' : ''}`}
            value={toInputValue(value?.end ?? null)}
            onChange={(event) => patch('end', event.target.value)}
            disabled={disabled}
            step={3600}
          />
        </label>
      </div>

      {value && !error && (
        <p className="text-sm text-slate-600">
          Срок аренды: <b>{days} сут.</b> ({hours} ч), возврат до {formatDate(value.end)}
        </p>
      )}

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}

      {conflicts.length > 0 && (
        <ul className="space-y-1 text-xs text-slate-500">
          {conflicts.slice(0, 3).map((slot) => (
            <li key={`${slot.start}-${slot.end}`}>
              Занято: {formatDate(slot.start)} — {formatDate(slot.end)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
