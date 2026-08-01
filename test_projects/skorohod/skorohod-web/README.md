# Скороход · веб

Веб-клиент сервиса доставки еды «Скороход». Витрина ресторанов, корзина, чекаут,
трекинг заказа в реальном времени и админ-раздел (отчёт по курьерам, промокоды).

Бэкенд живёт в отдельном репозитории `skorohod-api` (FastAPI). Фронт ходит на него
по HTTP, базовый адрес берётся из `NEXT_PUBLIC_API_URL`.

## Стек

- Next.js 15 (App Router, RSC там, где это оправдано)
- React 19
- TypeScript 5.7 (strict)
- Tailwind CSS 3.4 + clsx
- SSE для трекинга заказа (`EventSource`, свой хук с реконнектом)

## Запуск

```bash
cp .env.example .env.local
npm install
npm run dev -- -p 3020
```

Открыть http://localhost:3020. Бэкенд должен быть поднят на 8020
(`cd ../skorohod-api && make dev`), иначе витрина отдаст пустой список ресторанов.

Прочие команды:

```bash
npm run build      # прод-сборка
npm run lint       # eslint по src/
npm run typecheck  # tsc --noEmit
```

## Переменные окружения

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | базовый URL API | `http://localhost:8020` |
| `NEXT_PUBLIC_CDN_HOST` | хост картинок меню | `cdn.skorohod.local` |
| `NEXT_PUBLIC_DEFAULT_CITY` | город витрины | `msk` |
| `NEXT_PUBLIC_DEBUG_STREAM` | лог SSE в консоль | `0` |

Секретов во фронте нет: токен пользователя выдаёт API и мы храним его в
`localStorage` под ключом `skh_token`.

## Деньги

Все суммы от API приходят в **копейках** (`subtotal_kop`, `delivery_kop`,
`discount_kop`, `total_kop`) и являются целыми числами. Форматирование —
только через `formatKop()` из `src/lib/format.ts`, руками делить на 100 нельзя.

## Статусы заказа

Единственный источник правды по статусам — `src/lib/statuses.ts`. Там лежит
полная карта из десяти статусов бэкенда, порядок шагов для таймлайна и хелпер
`isFinal(status)`. Если бэкенд добавляет новый статус, правим **только** этот
файл — остальной интерфейс подхватывает изменения автоматически.

Порядок «нормального» заказа:

```
created → paid → cooking → courier_assigned → at_restaurant
        → picked_up → delivering → delivered
```

Терминальные: `delivered`, `cancelled`, `refunded`.

## Структура

```
src/
  app/         маршруты App Router (витрина, чекаут, заказы, админка)
  components/  презентационные компоненты
  lib/         api-клиент, домен (статусы, цены, корзина), хуки, форматтеры
  types.ts     типы контракта с API
```

## Договорённости команды

- Компоненты — `PascalCase.tsx`, хуки и утилиты — `camelCase.ts`.
- Никаких прямых `fetch` в компонентах: только `apiGet`/`apiPost` из `lib/api.ts`.
- Комментарии пишем по-русски, кратко и по делу.
