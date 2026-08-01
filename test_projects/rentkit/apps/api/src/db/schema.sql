-- Схема RentKit.
-- Накатывается через `npm run db:schema`. Миграций пока нет: база небольшая,
-- изменения вносим руками через ALTER и дописываем сюда.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Пункты выдачи. Сейчас он один, но привязку по locationId заложили сразу.
CREATE TABLE IF NOT EXISTS locations (
  id          TEXT PRIMARY KEY,
  title       TEXT        NOT NULL,
  address     TEXT        NOT NULL,
  timezone    TEXT        NOT NULL DEFAULT 'Europe/Moscow',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Экземпляры техники. Одна строка — один физический комплект, не модель.
CREATE TABLE IF NOT EXISTS items (
  id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  sku           TEXT        NOT NULL,
  title         TEXT        NOT NULL,
  category      TEXT        NOT NULL
                CHECK (category IN ('camera', 'lens', 'light', 'audio', 'grip')),
  day_rate_kop  INTEGER     NOT NULL CHECK (day_rate_kop >= 0),
  hour_rate_kop INTEGER     NOT NULL CHECK (hour_rate_kop >= 0),
  deposit_kop   INTEGER     NOT NULL CHECK (deposit_kop >= 0),
  condition     TEXT        NOT NULL CHECK (condition IN ('new', 'good', 'worn')),
  location_id   TEXT        NOT NULL REFERENCES locations (id),
  archived      BOOLEAN     NOT NULL DEFAULT false,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS items_sku_location_uq ON items (location_id, sku);
CREATE INDEX IF NOT EXISTS items_category_idx ON items (category) WHERE archived = false;

CREATE TABLE IF NOT EXISTS customers (
  id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  name        TEXT        NOT NULL,
  phone       TEXT        NOT NULL UNIQUE,
  rating      NUMERIC(2,1) NOT NULL DEFAULT 5.0 CHECK (rating >= 0 AND rating <= 5),
  verified    BOOLEAN     NOT NULL DEFAULT false,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Брони. Интервал полуоткрытый: [start_at, end_at).
CREATE TABLE IF NOT EXISTS bookings (
  id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  item_id          TEXT        NOT NULL REFERENCES items (id),
  customer_id      TEXT        NOT NULL REFERENCES customers (id),
  start_at         TIMESTAMPTZ NOT NULL,
  end_at           TIMESTAMPTZ NOT NULL,
  status           TEXT        NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'reserved', 'active', 'returned', 'cancelled', 'overdue')),
  quote_kop        INTEGER     NOT NULL DEFAULT 0,
  deposit_hold_id  TEXT,
  picked_up_at     TIMESTAMPTZ,
  returned_at      TIMESTAMPTZ,
  comment          TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bookings_range_ck CHECK (end_at > start_at)
);

CREATE INDEX IF NOT EXISTS bookings_item_idx     ON bookings (item_id, start_at);
CREATE INDEX IF NOT EXISTS bookings_customer_idx ON bookings (customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS bookings_status_idx   ON bookings (status);

-- Операции с деньгами: холды депозита, удержания, возвраты.
CREATE TABLE IF NOT EXISTS payments (
  id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  booking_id  TEXT        NOT NULL REFERENCES bookings (id),
  kind        TEXT        NOT NULL CHECK (kind IN ('hold', 'release', 'capture', 'refund')),
  amount_kop  INTEGER     NOT NULL,
  -- Идентификатор операции на стороне платёжного провайдера.
  external_id TEXT,
  status      TEXT        NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'pending', 'failed')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS payments_booking_idx ON payments (booking_id, created_at DESC);
CREATE INDEX IF NOT EXISTS payments_hold_idx    ON payments (external_id) WHERE kind = 'hold';

-- Журнал событий. Пишем всё, что меняет состояние брони: нужен для разборов с клиентами.
CREATE TABLE IF NOT EXISTS events (
  id          BIGSERIAL PRIMARY KEY,
  booking_id  TEXT REFERENCES bookings (id),
  type        TEXT        NOT NULL,
  payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
  actor_id    TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS events_booking_idx ON events (booking_id, created_at DESC);
CREATE INDEX IF NOT EXISTS events_type_idx    ON events (type, created_at DESC);

-- Стартовые данные для локальной разработки.
INSERT INTO locations (id, title, address)
VALUES ('loc-msk-1', 'Пункт выдачи на Бауманской', 'Москва, ул. Бауманская, 11')
ON CONFLICT (id) DO NOTHING;
