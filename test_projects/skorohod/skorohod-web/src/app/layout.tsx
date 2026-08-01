import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import Link from 'next/link';
import './globals.css';

const inter = Inter({
  subsets: ['latin', 'cyrillic'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: {
    default: 'Скороход — доставка еды',
    template: '%s · Скороход',
  },
  description: 'Доставка из любимых ресторанов за 30 минут.',
  applicationName: 'Скороход',
};

export const viewport: Viewport = {
  themeColor: '#f97316',
  width: 'device-width',
  initialScale: 1,
};

const NAV = [
  { href: '/', label: 'Рестораны' },
  { href: '/orders', label: 'Мои заказы' },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={inter.variable}>
      <body className="min-h-screen font-sans">
        <header className="sticky top-0 z-20 border-b border-black/5 bg-white/90 backdrop-blur">
          <div className="mx-auto flex h-[var(--header-h)] max-w-6xl items-center gap-6 px-4">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <span
                className="inline-block h-6 w-6 rounded-full bg-brand-500"
                aria-hidden
              />
              Скороход
            </Link>

            <nav className="flex items-center gap-4 text-sm text-ink-600">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href} className="hover:text-brand-600">
                  {item.label}
                </Link>
              ))}
            </nav>

            <div className="ml-auto flex items-center gap-3 text-sm">
              <Link href="/admin/couriers" className="text-ink-400 hover:text-brand-600">
                Админка
              </Link>
              <Link href="/checkout" className="skh-btn-primary">
                Корзина
              </Link>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>

        <footer className="mx-auto max-w-6xl px-4 pb-10 pt-4 text-xs text-ink-400">
          <p>
            Служба поддержки: +7 495 000-00-00 · ежедневно с 9:00 до 23:00 (МСК)
          </p>
          <p className="mt-1">
            ООО «Скороход», {new Date().getFullYear()}. Цены указаны с учётом НДС.
          </p>
        </footer>
      </body>
    </html>
  );
}
