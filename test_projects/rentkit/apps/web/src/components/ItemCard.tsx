import { Link } from 'react-router-dom';
import { formatKop } from '../lib/format';
import type { Item } from '../types';
import { CATEGORY_LABELS, CONDITION_LABELS } from '../types';

interface Props {
  item: Item;
  /** Подсветка совпадения в поиске — подставляем подстроку запроса. */
  highlight?: string;
}

const CONDITION_STYLES: Record<Item['condition'], string> = {
  new: 'bg-emerald-50 text-emerald-700',
  good: 'bg-slate-100 text-slate-600',
  worn: 'bg-amber-50 text-amber-700',
};

const CATEGORY_EMOJI: Record<Item['category'], string> = {
  camera: '🎥',
  lens: '🔎',
  light: '💡',
  audio: '🎙',
  grip: '🧰',
};

function highlightTitle(title: string, query?: string) {
  const needle = query?.trim();
  if (!needle || needle.length < 2) return title;

  const index = title.toLowerCase().indexOf(needle.toLowerCase());
  if (index < 0) return title;

  return (
    <>
      {title.slice(0, index)}
      <mark className="rounded bg-accent-400/40 px-0.5">{title.slice(index, index + needle.length)}</mark>
      {title.slice(index + needle.length)}
    </>
  );
}

export default function ItemCard({ item, highlight }: Props) {
  return (
    <Link
      to={`/items/${item.id}`}
      className="card group flex flex-col p-4 transition-shadow hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-brand-300"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
          {CATEGORY_EMOJI[item.category]} {CATEGORY_LABELS[item.category]}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] ${CONDITION_STYLES[item.condition]}`}>
          {CONDITION_LABELS[item.condition]}
        </span>
      </div>

      <h3 className="mt-2 text-base font-semibold leading-snug text-slate-900 group-hover:text-brand-700">
        {highlightTitle(item.title, highlight)}
      </h3>
      <p className="mt-1 font-mono text-xs text-slate-400">{item.sku}</p>

      <div className="mt-auto pt-4">
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-semibold text-slate-900">{formatKop(item.dayRateKop)}</span>
          <span className="text-sm text-slate-500">/ сутки</span>
        </div>
        <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
          <span>час — {formatKop(item.hourRateKop)}</span>
          <span>залог {formatKop(item.depositKop)}</span>
        </div>
      </div>

      <span className="mt-3 text-sm font-medium text-brand-600 group-hover:underline">
        Выбрать даты →
      </span>
    </Link>
  );
}

/** Скелетон на время загрузки каталога — размеры совпадают с карточкой. */
export function ItemCardSkeleton() {
  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="skeleton h-3 w-24" />
      <div className="skeleton h-5 w-full" />
      <div className="skeleton h-3 w-20" />
      <div className="skeleton mt-6 h-6 w-32" />
      <div className="skeleton h-3 w-full" />
    </div>
  );
}
