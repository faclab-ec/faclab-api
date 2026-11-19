#!/usr/bin/env bash
# Un pedido pagado en línea como venta de Faclab, su reintento y su anulación
# (guía "Ventas desde un ecommerce").
#
#   ./venta.sh
#
# Elige la primera sucursal, un producto con stock y su precio con IVA. El
# total se calcula con bc: subtotal e IVA redondeados al centavo, mitad hacia
# arriba, como Faclab.
set -euo pipefail
# Punto decimal en printf, cualquiera sea el idioma del sistema
export LC_ALL=C
: "${FACLAB_API_URL:=http://localhost:3000}"
here=$(dirname "$0")
TOKEN=${TOKEN:-$("$here/token.sh")}

api() {
  curl -sS --fail-with-body "$FACLAB_API_URL$1" -H "Authorization: Bearer $TOKEN" "${@:2}"
}

rate() {
  case $1 in
    VAT_5) echo 5 ;; VAT_8_TOURISM) echo 8 ;; VAT_12) echo 12 ;; VAT_13) echo 13 ;;
    VAT_14) echo 14 ;; VAT_15) echo 15 ;; *) echo 0 ;;
  esac
}

# Un monto a centavos, mitad hacia arriba: se calcula con 6 decimales y bc
# trunca al dividir con scale=2
cents() { echo "scale=6; x = $1; scale=2; (x + 0.005) / 1" | bc; }

branch=$(api /api/v1/branches | jq -c '[.data[] | select(.emissionPoints | length > 0)][0]')
branch_id=$(jq -r .id <<<"$branch")
emission_point=$(jq -r '.emissionPoints[0].id' <<<"$branch")

# Lo que cobra Faclab por una unidad: subtotal más IVA, cada uno al centavo
total_of() {
  local price tax_rate
  price=$(jq -r .salePrice <<<"$1")
  tax_rate=$(rate "$(jq -r .taxCode <<<"$1")")
  printf '%.2f' "$(echo "$(cents "$price") + $(cents "$price * $tax_rate / 100")" | bc)"
}

# El primer producto activo con stock de la sucursal y hasta 50 dólares, lo
# que factura el consumidor final
product=
for row in $(api "/api/v1/stock?branchId=$branch_id&limit=200" \
  | jq -c '.data[] | select((.available | tonumber) >= 1) | {productId, locationId}'); do
  candidate=$(api "/api/v1/products/$(jq -r .productId <<<"$row")" | jq -c .data)
  if [[ $(jq -r '.isActive and (.isService | not)' <<<"$candidate") == true ]] \
    && [[ $(echo "$(total_of "$candidate") <= 50" | bc) -eq 1 ]]; then
    product=$candidate
    break
  fi
done
[[ -n $product ]] || { echo "la sucursal $branch_id no tiene productos con stock" >&2; exit 1; }
total=$(total_of "$product")

order="WEB-$(date +%s)"
body=$(jq -n \
  --argjson emissionPointId "$emission_point" \
  --argjson locationId "$(jq .locationId <<<"$row")" \
  --argjson productId "$(jq .id <<<"$product")" \
  --arg order "$order" --arg total "$total" \
  '{emissionPointId: $emissionPointId, locationId: $locationId, externalReference: $order,
    items: [{productId: $productId, quantity: "1"}],
    payments: [{method: "TRANSFER", amount: $total, reference: "pago-\($order)"}]}')

# Una clave por pedido, la misma en cada reintento de ese pedido
key=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)
post_sale() {
  api /api/v1/sales -X POST -D "$1" \
    -H "X-Branch-Id: $branch_id" -H "Idempotency-Key: $key" \
    -H 'Content-Type: application/json' -d "$body"
}
headers=$(mktemp)
trap 'rm -f "$headers"' EXIT

sale=$(post_sale "$headers" | jq -c .data)
echo "venta $(jq -r .number <<<"$sale") ($order): $(jq -r .sku <<<"$product") por $(jq -r .total <<<"$sale"), factura $(jq -r .invoiceStatus <<<"$sale")"
[[ $(echo "$(jq -r .total <<<"$sale") == $total" | bc) -eq 1 ]] || { echo "total distinto de $total" >&2; exit 1; }

replayed=$(post_sale "$headers" | jq -r .data.id)
grep -qi '^idempotent-replayed: true' "$headers" || { echo "el reintento no fue una repetición" >&2; exit 1; }
[[ $replayed == $(jq -r .id <<<"$sale") ]]
echo "reintento con la misma clave: la misma venta (Idempotent-Replayed)"

found=$(api "/api/v1/sales?externalReference=$order" | jq '.data | length')
[[ $found -eq 1 ]]

# Anular: con la factura en camino responde 400 INVOICE_IN_PROGRESS
cancel=$(curl -sS "$FACLAB_API_URL/api/v1/sales/$(jq -r .id <<<"$sale")/cancel" -X POST \
  -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)" \
  -H 'Content-Type: application/json' -d '{"reason": "Pedido anulado en la tienda"}')
case $(jq -r '.errors[0].code // "OK"' <<<"$cancel") in
  OK) echo "venta anulada: el stock vuelve" ;;
  INVOICE_IN_PROGRESS | CREDIT_NOTE_REQUIRED) echo "venta con factura en camino: $(jq -r '.errors[0].code' <<<"$cancel")" ;;
  *) echo "anular: $cancel" >&2; exit 1 ;;
esac
