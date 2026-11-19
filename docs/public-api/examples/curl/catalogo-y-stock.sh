#!/usr/bin/env bash
# Sucursales, productos cambiados y stock (guía "Sincronizar catálogo y stock").
#
#   ./catalogo-y-stock.sh [updatedSince]
#
# Sin argumento trae la primera página de productos; con una fecha ISO 8601
# (2026-11-18T15:00:00Z), solo los cambiados desde entonces.
set -euo pipefail
: "${FACLAB_API_URL:=http://localhost:3000}"
here=$(dirname "$0")
TOKEN=${TOKEN:-$("$here/token.sh")}
since=${1:-}

api() {
  curl -sS --fail-with-body "$FACLAB_API_URL$1" -H "Authorization: Bearer $TOKEN" "${@:2}"
}

branches=$(api /api/v1/branches)
echo "$branches" | jq -r '.data[] | "sucursal \(.id) \(.code) \(.name): \(.emissionPoints | length) puntos de emisión, \(.locations | length) ubicaciones"'

products=$(api "/api/v1/products?limit=200${since:+&updatedSince=$since}")
echo "$products" | jq -r '"productos: \(.meta.pagination.total)"'
echo "$products" | jq -r '.data[:3][] | "  \(.sku) \(.name) a \(.salePrice) (\(.taxCode))"'

branch=$(echo "$branches" | jq -r '.data[0].id')
stock=$(api "/api/v1/stock?branchId=$branch&limit=200")
# El disponible de un producto en la sucursal: la suma de sus ubicaciones
echo "$stock" | jq -r '[.data[] | {sku, available: (.available | tonumber)}]
  | group_by(.sku) | map({sku: .[0].sku, available: (map(.available) | add)})
  | map(select(.available > 0)) | "con stock en la sucursal \('"$branch"'): \(length) productos"'

total=$(echo "$products" | jq '.meta.pagination.total')
if [[ -z $since && $total -eq 0 ]]; then
  echo "la empresa no tiene productos" >&2
  exit 1
fi
