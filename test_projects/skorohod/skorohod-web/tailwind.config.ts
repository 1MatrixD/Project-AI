import type { Config } from 'tailwindcss';

// Фирменные цвета «Скорохода» согласованы с дизайном в Figma (файл SKH-UI v4).
const config: Config = {
  content: [
    './src/app/**/*.{ts,tsx}',
    './src/components/**/*.{ts,tsx}',
    './src/lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#fff5ed',
          100: '#ffe8d4',
          300: '#ffb066',
          500: '#f97316',
          600: '#e25c05',
          700: '#b84703',
        },
        ink: {
          400: '#8b8f98',
          600: '#4a4f59',
          900: '#16181d',
        },
        surface: '#fbfbfc',
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        card: '14px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(22, 24, 29, 0.06), 0 8px 24px rgba(22, 24, 29, 0.05)',
      },
      keyframes: {
        pulseDot: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.45', transform: 'scale(0.85)' },
        },
      },
      animation: {
        'pulse-dot': 'pulseDot 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};

export default config;
