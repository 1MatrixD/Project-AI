'use client';

import { useEffect, useState } from 'react';
import type { Promo } from '@/types';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import { formatKop, formatDateTime } from '@/lib/format';

interface FormState {
  code: string;
  kind: 'percent' | 'fixed';
  value: string;
  min_total_rub: string;
  expires_at: string;
}

const EMPTY_FORM: FormState = {
  code: '',
  kind: 'percent',
  value: '10',
  min_total_rub: '1000',
  expires_at: '',
};

/** Админка промокодов: список и создание. */
export default function PromosPage() {
  const [promos, setPromos] = useState<Promo[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    apiGet<Promo[]>('/api/admin/promos')
      .then(setPromos)
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить промокоды'),
      )
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);

    // Порог и фиксированная скидка вводятся в рублях, на бэк уходят в копейках.
    const payload = {
      code: form.code.trim().toUpperCase(),
      percent: form.kind === 'percent' ? Number(form.value) : null,
      discount_kop: form.kind === 'fixed' ? Math.round(Number(form.value) * 100) : null,
      min_total_kop: Math.round(Number(form.min_total_rub) * 100),
      expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
      active: true,
    };

    try {
      await apiPost<Promo>('/api/admin/promos', payload);
      setForm(EMPTY_FORM);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать промокод');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section>
        <h1 className="text-xl font-semibold">Промокоды</h1>
        {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}

        <div className="skh-card mt-3 overflow-x-auto">
          <table className="skh-table w-full min-w-[600px]">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-ink-400">
                {['Код', 'Скидка', 'Мин. сумма', 'Действует до', 'Статус'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-ink-400">Загружаем…</td>
                </tr>
              )}
              {promos.map((p) => (
                <tr key={p.code}>
                  <td className="font-mono text-xs font-semibold">{p.code}</td>
                  <td>{p.percent !== null ? `${p.percent}%` : formatKop(p.discount_kop ?? 0)}</td>
                  <td className="num">{formatKop(p.min_total_kop)}</td>
                  <td>{p.expires_at ? formatDateTime(p.expires_at) : 'бессрочно'}</td>
                  <td className={p.active ? 'text-emerald-700' : 'text-ink-400'}>
                    {p.active ? 'активен' : 'выключен'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <aside>
        <form onSubmit={handleCreate} className="skh-card space-y-3 p-4">
          <h2 className="text-sm font-semibold">Новый промокод</h2>

          <label className="block">
            <span className="skh-label">Код</span>
            <input
              className="skh-input uppercase"
              value={form.code}
              placeholder="SKOROHOD10"
              onChange={(e) => set('code', e.target.value)}
              required
            />
          </label>

          <div className="flex gap-2">
            <select
              className="skh-input w-32"
              aria-label="Тип скидки"
              value={form.kind}
              onChange={(e) => set('kind', e.target.value as FormState['kind'])}
            >
              <option value="percent">Процент</option>
              <option value="fixed">Сумма, ₽</option>
            </select>
            <input
              className="skh-input"
              type="number"
              min={1}
              aria-label="Размер скидки"
              value={form.value}
              onChange={(e) => set('value', e.target.value)}
              required
            />
          </div>

          <label className="block">
            <span className="skh-label">Минимальная сумма заказа, ₽</span>
            <input
              className="skh-input"
              type="number"
              min={0}
              value={form.min_total_rub}
              onChange={(e) => set('min_total_rub', e.target.value)}
            />
          </label>

          <label className="block">
            <span className="skh-label">Действует до</span>
            <input
              className="skh-input"
              type="date"
              value={form.expires_at}
              onChange={(e) => set('expires_at', e.target.value)}
            />
          </label>

          <button type="submit" className="skh-btn-primary w-full" disabled={saving}>
            {saving ? 'Сохраняем…' : 'Создать'}
          </button>
        </form>
      </aside>
    </div>
  );
}
