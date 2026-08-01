import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import AvailabilityBar from '../components/AvailabilityBar';
import DateRangePicker, { overlaps } from '../components/DateRangePicker';
import PriceBreakdown from '../components/PriceBreakdown';
import { ApiError, api } from '../lib/api';
import { formatKop } from '../lib/format';
import type { DateRange, Item } from '../types';
import { CATEGORY_LABELS, CONDITION_LABELS } from '../types';
import { draftRange, getDraft, setDraftItem } from '../state/cart';

const AVAILABILITY_DAYS = Number(import.meta.env.VITE_AVAILABILITY_DAYS ?? 14);

export default function ItemPage() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [item, setItem] = useState<Item | null>(null);
  const [busy, setBusy] = useState<DateRange[]>([]);
  const [nextFreeAt, setNextFreeAt] = useState<string | null>(null);
  const [range, setRange] = useState<DateRange | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    Promise.all([api.items.get(id), api.items.availability(id, AVAILABILITY_DAYS)])
      .then(([loadedItem, availability]) => {
        if (cancelled) return;
        setItem(loadedItem);
        setBusy(availability.busy);
        setNextFreeAt(availability.nextFreeAt);
        setError(null);

        // если пользователь пришёл с чекаута назад — восстанавливаем его даты
        const draft = getDraft();
        if (draft?.itemId === loadedItem.id) setRange(draftRange(draft));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Не удалось загрузить товар');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const conflict = useMemo(
    () => (range ? busy.some((slot) => overlaps(slot, range)) : false),
    [busy, range],
  );

  const canBook = Boolean(item && range && !conflict);

  function handleBook(): void {
    if (!item || !range) return;
    setDraftItem(item, range);
    navigate('/checkout');
  }

  if (loading) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="card space-y-3 p-6">
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-7 w-2/3" />
          <div className="skeleton h-24 w-full" />
        </div>
        <div className="skeleton h-64 w-full" />
      </div>
    );
  }

  if (error || !item) {
    return (
      <div className="card p-8 text-center">
        <p className="text-slate-800">{error ?? 'Товар не найден'}</p>
        <Link to="/" className="btn-ghost mt-4">
          Вернуться в каталог
        </Link>
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <div className="space-y-6">
        <div className="card p-6">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            {CATEGORY_LABELS[item.category]} · {item.sku}
          </span>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{item.title}</h1>

          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-slate-500">Сутки</dt>
              <dd className="text-base font-semibold">{formatKop(item.dayRateKop)}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Час</dt>
              <dd className="text-base font-semibold">{formatKop(item.hourRateKop)}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Залог</dt>
              <dd className="text-base font-semibold">{formatKop(item.depositKop)}</dd>
            </div>
          </dl>

          <p className="mt-4 text-sm text-slate-600">
            Состояние: {CONDITION_LABELS[item.condition]}. Выдача в пункте {item.locationId}.
            В комплекте — кофр, аккумулятор и зарядное устройство.
          </p>
        </div>

        <div className="card p-6">
          <AvailabilityBar busy={busy} days={AVAILABILITY_DAYS} />
          {nextFreeAt && busy.length > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              Ближайшее свободное окно начинается {new Date(nextFreeAt).toLocaleString('ru-RU')}
            </p>
          )}
        </div>
      </div>

      <aside className="card h-fit space-y-4 p-6 lg:sticky lg:top-20">
        <h2 className="text-lg font-semibold">Аренда</h2>
        <DateRangePicker value={range} onChange={setRange} busy={busy} />
        <PriceBreakdown item={item} range={conflict ? null : range} />
        <button className="btn-primary w-full" disabled={!canBook} onClick={handleBook}>
          Забронировать
        </button>
        <p className="text-xs text-slate-500">
          Бронь держим 2 часа без предоплаты. Отменить можно бесплатно до момента выдачи.
        </p>
      </aside>
    </div>
  );
}
