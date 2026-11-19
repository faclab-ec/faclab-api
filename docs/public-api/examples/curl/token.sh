#!/usr/bin/env bash
# El token de acceso del cliente de integración (guía "Autenticación").
#
#   export TOKEN=$(./token.sh)
#
# Usa FACLAB_API_URL (por defecto http://localhost:3000), FACLAB_CLIENT_ID y
# FACLAB_CLIENT_SECRET. El token dura 15 minutos: pide otro cuando venza.
set -euo pipefail
: "${FACLAB_API_URL:=http://localhost:3000}"

response=$(curl -sS "$FACLAB_API_URL/api/oauth/token" \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" \
  -d grant_type=client_credentials)

token=$(jq -r '.access_token // empty' <<<"$response")
if [[ -z $token ]]; then
  # Errores de OAuth: {"error": "invalid_client", "error_description": "…"}
  echo "token: $(jq -c . <<<"$response")" >&2
  exit 1
fi
echo "$token"
