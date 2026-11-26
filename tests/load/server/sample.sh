#!/usr/bin/env bash
# What the server does while k6 runs (S9.2). On the staging host, as root:
#
#   sample.sh <output folder>      until it is killed (or the file <output folder>/stop appears)
#
# Every 5 s: PostgreSQL connections, lock waits and what waits, the outbox and the invoices by status.
# Every 10 s: CPU and memory of each container and of the host. Every 30 s: Kafka consumer lag.
set -euo pipefail

OUT=${1:?output folder}
PROJECT=${PROJECT:-faclab}
mkdir -p "$OUT"
rm -f "$OUT/stop"

psql_in() {
  docker exec "$PROJECT-postgres-1" psql -U postgres -d "$1" -At -F, -c "$2" < /dev/null 2> /dev/null || true
}
stamp() { sed "s/^/$1,/"; }

tick=0
while [[ ! -e "$OUT/stop" ]]; do
  now=$(date -u +%H:%M:%S)
  psql_in postgres "SELECT datname, coalesce(usename, '-'), coalesce(state, '-'), count(*)
    FROM pg_stat_activity WHERE datname LIKE 'faclab%' GROUP BY 1, 2, 3" | stamp "$now" >> "$OUT/connections.csv"
  psql_in postgres "SELECT datname, wait_event_type, wait_event, count(*),
      round(max(extract(epoch FROM clock_timestamp() - query_start))::numeric, 3),
      left(regexp_replace(min(query), '[\s,]+', ' ', 'g'), 90)
    FROM pg_stat_activity
    WHERE datname LIKE 'faclab%' AND state <> 'idle' AND wait_event_type IN ('Lock', 'LWLock', 'IO')
    GROUP BY 1, 2, 3" | stamp "$now" >> "$OUT/waits.csv"
  psql_in faclab "SELECT status, count(*), round(extract(epoch FROM (now() AT TIME ZONE 'utc') - min(created_at))::numeric, 1)
    FROM outbox_messages WHERE status <> 'published' GROUP BY 1" | stamp "$now" >> "$OUT/outbox.csv"
  psql_in faclab_invoicing "SELECT status, count(*) FROM invoices
    WHERE status NOT IN ('authorized', 'rejected') GROUP BY 1" | stamp "$now" >> "$OUT/invoices.csv"

  if ((tick % 2 == 0)); then
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' < /dev/null | stamp "$now" >> "$OUT/stats.csv"
    awk -v now="$now" '/^MemAvailable/ {print now "," $2}' /proc/meminfo >> "$OUT/host-mem.csv"
    echo "$now,$(cut -d' ' -f1-3 /proc/loadavg | tr ' ' ,)" >> "$OUT/load.csv"
  fi
  if ((tick % 6 == 0)); then
    docker exec -e KAFKA_HEAP_OPTS=-Xmx64m "$PROJECT-kafka-1" kafka-consumer-groups \
      --bootstrap-server localhost:9092 --describe --all-groups < /dev/null 2> /dev/null |
      awk '$6 ~ /^[0-9]+$/ {lag[$1 "," $2] += $6} END {for (k in lag) print k "," lag[k]}' |
      stamp "$now" >> "$OUT/lag.csv"
  fi
  tick=$((tick + 1))
  sleep 5
done
