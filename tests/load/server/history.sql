-- Months of history for the listings and reports (S9.2), made from the sales the load runs already
-- wrote: each copy keeps its lines, payments and stock movements, `day_step` days further back.
-- Only on a throwaway load environment, as the postgres superuser:
--
--   psql -U postgres -d faclab -v copies=20 -v day_step=7 -f history.sql
--
-- The copies are good for reading only: they don't move stock, cash nor receivables.
\set ON_ERROR_STOP on
SET faclab.copies = :'copies';
SET faclab.day_step = :'day_step';

DO $$
DECLARE
    copies int := current_setting('faclab.copies');
    day_step int := current_setting('faclab.day_step');
    -- Ids of copy k are those of the original plus k * offset
    offset_ bigint := 10000000;
    last_sale bigint;
    shift_by text;

    insert_copy text;
    spec record;
BEGIN
    SELECT max(id) INTO last_sale FROM sales WHERE id < offset_;

    FOR k IN 1..copies LOOP
        shift_by := format('interval %L', (k * day_step) || ' days');
        FOR spec IN
            SELECT * FROM (VALUES
                (1, 'sales', format('id <= %s', last_sale),
                    jsonb_build_object(
                        'id', format('id + %s', k * offset_),
                        'number', format('''H%s'' || substr(number, 2)', k),
                        'invoice_status', '''AUTHORIZED''',
                        'external_reference', 'NULL',
                        'integration_client_id', 'NULL',
                        'quote_id', 'NULL')),
                (2, 'sale_items', format('sale_id <= %s', last_sale),
                    jsonb_build_object(
                        'id', format('id + %s', k * offset_),
                        'sale_id', format('sale_id + %s', k * offset_))),
                (3, 'payments', format('sale_id <= %s', last_sale),
                    jsonb_build_object(
                        'id', format('id + %s', k * offset_),
                        'sale_id', format('sale_id + %s', k * offset_))),
                (4, 'movements', format('reference_type = ''sale'' AND reference_id <= %s', last_sale),
                    jsonb_build_object(
                        'id', format('id + %s', k * offset_),
                        'reference_id', format('reference_id + %s', k * offset_)))
            ) AS t(position, name, filter, overrides)
            ORDER BY position
        LOOP
            -- Every column as it is, except the ids above and the dates, further back
            SELECT format(
                'INSERT INTO %I (%s) SELECT %s FROM %I WHERE id < %s AND %s',
                spec.name,
                string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position),
                string_agg(
                    coalesce(
                        spec.overrides ->> column_name,
                        CASE WHEN data_type LIKE 'timestamp%' OR data_type = 'date'
                             THEN quote_ident(column_name) || ' - ' || shift_by
                             ELSE quote_ident(column_name) END),
                    ', ' ORDER BY ordinal_position),
                spec.name, offset_, spec.filter)
            INTO insert_copy
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = spec.name;
            EXECUTE insert_copy;
        END LOOP;
    END LOOP;

    FOR spec IN SELECT unnest(ARRAY['sales', 'sale_items', 'payments', 'movements']) AS name LOOP
        EXECUTE format(
            'SELECT setval(pg_get_serial_sequence(%L, ''id''), (SELECT max(id) FROM %I))',
            spec.name, spec.name);
    END LOOP;
END $$;

ANALYZE;
SELECT 'sales' AS rows_of, count(*) FROM sales
UNION ALL SELECT 'sale_items', count(*) FROM sale_items
UNION ALL SELECT 'movements', count(*) FROM movements;
