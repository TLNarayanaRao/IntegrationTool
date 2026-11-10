CREATE SCHEMA IF NOT EXISTS mina_demo;
CREATE TABLE IF NOT EXISTS mina_demo.orders (
    id integer PRIMARY KEY,
    amount numeric(24, 6) NOT NULL,
    details jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1
);

CREATE OR REPLACE PROCEDURE mina_demo.order_total(IN minimum_id integer, INOUT total numeric)
LANGUAGE plpgsql AS $$
BEGIN
    SELECT COALESCE(SUM(amount), 0) INTO total FROM mina_demo.orders WHERE id >= minimum_id;
END;
$$;

INSERT INTO mina_demo.orders (id, amount, details)
VALUES (1, 11.25, '{"source":"setup"}'), (2, 20.75, '{"source":"setup"}')
ON CONFLICT (id) DO NOTHING;
