# MiDoc — Producto completo con design system

Producto real salvo pagos simulados, con design system propio y UX de los 3 flujos.
Rama: `feat/producto-completo`. Fase 3 del Proyecto Integrador: 30-nov-2026 (equipos 1-4) o 3-dic-2026 (5-8).

## Specs

S1 — Design system completo y funcionando en todas las pantallas.
> "quiero que se defina un sistem desing que se complete todo su funcionamiento"

S2 — Lo único simulado son los pagos; el resto funciona de verdad.
> "la única función que puede quedar simulada es la de pagos"

S3 — UX de los 3 flujos mejorada, cumpliendo lo académico y entregando mejor producto.
> "también quiero mejorar la ux me parecen demaciado simples los flujos y creo que los podemos aprovechar cumpliendo con lo que se pide pero entregando un mejor producto"

S4 — Diseño compatible con WCAG.
> "me importa solamente que la aplicación sea compatible con 9las wcag en cuanto a el diseño"

S5 — Estilo limpio, pulido, profesional y distintivo, no un design system genérico.
> "que se vea limpio pulido y profecional para el tipo de pproducto pero al mismo tiempo que se vea único y no sea tan similar a la mayoría de sistem desins de otras aplicaciones busca crear un estilo único"

S6 — Requisitos del Proyecto Integrador que se demuestran en la fase 3 (enunciado, secciones 3 y 7): 5 métricas + 2 alarmas + dashboard en CloudWatch, CI/CD en GitHub Actions que despliega al integrar a `main`, 3 flujos end-to-end, ≥5 servicios AWS, diagrama de arquitectura, PDF ≤5 páginas.
> "cumpliendo con lo que se pide"

S7 — Orden acordado: piso académico primero, después producto.
> "Piso académico primero (E0 → E1)"

S8 — Alcance acordado para el 30-nov.
> "Académico + design system + 3 flujos"

## Tasks

| ID | Spec | Tarea | Ruta | Commit |
| --- | --- | --- | --- | --- |
| T1 | S2 | Migración `003` que iguala `migrations/` con `schema.sql` (4 tablas y 5 índices faltantes) | inline | 66e04f8 |
| T2 | S2 | Auditoría DynamoDB no rompe la lectura de expediente si falla | inline | 0347935 |
| T3 | S6 | 5 métricas de negocio + 2 alarmas + dashboard CloudWatch en Terraform | inline | 78bd116 |
| T4 | S6 | Workflow de CD que despliega al integrar a `main`, con la limitación del Learner Lab documentada | inline | 73a71ef |
| T5 | S6 | Redespliegue con Terraform y evidencia E2E de los 3 flujos | inline | L11 |
| T6 | S1,S4,S5 | `design/system.md` + tokens + escala tipográfica y de espacio | inline | d8229dd |
| T7 | S1,S4 | Primitivas: button, field, table, badge, dialog, toast, tabs, pagination, empty, confirm | inline | e571b31 |
| T8 | S5 | Artboards de las 6 pantallas y aprobación de dirección visual | inline | 93915ff (L7) |
| T9 | S3 | Router con guards, deep links y back/forward funcional | inline | e571b31 |
| T10 | S2,S3 | Renovación silenciosa de sesión (`POST /api/auth/refresh`) | inline | e571b31 |
| T11 | S3 | Flujo 1: filtros, paginación, perfil de doctor, calendario, post-reserva accionable | inline | L12 |
| T12 | S3 | Flujo 2: expediente por secciones, documentos sin 503 opaco, confirmación de revocación, "quién vio mi expediente" | inline | e571b31 |
| T13 | S2,S3 | Flujo 3: consulta en 3 pasos y receta PDF real en S3 con URL firmada | inline | 7b953e6 |
| T14 | S2 | Perfil editable (`PUT /api/me`) y cambio de contraseña | inline | 7b953e6 |
| T15 | S6 | Cierre: PDF 5 páginas, diagrama, `CIERRE-AWS.md`, guion del video | pendiente | pending |

## Log

L1 (usuario, verbatim):
> hay cosas que me preocupan una de ellas es el pproducto como tal quiero que se defina un sistem desing que se complete todo su funcionamiento la única función que puede quedar simulada es la de pagos también quiero mejorar la ux me parecen demaciado simples los flujos y creo que los podemos aprovechar cumpliendo con lo que se pide pero entregando un mejor producto  me gustaría que me hagas una propuesta con relación a esto identifica también los principales problemas errores para que me des un resumen de lo que vas a hacer

L2 (decisiones del usuario): orden = piso académico primero (E0 → E1); alcance = académico + design system + 3 flujos; diseño = criterio de aceptación WCAG + estilo único, sin exigir aprobación previa por artboards.

L3 (evidencia): exploración verificada del 15-nov-2026. Sin router (`main.ts:1-7`, `app.component.ts:21`); 0 tokens y 28 hex (`styles.css`, `app.component.css`); 0 primitivas; sesión sin refresh (`app.py:210`, `api.service.ts:256-260`); sin `PUT /api/me`; receta sin PDF en servidor (`app.py:356-359`); documentos 503 sin S3; revocación sin confirmar (`expediente.component.html:79`); `flujos.py:758` → `app.py:102-104` sin `try`; `migrations/001+002` omiten 4 tablas y 5 índices frente a `schema.sql`.

L4 (E0 y T3 cerrados, 15-nov-2026): E0 completo — migración `003` + `test_migraciones.py` (66e04f8) y auditoría tolerante a fallos de DynamoDB + `test_auditoria.py` (0347935). Suite: 63 pruebas verdes. T3 — se integró `origin/feat/monitoring` (235 líneas, merge `3afa19a`) y se añadió `infrastructure/monitoring.tf` con 2 alarmas, dashboard y el escape `enable_monitoring` (78bd116). Verificación independiente: PASS en las 7 comprobaciones salvo V7 (faltaba atar `monitoring.tf` a `metricas.py`, ya cubierto por `test_monitoreo.py`) y V6 parcial (el Lab no permite confirmar `cloudwatch:PutMetricAlarm`/`PutDashboard` sin AWS). `terraform fmt -check` y `validate` en verde.

L5 (frontera de slice): 645 líneas autoradas en 7 commits desde `origin/main`, de las cuales 235 vienen del merge de `feat/monitoring`. La siguiente unidad (T4, CD) empieza un slice nuevo.

L6 (design system y direcciones visuales, 15-nov-2026): `design/system.md` + `design/system.html` (d5e8e8f) fijan la identidad —papel cálido, tinta verde, serif editorial, filete clínico— con todas las relaciones de contraste calculadas. `design/midoc-v2/` contiene tres artboards de la pantalla de búsqueda y reserva del paciente sobre ese sistema: `01-indice.html` (índice editorial), `02-triage.html` (triaje por pasos) y `03-mesa.html` (mesa clínica). Ninguno se migra a `frontend/` hasta que el humano elija dirección (risk item 3). Pendiente detectado por el artboard: el orden por precio y el "próximo horario" son presentacionales porque `flujos.py` ordena por nombre, y "Guadalajara y zona metropolitana" no es un filtro real del backend.

L7 (dirección elegida por el usuario, 15-nov-2026): híbrido `hibrido-01-03`. Estructura del **índice editorial** (`01-indice.html`) para búsqueda y ficha del doctor, más la **columna de agenda semanal** de la mesa clínica (`03-mesa.html`) en el momento de reservar. El detalle del doctor pasa a ser su propia ruta con deep link. Consecuencia de producto: el orden por precio y la disponibilidad más próxima tienen que pasar al API si se muestran (hoy `flujos.py` ordena por nombre).

L8 (T6 cerrado, 15-nov-2026, d8229dd): los 76 tokens de `design/system.md` entran a `frontend/src/styles/_tokens.css` (cargado antes de `styles.css` en `angular.json`) y los 8 interlineados de la escala quedaron escritos como tokens en el documento, que era la única diferencia entre ambos conjuntos. `tokens.spec.ts` convierte el contrato en prueba: los conjuntos de tokens coinciden en las dos direcciones y 15 parejas de color cumplen el mínimo WCAG (4.5:1 texto, 3:1 límites de control y foco). El runner pasa de Karma (sin config, script muerto) a `@angular/build:unit-test` con vitest + jsdom; CI ejecuta `npm test` en el job de frontend. Verificación local: `ng build` verde, `tsc -p tsconfig.spec.json --noEmit` verde, `vitest run` con 18 pruebas verdes.

L9 (defecto de entorno, 15-nov-2026): `ng test` falla **sólo en esta máquina** con `No test files found`. Causa aislada con sondas directas: el builder entrega a vitest un `include` con la ruta absoluta del spec, y `tinyglobby` 0.2.17 no encuentra coincidencias cuando la ruta contiene paréntesis — este repositorio vive bajo `Desarrollo en la Nube (AWS)`. Sin paréntesis (directorio limpio en `%TEMP%`) el mismo patrón absoluto sí coincide; con sólo espacios también. No es regresión del cambio: en CI (Linux, ruta sin metacaracteres) `npm test` sí resuelve. Alternativas si molesta el desarrollo local: mover el clon a una ruta sin paréntesis, o exponer el repo con un `subst`/junction y correr ahí; ninguna se aplicó porque la primera es decisión del humano y la segunda escribe fuera del proyecto.

L10 (frontera de slice, 19-nov-2026): la fase 3 completa quedó consolidada en 3 commits (7b953e6 backend, e571b31 frontend, 73a71ef docs/CI-CD) más el modo simulado en commits L11. Slice acumulado: ~28.6k líneas autoradas en 17 commits desde `origin/main` en `feat/producto-completo` — demasiado para un PR único; al publicar, trocear en PRs encadenados por área (backend, frontend, docs/infra).

L11 (despliegue en vivo y modo simulado, 19-nov-2026): el usuario autorizó `terraform apply` sin pedir permiso y pidió "inventar una clave" de Stripe porque no tenía la llave a la mano. Una clave inventada no puede hablar con api.stripe.com (401), así que se implementó el modo `payment_mode="simulado"` — el único comportamiento permitido como simulado (S2): checkout genera sesión `cs_sim_*` con `checkoutUrl` interna `#/suscripcion/pago-simulado`, `consultar_sesion_checkout` la resuelve pagada sin red, confirm valida pertenencia vía el registro pendiente y activa la suscripción; la validación de successUrl/cancelUrl aplica también en simulado (endurecimiento, 6 pruebas nuevas en `test_pagos_stripe.ModoPagoSimuladoTests`, RED→GREEN). Despliegue en vivo: 49 recursos, frontend publicado, smoke de checkout→confirm→ACTIVA verificado con curl contra la API real. E2E en nube: 84/169 → 194/197 → tier 2 en verde (1 skip legítimo: webhooks firmados no aplican sin Stripe real; t2_f07_04 y t2_f14_04 adaptados a detectar `mode=="simulado"` desde la respuesta, no de la bandera CLI).

L12 (pulido UI inline y observabilidad, 19-nov-2026): los subagentes `gentle-ai-worker` fallaron por error de autenticación del runtime (3 intentos), así que el pulido se hizo inline con las mismas restricciones. Flujo 1: ruta pública `doctores/:id` con deep link (L7), cierre vuelve a /buscar, specs de rutas/búsqueda adaptados (58 pruebas verdes). Flujo 2 verificado maduro (secciones ancladas, modales de revocación/eliminación, bitácora). Flujo 3: insignias y banner del modo simulado en el panel. Observabilidad verificada en vivo: 9 métricas EMF en namespace `MiDoc`, 10 alarmas (todas OK salvo `midoc-payment-failed` en ALARM por los webhooks maliciosos intencionales del E2E — evidencia de que funciona), dashboard `midoc-estado`, SNS `midoc-alerts`. Pendiente del usuario: llave `sk_test_` real (cambiar `payment_mode="test"` + `stripe_secret_key` y re-aplicar) y T15 (PDF de cierre).
