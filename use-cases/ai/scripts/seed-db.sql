-- Schema (idempotent)
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer TEXT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed data (only if tables are empty)
INSERT INTO orders (id, customer, amount, status, created_at)
SELECT *
FROM (VALUES
    (1,  'Alice',   99.99::numeric, 'completed', '2026-02-23 14:00:00-05'::timestamptz),
    (2,  'Bob',     49.99,          'completed', '2026-02-23 14:10:00-05'),
    (3,  'Carol',  149.99,          'completed', '2026-02-23 14:15:00-05'),
    (4,  'Dave',    29.99,          'completed', '2026-02-23 14:20:00-05'),
    (5,  'Eve',     89.99,          'completed', '2026-02-23 14:25:00-05'),
    (6,  'Frank',   59.99,          'failed',    '2026-02-23 14:35:00-05'),
    (7,  'Grace',  119.99,          'failed',    '2026-02-23 14:36:00-05'),
    (8,  'Heidi',   39.99,          'failed',    '2026-02-23 14:37:00-05'),
    (9,  'Ivan',   199.99,          'failed',    '2026-02-23 14:38:00-05'),
    (10, 'Judy',    74.99,          'failed',    '2026-02-23 14:39:00-05')
) AS seed(id, customer, amount, status, created_at)
WHERE NOT EXISTS (SELECT 1 FROM orders);

INSERT INTO payments (id, order_id, status, error_message, created_at)
SELECT *
FROM (VALUES
    (1,  1,  'success', NULL::text,        '2026-02-23 14:00:01-05'::timestamptz),
    (2,  2,  'success', NULL,              '2026-02-23 14:10:01-05'),
    (3,  3,  'success', NULL,              '2026-02-23 14:15:01-05'),
    (4,  4,  'success', NULL,              '2026-02-23 14:20:01-05'),
    (5,  5,  'success', NULL,              '2026-02-23 14:25:01-05'),
    (6,  6,  'timeout', 'gateway_timeout', '2026-02-23 14:35:01-05'),
    (7,  7,  'timeout', 'gateway_timeout', '2026-02-23 14:36:01-05'),
    (8,  8,  'timeout', 'gateway_timeout', '2026-02-23 14:37:01-05'),
    (9,  9,  'timeout', 'gateway_timeout', '2026-02-23 14:38:01-05'),
    (10, 10, 'timeout', 'gateway_timeout', '2026-02-23 14:39:01-05')
) AS seed(id, order_id, status, error_message, created_at)
WHERE NOT EXISTS (SELECT 1 FROM payments);

-- Reset the sequences to avoid conflicts with future inserts
SELECT setval('orders_id_seq', COALESCE((SELECT MAX(id) FROM orders), 0));
SELECT setval('payments_id_seq', COALESCE((SELECT MAX(id) FROM payments), 0));
