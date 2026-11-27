#!/usr/bin/env bash
# A busy hour at once (S9.2): the tills at twice the morning peak, an online store, the back office
# and a price change of the whole catalog by bulk import.
#
#   mixed.sh [duration, default 5m]
#
# Needs what run.sh needs, plus LOAD_ADMIN_PASSWORD, LOAD_CA_FILE and LOAD_BASE_URL for the import.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
DURATION=${1:-5m}
export SETTLE_SECONDS=${SETTLE_SECONDS:-30}

# The tills' run samples the server; the others only run k6
"$HERE/run.sh" mixed-pos pos.js RATE=8 DURATION="$DURATION" &
pos=$!
sleep 10
LOAD_NO_SAMPLE=1 "$HERE/run.sh" mixed-api public_api.js READ_RATE=5 SALES_RATE=4 DURATION="$DURATION" &
api=$!
LOAD_NO_SAMPLE=1 "$HERE/run.sh" mixed-reports reports.js RATE=12 DURATION="$DURATION" &
reports=$!
sleep 30
"${PYTHON:-$HERE/../../.venv/bin/python}" "$HERE/setup_data.py" --reprice
wait "$pos" "$api" "$reports"
