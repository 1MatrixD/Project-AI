/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Картинки ресторанов и блюд лежат в S3-совместимом хранилище,
  // домен подставляется на деплое через переменную окружения.
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: process.env.NEXT_PUBLIC_CDN_HOST || 'cdn.skorohod.local',
        pathname: '/menu/**',
      },
    ],
  },

  // Проксируем /api на бэкенд в dev-режиме, чтобы не ловить CORS
  // на локальной машине. В проде фронт и API за одним nginx.
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8020';
    if (process.env.NODE_ENV !== 'development') {
      return [];
    }
    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },

  eslint: {
    dirs: ['src'],
  },

  // SSE-стрим заказа не должен буферизоваться прокси Next.
  async headers() {
    return [
      {
        source: '/api/v2/orders/:id/stream',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, no-transform' },
          { key: 'X-Accel-Buffering', value: 'no' },
        ],
      },
    ];
  },
};

export default nextConfig;
