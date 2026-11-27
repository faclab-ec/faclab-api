-- What a run left behind (S9.2), measured by the databases themselves. As the postgres superuser:
--
--   psql -U postgres -d faclab -v since='2026-11-26 14:00:00' -f after.sql
--
-- `since` is in UTC.
\pset footer off
\echo '== core: sales confirmed since the mark'
SELECT count(*) AS sales,
       count(*) FILTER (WHERE invoice_status = 'AUTHORIZED') AS authorized,
       count(*) FILTER (WHERE invoice_status = 'PENDING') AS pending,
       count(*) FILTER (WHERE invoice_status = 'REJECTED') AS rejected
FROM sales WHERE invoice_requested_at >= :'since';

\echo '== core: outbox, seconds from written to published'
SELECT topic, count(*),
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM published_at - created_at))::numeric, 2) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM published_at - created_at))::numeric, 2) AS p95,
       round(max(extract(epoch FROM published_at - created_at))::numeric, 2) AS max,
       count(*) FILTER (WHERE status = 'failed') AS failed
FROM outbox_messages WHERE created_at >= :'since' GROUP BY topic;

\echo '== core: dead letters'
SELECT count(*) FROM dead_letters;

\connect faclab_invoicing
\echo '== invoicing: seconds from requested to authorized'
SELECT status, count(*),
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM authorized_at - requested_at))::numeric, 2) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM authorized_at - requested_at))::numeric, 2) AS p95,
       round(max(extract(epoch FROM authorized_at - requested_at))::numeric, 2) AS max,
       round(extract(epoch FROM max(authorized_at) - min(requested_at))::numeric, 0) AS window_s
FROM invoices WHERE requested_at >= :'since' GROUP BY status;

\echo '== invoicing: dead letters'
SELECT count(*) FROM dead_letters;
