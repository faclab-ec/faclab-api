#!/usr/bin/env bash
# Registra un endpoint de webhooks, guarda su secreto y pide un evento de prueba
# (guía "Webhooks").
#
#   FACLAB_WEBHOOK_URL=https://tienda.example/webhooks/faclab ./webhook.sh
#
# Escribe el secreto en FACLAB_WEBHOOK_SECRET_FILE (por defecto
# ./webhook-secret, solo legible por ti) e imprime el id del endpoint.
set -euo pipefail
: "${FACLAB_API_URL:=http://localhost:3000}"
: "${FACLAB_WEBHOOK_SECRET_FILE:=webhook-secret}"
here=$(dirname "$0")
TOKEN=${TOKEN:-$("$here/token.sh")}

uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }
api() {
  curl -sS --fail-with-body "$FACLAB_API_URL$1" -H "Authorization: Bearer $TOKEN" "${@:2}"
}

endpoint=$(api /api/v1/webhook-endpoints -X POST \
  -H "Idempotency-Key: $(uuid)" -H 'Content-Type: application/json' \
  -d "$(jq -n --arg url "$FACLAB_WEBHOOK_URL" '{url: $url,
        eventTypes: ["sale.confirmed", "invoice.authorized", "invoice.rejected", "credit_note.authorized"],
        description: "Ejemplo de la guía", excludeOwnChanges: false}')")
id=$(jq -r .data.id <<<"$endpoint")

# El secreto se lee aparte y solo se guarda en el servidor del receptor
( umask 077; api "/api/v1/webhook-endpoints/$id/secret" | jq -r .data.secret >"$FACLAB_WEBHOOK_SECRET_FILE" )
echo "endpoint $id: secreto $(jq -r .data.secretHint <<<"$endpoint")… en $FACLAB_WEBHOOK_SECRET_FILE" >&2

api "/api/v1/webhook-endpoints/$id/test" -X POST -H "Idempotency-Key: $(uuid)" >/dev/null
echo "prueba en cola: llega como webhook.test en unos segundos" >&2
echo "$id"
