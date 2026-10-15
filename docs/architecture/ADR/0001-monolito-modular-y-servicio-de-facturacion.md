# ADR-0001: Monolito modular más un servicio de facturación

- **Estado:** propuesto (2026-10-14)
- **Relacionado:** [ADR-0005](0005-kafka-outbox-y-consumidores-idempotentes.md), [ADR-0007](0007-worker-para-procesos-en-segundo-plano.md)

## Contexto

faclab-core concentra 12 módulos de negocio con arquitectura limpia y CQRS, una sola base PostgreSQL
y una sesión por request. El POS confirma la venta, descuenta stock, registra pagos y escribe el outbox
en **una sola transacción**. faclab-invoicing vive aparte: firma XML, habla SOAP con el SRI, reintenta
durante horas y guarda certificados.

El encargo pide evaluar si conviene separar más servicios (ventas, inventario, caja, cuentas por cobrar).

## Alternativas

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| A. Mantener monolito modular + facturación aparte | Transacciones atómicas venta-stock-caja; un despliegue; bajo costo operativo; ya funciona | Hay que vigilar los límites entre módulos dentro del mismo proceso |
| B. Separar inventario y ventas en servicios | Escalado independiente | Sagas para cada venta, stock eventual (sobreventa), más infraestructura, más tiempo de un equipo pequeño |
| C. Volver a meter facturación en el core | Un servicio menos | El SRI lento o caído afectaría al POS; mezcla secretos de firma con el API de negocio |

## Decisión

**A.** Se conserva el monolito modular y el único servicio separado es facturación. Los límites internos
se refuerzan con reglas, no con red:

- Los módulos de administración se comunican por eventos de dominio; POS es una capa de composición
  (regla existente en `CLAUDE.md`).
- Se aceptan las importaciones cruzadas de lectura (consultas que leen modelos de otros módulos), pero
  no se extienden a comandos.
- Los procesos en segundo plano salen del proceso del API a un contenedor `worker` (ADR-0007), sin
  cambiar de repositorio.

Un módulo se separaría en un servicio solo si cumple al menos dos de estas condiciones: dominio de
fallo distinto, necesidad de escalar muy diferente, equipo dedicado o requisito regulatorio de aislamiento.

## Consecuencias

- Las capacidades nuevas (cuentas por cobrar, cotizaciones, listas de precios, auditoría, webhooks,
  API pública) se agregan como módulos del core.
- El costo operativo se mantiene en dos servicios de aplicación más PostgreSQL y Kafka.
- La deuda de importaciones cruzadas detectada (ventas → catálogo y clientes, compras → proveedores)
  se acepta en lecturas y se documenta; no bloquea esta decisión.
