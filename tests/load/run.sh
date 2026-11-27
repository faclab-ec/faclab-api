#!/usr/bin/env bash
# Runs one k6 scenario against the load environment, with the server sampled meanwhile (S9.2).
#
#   run.sh <name> <scenario.js> [VAR=value ...]
#
#   LOAD_FIXTURES  what setup_data.py wrote (outside the repository)
#   LOAD_RESULTS   where each run leaves <name>/ (outside the repository)
#   LOAD_VM        OrbStack machine of the environment (default faclab-load)
#   K6_IMAGE       default grafana/k6:1.3.0
#   LOAD_NO_SAMPLE only k6: another run is already sampling the server
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
NAME=${1:?name of the run}
SCENARIO=${2:?scenario}
shift 2

: "${LOAD_FIXTURES:?}" "${LOAD_RESULTS:?}"
VM=${LOAD_VM:-faclab-load}
K6_IMAGE=${K6_IMAGE:-grafana/k6:1.3.0}
IP=$(orbctl info "$VM" --format json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("ip4") or d["record"]["ip4"])')
OUT="$LOAD_RESULTS/$NAME"
mkdir -p "$OUT"

vm() { orb -m "$VM" -u root "$@"; }

args=()
for pair in "$@"; do args+=(-e "$pair"); done

SINCE=$(date -u '+%Y-%m-%d %H:%M:%S')
if [[ -z "${LOAD_NO_SAMPLE:-}" ]]; then
  vm bash -c "rm -rf /tmp/sample && mkdir -p /tmp/sample && nohup bash /opt/load/sample.sh /tmp/sample > /tmp/sample/log 2>&1 &" < /dev/null
fi

status=0
docker run --rm -i --user "$(id -u):$(id -g)" \
  --add-host "api.faclab.test:$IP" \
  -v "$HERE:/scripts:ro" -v "$LOAD_FIXTURES:/data/fixtures.json:ro" -v "$OUT:/results" \
  "$K6_IMAGE" run --quiet --log-output=file=/results/k6.log \
  -e SUMMARY=/results/summary.json "${args[@]+"${args[@]}"}" "/scripts/$SCENARIO" |
  tee "$OUT/summary.txt" || status=$?
[[ -z "${LOAD_NO_SAMPLE:-}" ]] || exit "$status"

# Let the queues drain before measuring what the run left
sleep "${SETTLE_SECONDS:-20}"
vm touch /tmp/sample/stop < /dev/null
sleep 6
vm tar -C /tmp/sample -cf - . < /dev/null | tar -xf - -C "$OUT"
vm bash -c "docker exec -i faclab-postgres-1 psql -U postgres -d faclab -v since='$SINCE' -f - < /opt/load/after.sql" |
  tee "$OUT/after.txt"
echo "$SINCE" > "$OUT/since"
python3 "$HERE/summarize.py" "$OUT" | tee "$OUT/server.txt"
exit "$status"
