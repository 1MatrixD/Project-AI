import type { Config } from 'tailwindcss';

/**
 * Палитра витрины: тёмно-синий как основной, янтарный — акцент под кнопки брони.
 * Цвета статусов брони держим здесь, чтобы StatusBadge и AvailabilityBar не расходились.
 */
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef4ff',
          100: '#d9e6ff',
          200: '#b6ceff',
          300: '#84acff',
          400: '#4a80ff',
          500: '#2158f5',
          600: '#1440d1',
          700: '#1233a6',
          800: '#132d84',
          900: '#152a6b',
        },
        accent: {
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
        },
        busy: '#f87171',
        free: '#34d399',
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      borderRadius: {
        card: '14px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.06), 0 8px 24px -12px rgba(15, 23, 42, 0.25)',
      },
      gridTemplateColumns: {
        catalog: 'repeat(auto-fill, minmax(248px, 1fr))',
        availability: 'repeat(14, minmax(0, 1fr))',
      },
      keyframes: {
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.45' },
        },
      },
      animation: {
        'pulse-soft': 'pulseSoft 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};

export default config;
