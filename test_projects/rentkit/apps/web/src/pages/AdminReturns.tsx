import { useMemo, useState } from 'react';
import StatusBadge, { isReturnable } from '../components/StatusBadge';
import { ApiError, api } from '../lib/api';
import { formatDate, formatKop, formatRange, pluralHours } from '../lib/format';
import type { Booking, Condition, Item, ReturnReceipt } from '../types';
import { CONDITION_LABELS } from '../types';

/** Доля залога, которую удерживаем за состояние техники при приёмке. */
const DAMAGE_SHARE: Record<Condition, number> = { new: 0, good: 0, worn: 0.1 };
const CONDITIONS = Object.keys(DAMAGE_SHARE) as Condition[];

function lateHoursOf(booking: Booking): number {
  const due = new Date(booking.endAt).getTime();
  if (!Number.isFinite(due) || Date.now() <= due) return 0;
  return Math.ceil((Date.now() - due) / (60 * 60 * 1000));
}

export default function AdminReturns() {
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Booking[]>([]);
  const [selected, setSelected] = useState<Booking | null>(null);
  const [item, setItem] = useState<Item | null>(null);
  const [condition, setCondition] = useState<Condition>('good');
  const [damageNote, setDamageNote] = useState('');
  const [receipt, setReceipt] = useState<ReturnReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lateHours = selected ? lateHoursOf(selected) : 0;

  /** Предварительная оценка для сотрудника: просрочка по часовому тарифу + удержание за состояние. */
  const penaltyPreviewKop = useMemo(() => {
    if (!selected || !item) return 0;
    return lateHours * item.hourRateKop + Math.round(item.depositKop * DAMAGE_SHARE[condition]);
  }, [condition, item, lateHours, selected]);

  async function search(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setReceipt(null);
    try {
      const rows = await api.bookings.list({ q: query.trim() });
      setFound(rows.filter((row) => isReturnable(row.status)));
      setSelected(null);
      setItem(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Поиск не отработал');
    } finally {
      setBusy(false);
    }
  }

  function pick(booking: Booking): void {
    setSelected(booking);
    setCondition('good');
    setDamageNote('');
    setReceipt(null);
    // тарифы нужны только для предпросмотра штрафа, поэтому ошибку глушим
    api.items.get(booking.itemId).then(setItem, () => setItem(null));
  }

  async function submit(): Promise<void> {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.returns.create({
        bookingId: selected.id,
        condition,
        lateHours,
        damageNote: damageNote.trim(),
      });
      setReceipt(result);
      setFound((prev) => prev.filter((row) => row.id !== selected.id));
      setSelected(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Приёмка не прошла');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="card space-y-4 p-6">
        <h1 className="text-xl font-semibold tracking-tight">Приём возврата</h1>
        <form className="flex gap-2" onSubmit={search}>
          <input className="field" placeholder="Номер брони, телефон или артикул" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className="btn-primary" type="submit" disabled={busy || query.trim().length < 3}>Найти</button>
        </form>

        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <ul className="divide-y divide-slate-100">
          {found.map((booking) => (
            <li key={booking.id}>
              <button className={`flex w-full items-center gap-3 py-3 text-left ${selected?.id === booking.id ? 'bg-brand-50' : ''}`} onClick={() => pick(booking)}>
                <span className="flex-1 font-mono text-sm">{booking.id}</span>
                <span className="text-xs text-slate-500">{formatRange({ start: booking.startAt, end: booking.endAt })}</span>
                <StatusBadge status={booking.status} dense />
              </button>
            </li>
          ))}
          {!busy && found.length === 0 && (
            <li className="py-6 text-center text-sm text-slate-500">Брони на приёмку не найдены. Ищите по номеру из письма клиента.</li>
          )}
        </ul>
      </section>

      <section className="card space-y-4 p-6">
        {receipt && (
          <div className="rounded-lg bg-emerald-50 p-4 text-sm text-emerald-900">
            <p className="font-medium">Возврат принят {formatDate(receipt.closedAt)}</p>
            <p className="mt-1">
              Штраф: {formatKop(receipt.penaltyKop)} · к возврату с залога {formatKop(receipt.depositRefundKop)}
            </p>
          </div>
        )}

        {!selected && !receipt && <p className="py-10 text-center text-sm text-slate-500">Выберите бронь слева, чтобы оформить приёмку</p>}

        {selected && (
          <>
            <div>
              <h2 className="font-semibold">{item?.title ?? selected.itemId}</h2>
              <p className="text-sm text-slate-600">Вернуть до {formatDate(selected.endAt)}</p>
            </div>

            <div>
              <span className="label">Состояние при приёмке</span>
              <div className="flex gap-2">
                {CONDITIONS.map((value) => (
                  <button key={value} className={`chip ${condition === value ? 'chip-active' : ''}`} onClick={() => setCondition(value)}>{CONDITION_LABELS[value]}</button>
                ))}
              </div>
            </div>
            <label className="block">
              <span className="label">Что с техникой</span>
              <textarea className="field min-h-[80px]" value={damageNote} placeholder="Скол на бленде, потерян колпачок" onChange={(e) => setDamageNote(e.target.value)} />
            </label>

            <div className="space-y-1 rounded-lg bg-slate-50 p-3 text-sm">
              <div className="flex justify-between">
                <span>Просрочка</span><span>{lateHours > 0 ? pluralHours(lateHours) : 'нет'}</span>
              </div>
              <div className="flex justify-between font-medium">
                <span>Штраф (предварительно)</span><span className="tabular-nums">{formatKop(penaltyPreviewKop)}</span>
              </div>
              <p className="text-xs text-slate-500">Итоговую сумму пересчитает сервер при сохранении приёмки.</p>
            </div>

            <button className="btn-primary w-full" disabled={busy} onClick={submit}>{busy ? 'Сохраняем…' : 'Принять возврат'}</button>
          </>
        )}
      </section>
    </div>
  );
}
