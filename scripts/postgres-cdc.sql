-- Run as a database owner, then attach the trigger to authorized source tables.
CREATE SCHEMA IF NOT EXISTS mina_cdc;
CREATE TABLE IF NOT EXISTS mina_cdc.changes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel text NOT NULL,
    operation text NOT NULL,
    source_table text NOT NULL,
    old_row jsonb,
    new_row jsonb,
    lease_token text,
    lease_until timestamptz NOT NULL DEFAULT '-infinity'
);
CREATE INDEX IF NOT EXISTS mina_cdc_channel_id ON mina_cdc.changes (channel, id);

CREATE OR REPLACE FUNCTION mina_cdc.capture_row()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    INSERT INTO mina_cdc.changes (channel, operation, source_table, old_row, new_row)
    VALUES (
        TG_ARGV[0], TG_OP, format('%I.%I', TG_TABLE_SCHEMA, TG_TABLE_NAME),
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END
    );
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION mina_cdc.capture_row() FROM PUBLIC;

-- Example for a source table owned by the installing role
-- CREATE TRIGGER mina_orders AFTER INSERT OR UPDATE OR DELETE ON public.orders
-- FOR EACH ROW EXECUTE FUNCTION mina_cdc.capture_row('orders');
-- GRANT USAGE ON SCHEMA mina_cdc TO mina_runtime;
-- GRANT SELECT, UPDATE (lease_until, lease_token), DELETE ON mina_cdc.changes TO mina_runtime;
