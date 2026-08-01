import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import AdminReturns from './pages/AdminReturns';
import Catalog from './pages/Catalog';
import Checkout from './pages/Checkout';
import ItemPage from './pages/ItemPage';
import MyBookings from './pages/MyBookings';
import { useDraft } from './state/cart';

const NAV = [
  { to: '/', label: 'Каталог', end: true },
  { to: '/bookings', label: 'Мои брони', end: false },
  { to: '/admin/returns', label: 'Приём возврата', end: false },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    'rounded-lg px-3 py-2 text-sm font-medium transition-colors',
    isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-100',
  ].join(' ');
}

export default function App() {
  const draft = useDraft();
  const hasDraft = Boolean(draft?.start && draft.end);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 font-bold text-white">
              R
            </span>
            <span className="text-lg font-semibold tracking-tight">RentKit</span>
          </NavLink>

          <nav className="ml-2 flex items-center gap-1">
            {NAV.map((link) => (
              <NavLink key={link.to} to={link.to} end={link.end} className={navClass}>
                {link.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto">
            {hasDraft ? (
              <NavLink to="/checkout" className="btn-primary">
                Оформить бронь
                <span className="ml-1 h-2 w-2 rounded-full bg-accent-400" aria-hidden />
              </NavLink>
            ) : (
              <span className="text-sm text-slate-400">Выберите технику и даты</span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Routes>
          <Route path="/" element={<Catalog />} />
          <Route path="/items/:id" element={<ItemPage />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/bookings" element={<MyBookings />} />
          <Route path="/admin/returns" element={<AdminReturns />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-4 text-xs text-slate-500">
          <span>RentKit · прокат фото и видео техники</span>
          <span>Самовывоз: Москва, Дербеневская 20, с 10:00 до 22:00</span>
          <span className="ml-auto font-mono">
            api: {import.meta.env.VITE_API_URL ?? 'http://localhost:8030'}
          </span>
        </div>
      </footer>
    </div>
  );
}
