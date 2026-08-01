import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import StatusBadge, { isCancellable } from '../components/StatusBadge';
import { ApiError, api } from '../lib/api';
import { formatDate, formatKop, formatRange } from '../lib/format';
import type { BookingRow, BookingStatus } from '../types';
import { STATUS_LABELS } from '../types';

const FILTERS: (BookingStatus | 'all')[] = ['all', 'reserved', 'active', 'overdue', 'returned', 'cancelled'];

export default function MyBookings() {
  const [params] = useSearchParams();
  const highlightId = params.get('highlight');

  const [rows, setRows] = useState<BookingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<BookingStatus | 'all'>('all');
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    // тянем брони и каталог параллельно: в брони приходит только itemId
    Promise.all([api.bookings.list(), api.items.list()])
      .then(([bookings, items]) => {
        if (cancelled) return;
        const byId = new Map(items.map((item) => [item.id, item]));
        setRows(
          bookings.map((booking) => ({
            ...booking,
            itemTitle: byId.get(booking.itemId)?.title,
            itemSku: byId.get(booking.itemId)?.sku,
          })),
        );
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Не удалось загрузить брони');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const visible = useMemo(
    () => (filter === 'all' ? rows : rows.filter((row) => row.status === filter)),
    [filter, rows],
  );

  async function cancel(id: string): Promise<void> {
    if (!window.confirm('Отменить бронь? Технику вернём в свободный пул.')) return;

    setCancellingId(id);
    try {
      const updated = await api.bookings.cancel(id);
      setRows((prev) =>
        prev.map((row) => (row.id === id ? { ...row, status: updated.status } : row)),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Отмена не прошла, попробуйте позже');
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Мои брони</h1>
        <div className="ml-auto flex flex-wrap gap-2">
          {FILTERS.map((value) => (
            <button
              key={value}
              className={`chip ${filter === value ? 'chip-active' : ''}`}
              onClick={() => setFilter(value)}
            >
              {value === 'all' ? 'Все' : STATUS_LABELS[value]}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {loading && (
        <div className="space-y-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="skeleton h-24 w-full" />
          ))}
        </div>
      )}

      {!loading && visible.length === 0 && (
        <div className="card p-8 text-center">
          <p className="text-slate-700">Здесь пока пусто</p>
          <Link to="/" className="btn-primary mt-4">
            Подобрать технику
          </Link>
        </div>
      )}

      <div className="space-y-3">
        {visible.map((row) => (
          <article
            key={row.id}
            className={`card flex flex-wrap items-center gap-4 p-4 ${
              row.id === highlightId ? 'ring-2 ring-brand-400' : ''
            }`}
          >
            <div className="min-w-[220px] flex-1">
              <div className="flex items-center gap-2">
                <h2 className="font-semibold">{row.itemTitle ?? 'Товар удалён из каталога'}</h2>
                <StatusBadge status={row.status} dense />
              </div>
              <p className="mt-1 text-sm text-slate-600">
                {formatRange({ start: row.startAt, end: row.endAt })}
              </p>
              <p className="mt-1 font-mono text-xs text-slate-400">
                {row.itemSku ?? row.itemId} · бронь {row.id}
              </p>
            </div>

            <div className="text-right">
              <div className="text-lg font-semibold tabular-nums">{formatKop(row.quoteKop)}</div>
              <div className="text-xs text-slate-500">
                {row.pickedUpAt ? `выдано ${formatDate(row.pickedUpAt)}` : `создана ${formatDate(row.createdAt)}`}
              </div>
            </div>

            <div className="flex gap-2">
              <Link to={`/items/${row.itemId}`} className="btn-ghost">
                К товару
              </Link>
              {isCancellable(row.status) && (
                <button
                  className="btn-danger"
                  disabled={cancellingId === row.id}
                  onClick={() => cancel(row.id)}
                >
                  {cancellingId === row.id ? 'Отменяем…' : 'Отменить'}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
