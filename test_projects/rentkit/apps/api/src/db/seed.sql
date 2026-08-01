-- Демо-данные для локального стенда. Накатываются после schema.sql.
-- Идентификаторы фиксированные, чтобы на них можно было ссылаться руками из curl.

INSERT INTO customers (id, name, phone, rating, verified) VALUES
  ('cus-1', 'Игорь Ветров',   '+79101110011', 4.8, true),
  ('cus-2', 'Марина Полева',  '+79101110022', 4.2, true),
  ('cus-3', 'Слава Ким',      '+79101110033', 3.6, false)
ON CONFLICT (id) DO NOTHING;

INSERT INTO items (id, sku, title, category, day_rate_kop, hour_rate_kop, deposit_kop, condition, location_id) VALUES
  ('itm-a7s3',  'CAM-A7S3',   'Sony A7S III, body',              'camera', 450000,  75000, 3000000, 'good', 'loc-msk-1'),
  ('itm-fx3',   'CAM-FX3',    'Sony FX3, body',                  'camera', 620000, 100000, 4500000, 'new',  'loc-msk-1'),
  ('itm-2470',  'LEN-2470GM', 'Sony FE 24-70 f/2.8 GM II',       'lens',   210000,  35000, 1500000, 'good', 'loc-msk-1'),
  ('itm-85',    'LEN-85GM',   'Sony FE 85 f/1.4 GM',             'lens',   180000,  30000, 1200000, 'worn', 'loc-msk-1'),
  ('itm-600d',  'LGT-600D',   'Aputure LS 600d Pro',             'light',  390000,  65000, 2500000, 'good', 'loc-msk-1'),
  ('itm-tube',  'LGT-TUBE',   'Astera Titan Tube, комплект 4 шт','light',  340000,  55000, 2200000, 'good', 'loc-msk-1'),
  ('itm-mixpre','AUD-MIXPRE', 'Sound Devices MixPre-6 II',       'audio',  230000,  40000, 1800000, 'good', 'loc-msk-1'),
  ('itm-boom',  'AUD-BOOM',   'Sennheiser MKH 416 + удочка',     'audio',  150000,  25000,  900000, 'worn', 'loc-msk-1'),
  ('itm-ronin', 'GRP-RONIN',  'DJI Ronin 4D-6',                  'grip',   580000,  95000, 5000000, 'new',  'loc-msk-1'),
  ('itm-slider','GRP-SLIDER', 'Слайдер Rhino 42"',               'grip',    90000,  15000,  400000, 'good', 'loc-msk-1')
ON CONFLICT (id) DO NOTHING;

-- Активная выдача: техника на руках, вернуть должны сегодня вечером.
INSERT INTO bookings (id, item_id, customer_id, start_at, end_at, status, quote_kop, deposit_hold_id, picked_up_at) VALUES
  ('bkg-1', 'itm-fx3', 'cus-1', now() - interval '2 days', now() + interval '6 hours',
   'active', 1240000, 'hold-demo-1', now() - interval '2 days')
ON CONFLICT (id) DO NOTHING;

-- Свежая бронь: техника ещё в пункте, деньги не списаны.
INSERT INTO bookings (id, item_id, customer_id, start_at, end_at, status, quote_kop, deposit_hold_id) VALUES
  ('bkg-2', 'itm-600d', 'cus-2', now() + interval '3 days', now() + interval '5 days',
   'reserved', 780000, 'hold-demo-2')
ON CONFLICT (id) DO NOTHING;

-- Закрытая бронь недельного проката — на ней видно, как считается длинный срок.
INSERT INTO bookings (id, item_id, customer_id, start_at, end_at, status, quote_kop, returned_at) VALUES
  ('bkg-3', 'itm-2470', 'cus-1', now() - interval '20 days', now() - interval '13 days',
   'returned', 1249500, now() - interval '13 days')
ON CONFLICT (id) DO NOTHING;

INSERT INTO payments (booking_id, kind, amount_kop, external_id, status) VALUES
  ('bkg-1', 'hold',    4500000, 'hold-demo-1', 'ok'),
  ('bkg-2', 'hold',    2500000, 'hold-demo-2', 'ok'),
  ('bkg-3', 'hold',    1500000, 'hold-demo-3', 'ok'),
  ('bkg-3', 'release', 1500000, 'hold-demo-3', 'ok')
ON CONFLICT DO NOTHING;

INSERT INTO events (booking_id, type, payload, actor_id) VALUES
  ('bkg-1', 'booking.picked_up', '{"staff":"manager-1"}'::jsonb, 'staff-1'),
  ('bkg-2', 'booking.created',   '{"source":"web"}'::jsonb,      'cus-2'),
  ('bkg-3', 'booking.returned',  '{"condition":"good"}'::jsonb,  'staff-1');
