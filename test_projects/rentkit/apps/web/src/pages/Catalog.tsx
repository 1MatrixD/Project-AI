import { useEffect, useMemo, useState } from 'react';
import ItemCard, { ItemCardSkeleton } from '../components/ItemCard';
import { ApiError, api } from '../lib/api';
import type { Category, Item } from '../types';
import { CATEGORIES, CATEGORY_LABELS } from '../types';

type Filter = Category | 'all';
type LoadState = 'loading' | 'ready' | 'error';

const DEBOUNCE_MS = 250;
const DEFAULT_LOCATION = import.meta.env.VITE_DEFAULT_LOCATION_ID || undefined;

export default function Catalog() {
  const [items, setItems] = useState<Item[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  // поиск не дёргает API на каждую букву
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    setState('loading');

    api.items
      .list({
        ...(category === 'all' ? {} : { category }),
        ...(debounced ? { q: debounced } : {}),
        ...(DEFAULT_LOCATION ? { locationId: DEFAULT_LOCATION } : {}),
      })
      .then((rows) => {
        if (cancelled) return;
        setItems(rows);
        setState('ready');
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Не удалось загрузить каталог');
        setState('error');
      });

    return () => {
      cancelled = true;
    };
  }, [category, debounced, reloadKey]);

  // сервер уже отфильтровал, но при быстром вводе показываем актуальную выборку сразу
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(needle) || item.sku.toLowerCase().includes(needle),
    );
  }, [items, query]);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Каталог техники</h1>
        <span className="text-sm text-slate-500">
          {state === 'ready' ? `${visible.length} позиций` : 'загружаем…'}
        </span>
        <input
          type="search"
          className="field ml-auto max-w-xs"
          placeholder="Поиск по названию или артикулу"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        <button
          className={`chip ${category === 'all' ? 'chip-active' : ''}`}
          onClick={() => setCategory('all')}
        >
          Всё
        </button>
        {CATEGORIES.map((value) => (
          <button
            key={value}
            className={`chip ${category === value ? 'chip-active' : ''}`}
            onClick={() => setCategory(value)}
          >
            {CATEGORY_LABELS[value]}
          </button>
        ))}
      </div>

      {state === 'error' && (
        <div className="card p-6">
          <p className="text-sm text-red-700">{error}</p>
          <button className="btn-ghost mt-3" onClick={() => setReloadKey((n) => n + 1)}>
            Повторить
          </button>
        </div>
      )}

      {state === 'loading' && (
        <div className="grid grid-cols-catalog gap-4">
          {Array.from({ length: 8 }, (_, index) => (
            <ItemCardSkeleton key={index} />
          ))}
        </div>
      )}

      {state === 'ready' && visible.length === 0 && (
        <div className="card p-8 text-center">
          <p className="text-slate-700">По запросу ничего не нашлось</p>
          <p className="mt-1 text-sm text-slate-500">
            Попробуйте другую категорию или напишите менеджеру — часть техники выдаём под заказ.
          </p>
        </div>
      )}

      {state === 'ready' && visible.length > 0 && (
        // TODO: пагинация — сейчас тянем весь список одним запросом, при 500+ позициях будет тяжело
        <div className="grid grid-cols-catalog gap-4">
          {visible.map((item) => (
            <ItemCard key={item.id} item={item} highlight={query} />
          ))}
        </div>
      )}
    </div>
  );
}
