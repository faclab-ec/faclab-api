#!/usr/bin/env bash
# Corre todos los ejemplos contra una API de Faclab y falla si alguno no hace lo
# que su guía dice. El CI lo corre (job `examples`) contra un core de sandbox
# levantado en el mismo job.
#
#   FACLAB_API_URL=http://localhost:3000 \
#   FACLAB_CLIENT_ID=fl_test_… FACLAB_CLIENT_SECRET=… ./run-all.sh
#
# Necesita bash, curl, jq, bc, python3 con httpx y Node 20 o posterior.
#
# Los webhooks se reciben en receptores locales (127.0.0.1): la API tiene que
# poder llegar a ellos, y solo un core local con WEBHOOK_ALLOW_PRIVATE_URLS=true
# acepta una URL así. FACLAB_WEBHOOK_HOST cambia el host de la URL que se
# registra (host.docker.internal si la API corre en Docker) y
# FACLAB_SKIP_WEBHOOKS=1 salta esa parte (contra el sandbox público, que solo
# envía a URLs https).
set -euo pipefail
cd "$(dirname "$0")"
: "${FACLAB_API_URL:=http://localhost:3000}"
: "${FACLAB_CLIENT_ID:?falta FACLAB_CLIENT_ID}"
: "${FACLAB_CLIENT_SECRET:?falta FACLAB_CLIENT_SECRET}"
: "${FACLAB_WEBHOOK_HOST:=127.0.0.1}"
: "${FACLAB_WEBHOOK_TIMEOUT:=60}"
export FACLAB_API_URL FACLAB_CLIENT_ID FACLAB_CLIENT_SECRET

work=$(mktemp -d)
pids=()
endpoints=()

cleanup() {
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  for id in "${endpoints[@]}"; do
    curl -sS -o /dev/null -X DELETE "$FACLAB_API_URL/api/v1/webhook-endpoints/$id" \
      -H "Authorization: Bearer $TOKEN" || true
  done
  rm -rf "$work"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$*"; }

# Espera hasta que el archivo tenga la línea, o falla con lo que tenga
wait_for() {
  local file=$1 pattern=$2
  for _ in $(seq "$FACLAB_WEBHOOK_TIMEOUT"); do
    grep -q "$pattern" "$file" && return 0
    sleep 1
  done
  echo "no llegó '$pattern' en ${FACLAB_WEBHOOK_TIMEOUT}s:" >&2
  cat "$file" >&2
  return 1
}

TOKEN=$(curl/token.sh)
export TOKEN

step "curl: catálogo y stock"
curl/catalogo-y-stock.sh
step "curl: venta"
curl/venta.sh

step "python: sincronizar catálogo (completa y luego incremental)"
(cd python && FACLAB_SYNC_STATE="$work/sync-python" python3 sincronizar_catalogo.py \
  && FACLAB_SYNC_STATE="$work/sync-python" python3 sincronizar_catalogo.py)
step "python: venta"
(cd python && python3 crear_venta.py)

step "javascript: sincronizar catálogo (completa y luego incremental)"
(cd javascript && FACLAB_SYNC_STATE="$work/sync-js" node sincronizar-catalogo.mjs \
  && FACLAB_SYNC_STATE="$work/sync-js" node sincronizar-catalogo.mjs)
step "javascript: venta"
(cd javascript && node crear-venta.mjs)

# Un receptor: se registra su endpoint, llega la prueba y la venta que se crea
# después, con la firma comprobada
receive() {
  local name=$1 port=$2 dir=$3
  shift 3
  local log="$work/$name.log" secret="$work/$name-secret"
  : >"$secret"
  # exec: el pid es el del receptor, y cleanup lo detiene
  (cd "$dir" && export FACLAB_WEBHOOK_PORT=$port FACLAB_WEBHOOK_SECRET_FILE=$secret \
    && exec "$@") >"$log" 2>&1 &
  pids+=($!)
  wait_for "$log" "escuchando"

  local id
  id=$(FACLAB_WEBHOOK_URL="http://$FACLAB_WEBHOOK_HOST:$port/webhooks/faclab" \
    FACLAB_WEBHOOK_SECRET_FILE=$secret curl/webhook.sh)
  endpoints+=("$id")
  (cd python && python3 crear_venta.py) >/dev/null

  wait_for "$log" "verificado webhook.test"
  wait_for "$log" "verificado sale.confirmed"
  if grep -q "firma inválida" "$log"; then
    echo "el receptor rechazó una firma:" >&2
    cat "$log" >&2
    return 1
  fi
  cat "$log"
}

if [[ ${FACLAB_SKIP_WEBHOOKS:-} == 1 ]]; then
  step "webhooks: saltados (FACLAB_SKIP_WEBHOOKS=1)"
else
  step "python: receptor de webhooks"
  receive python 8701 python python3 receptor_webhooks.py
  step "javascript: receptor de webhooks"
  receive javascript 8702 javascript node receptor-webhooks.mjs
fi

step "todos los ejemplos pasaron"
