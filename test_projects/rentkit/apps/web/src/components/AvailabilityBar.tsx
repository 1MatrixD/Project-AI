import { useMemo } from 'react';
import type { DateRange } from '../types';

interface Props {
  busy: DateRange[];
  /** Сколько дней показываем вперёд, начиная с сегодня. */
  days?: number;
  from?: Date;
}

interface DayCell {
  date: Date;
  /** Доля занятых часов в сутках: 0 — свободно, 1 — занято целиком. */
  load: number;
  weekend: boolean;
}

const MS_IN_DAY = 24 * 60 * 60 * 1000;
const WEEKDAY_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

function startOfDay(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

/** Пересечение занятых интервалов с каждыми сутками горизонта. */
function buildCells(busy: DateRange[], from: Date, days: number): DayCell[] {
  const cells: DayCell[] = [];
  const origin = startOfDay(from);

  for (let i = 0; i < days; i += 1) {
    const dayStart = new Date(origin.getTime() + i * MS_IN_DAY);
    const dayEnd = new Date(dayStart.getTime() + MS_IN_DAY);
    let busyMs = 0;

    for (const slot of busy) {
      const slotStart = new Date(slot.start).getTime();
      const slotEnd = new Date(slot.end).getTime();
      if (!Number.isFinite(slotStart) || !Number.isFinite(slotEnd)) continue;

      const overlapMs =
        Math.min(slotEnd, dayEnd.getTime()) - Math.max(slotStart, dayStart.getTime());
      if (overlapMs > 0) busyMs += overlapMs;
    }

    cells.push({
      date: dayStart,
      load: Math.min(1, busyMs / MS_IN_DAY),
      weekend: dayStart.getDay() === 0 || dayStart.getDay() === 6,
    });
  }

  return cells;
}

function cellClass(load: number): string {
  if (load === 0) return 'bg-emerald-100 text-emerald-800';
  if (load < 0.5) return 'bg-amber-100 text-amber-800';
  if (load < 0.95) return 'bg-orange-200 text-orange-900';
  return 'bg-red-200 text-red-900';
}

export default function AvailabilityBar({ busy, days = 14, from }: Props) {
  const cells = useMemo(() => buildCells(busy, from ?? new Date(), days), [busy, days, from]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-700">Занятость на {days} дней</h3>
        <div className="flex items-center gap-3 text-[11px] text-slate-500">
          <span className="flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded bg-emerald-200" /> свободно
          </span>
          <span className="flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded bg-amber-200" /> частично
          </span>
          <span className="flex items-center gap-1">
            <i className="h-2.5 w-2.5 rounded bg-red-300" /> занято
          </span>
        </div>
      </div>

      <div className="grid grid-cols-availability gap-1">
        {cells.map((cell) => (
          <div
            key={cell.date.toISOString()}
            title={`${cell.date.toLocaleDateString('ru-RU')} — занято ${Math.round(cell.load * 100)}%`}
            className={`flex flex-col items-center rounded-md py-1.5 text-[11px] leading-tight ${cellClass(cell.load)}`}
          >
            <span className={cell.weekend ? 'font-semibold' : ''}>
              {WEEKDAY_SHORT[cell.date.getDay()]}
            </span>
            <span className="font-medium">{cell.date.getDate()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
