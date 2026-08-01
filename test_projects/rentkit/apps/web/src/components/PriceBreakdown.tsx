import { useMemo } from 'react';
import { formatKop, formatKopSigned, pluralDays } from '../lib/format';
import { calcQuote } from '../lib/price';
import type { PricedItem } from '../lib/price';
import type { DateRange } from '../types';

interface Props {
  item: PricedItem;
  range: DateRange | null;
  /** На чекауте показываем строку заморозки залога, на карточке товара — нет. */
  showDeposit?: boolean;
  compact?: boolean;
}

const LINE_STYLES: Record<string, string> = {
  base: 'text-slate-700',
  weekend: 'text-amber-700',
  long_term: 'text-emerald-700',
  deposit: 'text-slate-500',
};

export default function PriceBreakdown({ item, range, showDeposit = true, compact = false }: Props) {
  const quote = useMemo(() => calcQuote(item, range), [item, range]);

  if (!range || quote.days === 0) {
    return (
      <div className="rounded-lg bg-slate-50 px-3 py-4 text-center text-sm text-slate-500">
        Выберите даты выдачи и возврата — покажем стоимость
      </div>
    );
  }

  const lines = quote.lines.filter((line) => showDeposit || line.code !== 'deposit');

  return (
    <div className={compact ? 'text-sm' : ''}>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-700">Стоимость аренды</span>
        <span className="text-xs text-slate-400">{pluralDays(quote.days)}</span>
      </div>

      <dl className="divide-y divide-slate-100">
        {lines.map((line) => (
          <div key={line.code} className="price-row">
            <dt className={LINE_STYLES[line.code] ?? 'text-slate-700'}>{line.title}</dt>
            <dd className="whitespace-nowrap font-medium tabular-nums">
              {line.code === 'long_term' ? formatKopSigned(line.amountKop) : formatKop(line.amountKop)}
            </dd>
          </div>
        ))}
      </dl>

      <div className="price-total mt-2">
        <span>К оплате при выдаче</span>
        <span className="tabular-nums">{formatKop(quote.totalKop)}</span>
      </div>

      {showDeposit && (
        <p className="mt-2 text-xs text-slate-500">
          Дополнительно замораживаем залог {formatKop(quote.depositKop)} — возвращаем в течение
          трёх рабочих дней после приёмки техники.
        </p>
      )}

      {quote.weekendKop > 0 && (
        <p className="mt-1 text-xs text-amber-700">
          В интервал попадают выходные — за них действует наценка 20%.
        </p>
      )}
    </div>
  );
}
