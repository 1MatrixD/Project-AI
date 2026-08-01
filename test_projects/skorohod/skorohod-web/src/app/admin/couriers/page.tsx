'use client';

import { useEffect, useMemo, useState } from 'react';
import type { CourierReportRow } from '@/types';
import { apiGet, ApiError, qs } from '@/lib/api';
import { formatKop, formatMinutes, toApiDate, pluralizeWithCount } from '@/lib/format';

type SortKey = 'orders_count' | 'delivered_count' | 'earnings_kop' | 'avg_delivery_minutes';

/** Отчёт по курьерам за день: GET /api/admin/reports/couriers?date= */
export default function CouriersReportPage() {
  const [date, setDate] = useState(() => toApiDate(new Date()));
  const [rows, setRows] = useState<CourierReportRow[]>([]);
  const [sort, setSort] = useState<SortKey>('orders_count');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiGet<CourierReportRow[]>(`/api/admin/reports/couriers${qs({ date })}`)
      .then(setRows)
      .catch((e: unknown) => {
        setRows([]);
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить отчёт');
      })
      .finally(() => setLoading(false));
  }, [date]);

  const sorted = useMemo(
    () => [...rows].sort((a, b) => b[sort] - a[sort]),
    [rows, sort],
  );

  const totals = useMemo(
    () =>
      rows.reduce(
        (acc, r) => ({
          orders: acc.orders + r.orders_count,
          delivered: acc.delivered + r.delivered_count,
          cancelled: acc.cancelled + r.cancelled_count,
          earnings: acc.earnings + r.earnings_kop,
        }),
        { orders: 0, delivered: 0, cancelled: 0, earnings: 0 },
      ),
    [rows],
  );

  function shiftDay(days: number) {
    const d = new Date(`${date}T12:00:00`);
    d.setDate(d.getDate() + days);
    setDate(toApiDate(d));
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Курьеры за день</h1>
        <div className="flex items-center gap-2">
          <button type="button" className="skh-btn-ghost" onClick={() => shiftDay(-1)}>
            ←
          </button>
          <input
            type="date"
            className="skh-input w-auto"
            value={date}
            max={toApiDate(new Date())}
            onChange={(e) => setDate(e.target.value)}
          />
          <button type="button" className="skh-btn-ghost" onClick={() => shiftDay(1)}>
            →
          </button>
        </div>
      </header>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="skh-card overflow-x-auto">
        <table className="skh-table w-full min-w-[720px]">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-ink-400">
              <th>Курьер</th>
              {(
                [
                  ['orders_count', 'Заказов'],
                  ['delivered_count', 'Доставлено'],
                  ['avg_delivery_minutes', 'Среднее время'],
                  ['earnings_kop', 'Заработок'],
                ] as Array<[SortKey, string]>
              ).map(([key, title]) => (
                <th key={key} className="cursor-pointer" onClick={() => setSort(key)}>
                  {title}
                  {sort === key && ' ▾'}
                </th>
              ))}
              <th>Отмен</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-sm text-ink-400">
                  Загружаем…
                </td>
              </tr>
            )}
            {!loading && sorted.length === 0 && !error && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-sm text-ink-400">
                  За эту дату данных нет
                </td>
              </tr>
            )}
            {sorted.map((row) => (
              <tr key={row.courier_id} className="hover:bg-brand-50/50">
                <td className="font-medium">{row.name}</td>
                <td className="num">{row.orders_count}</td>
                <td className="num">{row.delivered_count}</td>
                <td className="num">{formatMinutes(row.avg_delivery_minutes)}</td>
                <td className="num">{formatKop(row.earnings_kop)}</td>
                <td className="num">{row.cancelled_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > 0 && (
        <p className="text-sm text-ink-600">
          Всего {pluralizeWithCount(totals.orders, ['заказ', 'заказа', 'заказов'])}:
          доставлено {totals.delivered}, отменено {totals.cancelled}. Выплаты —{' '}
          <span className="font-semibold">{formatKop(totals.earnings)}</span>.
        </p>
      )}
    </div>
  );
}
