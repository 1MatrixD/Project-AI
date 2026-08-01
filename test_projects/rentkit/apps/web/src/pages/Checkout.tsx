import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import PriceBreakdown from '../components/PriceBreakdown';
import { ApiError, api } from '../lib/api';
import { formatKop, formatRange } from '../lib/format';
import { calcQuote, chargeAtPickupKop } from '../lib/price';
import type { CustomerForm } from '../types';
import { clearDraft, draftRange, useDraft } from '../state/cart';

const EMPTY_FORM: CustomerForm = { fullName: '', phone: '', email: '', comment: '' };
const PHONE_RE = /^\+?[0-9\s()-]{10,18}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const CONTACTS_KEY = 'rentkit.customer';

type Errors = Partial<Record<keyof CustomerForm, string>>;

function validate(form: CustomerForm): Errors {
  const errors: Errors = {};
  if (form.fullName.trim().split(/\s+/).length < 2) {
    errors.fullName = 'Укажите фамилию и имя — сверяем с паспортом при выдаче';
  }
  if (!PHONE_RE.test(form.phone.trim())) errors.phone = 'Телефон в формате +7 999 123-45-67';
  if (!EMAIL_RE.test(form.email.trim())) errors.email = 'На эту почту придёт бронь и договор';
  return errors;
}

export default function Checkout() {
  const draft = useDraft();
  const navigate = useNavigate();
  const range = draftRange(draft);

  const [form, setForm] = useState<CustomerForm>(EMPTY_FORM);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  // подставляем контакты из прошлой брони — постоянники не любят печатать их заново
  useEffect(() => {
    try {
      const saved = localStorage.getItem(CONTACTS_KEY);
      if (saved) setForm({ ...EMPTY_FORM, ...(JSON.parse(saved) as Partial<CustomerForm>) });
    } catch {
      localStorage.removeItem(CONTACTS_KEY);
    }
  }, []);

  if (!draft || !range) {
    return (
      <div className="card mx-auto max-w-lg p-8 text-center">
        <h1 className="text-lg font-semibold">Черновик брони пуст</h1>
        <p className="mt-2 text-sm text-slate-600">
          Выберите технику и даты в каталоге — сумма и залог посчитаются автоматически.
        </p>
        <Link to="/" className="btn-primary mt-4">В каталог</Link>
      </div>
    );
  }

  const quote = calcQuote(draft, range);
  const fieldClass = (error?: string) => `field ${error ? 'field-invalid' : ''}`;

  function patch(field: keyof CustomerForm, value: string): void {
    setForm((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  }

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    const found = validate(form);
    setErrors(found);
    if (Object.keys(found).length > 0 || !draft || !range) return;

    setSubmitting(true);
    setApiError(null);
    try {
      const booking = await api.bookings.create({
        itemId: draft.itemId,
        startAt: range.start,
        endAt: range.end,
        customer: { ...form, fullName: form.fullName.trim() },
      });
      localStorage.setItem(CONTACTS_KEY, JSON.stringify(form));
      clearDraft();
      navigate(`/bookings?highlight=${booking.id}`);
    } catch (error) {
      setApiError(error instanceof ApiError ? error.message : 'Не удалось создать бронь');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      <form className="card space-y-4 p-6" onSubmit={submit} noValidate>
        <h1 className="text-xl font-semibold tracking-tight">Оформление брони</h1>

        <label className="block">
          <span className="label">Фамилия и имя</span>
          <input className={fieldClass(errors.fullName)} value={form.fullName} placeholder="Иванов Пётр" onChange={(e) => patch('fullName', e.target.value)} />
          {errors.fullName && <p className="mt-1 text-xs text-red-600">{errors.fullName}</p>}
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="label">Телефон</span>
            <input className={fieldClass(errors.phone)} value={form.phone} inputMode="tel" placeholder="+7 999 123-45-67" onChange={(e) => patch('phone', e.target.value)} />
            {errors.phone && <p className="mt-1 text-xs text-red-600">{errors.phone}</p>}
          </label>
          <label className="block">
            <span className="label">Почта</span>
            <input className={fieldClass(errors.email)} value={form.email} inputMode="email" placeholder="peter@example.com" onChange={(e) => patch('email', e.target.value)} />
            {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email}</p>}
          </label>
        </div>

        <label className="block">
          <span className="label">Комментарий для пункта выдачи</span>
          <textarea className="field min-h-[84px]" value={form.comment} placeholder="Нужен второй аккумулятор, заберу после 19:00" onChange={(e) => patch('comment', e.target.value)} />
        </label>

        {apiError && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{apiError}</p>}

        <button className="btn-primary w-full" type="submit" disabled={submitting}>
          {submitting ? 'Отправляем…' : `Забронировать за ${formatKop(quote.totalKop)}`}
        </button>
        <p className="text-xs text-slate-500">Оплата и залог — при выдаче в пункте проката.</p>
      </form>

      <aside className="card h-fit space-y-4 p-6 lg:sticky lg:top-20">
        <div>
          <h2 className="text-base font-semibold">{draft.title}</h2>
          <p className="font-mono text-xs text-slate-400">{draft.sku}</p>
          <p className="mt-2 text-sm text-slate-600">{formatRange(range)}</p>
        </div>

        <PriceBreakdown item={draft} range={range} />

        <div className="flex justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
          <span className="text-slate-600">Списание при выдаче с залогом</span>
          <span className="font-semibold tabular-nums">{formatKop(chargeAtPickupKop(quote))}</span>
        </div>

        <Link to={`/items/${draft.itemId}`} className="btn-ghost w-full">Изменить даты</Link>
      </aside>
    </div>
  );
}
