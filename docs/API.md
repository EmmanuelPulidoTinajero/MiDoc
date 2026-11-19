# API de MiDoc (Fase 3)

La API REST de MiDoc cubre los tres flujos end-to-end del proyecto integrador junto con sus ampliaciones de agenda, recetas PDF en S3, inventario, promociones, mensajería, avisos, gestión de perfil y pagos reales con **Stripe**.

## Convenciones globales

- **Formato de respuestas:**
  - En rutas de negocio, las respuestas exitosas (`2xx`) devuelven `{"data": ...}` y los errores (`4xx`/`5xx`) devuelven `{"error": "mensaje"}`.
  - **Excepciones explícitas:** `GET /health` devuelve `{"status": "ok", "service": "midoc-api"}`, y las tres rutas de autenticación (`POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`) devuelven directamente `{"token": "<jwt>", "user": {...}}` sin envoltorio `data`.
- **Autenticación (`🔒`):** Encabezado `Authorization: Bearer <token>` (JWT HS256 con vigencia de 1 hora). Si falta, es inválido o expiró, responde `401`.
- **CORS:** `access-control-allow-origin: *`, `access-control-allow-headers: content-type, authorization, idempotency-key`, `access-control-allow-methods: GET,POST,PUT,PATCH,DELETE,OPTIONS`. `OPTIONS *` responde `204 {}`.
- **Idempotencia (`Idempotency-Key`):** Encabezado opcional (`<= 160` caracteres; `400` si excede el límite, `409` si se reutiliza con distinto método, ruta o cuerpo) soportado en `POST /api/appointments`, `POST /api/messages`, `POST /api/consultations` y `POST /api/subscriptions/checkout`.
- **Identificadores y zona horaria:** En AWS PostgreSQL los IDs son UUID; las fechas y horarios se manejan en hora de Ciudad de México (`UTC-6`) en formato ISO 8601 (por ejemplo `2026-11-20T10:00:00-06:00`).
- **Cuentas semilla (`ALLOW_DEMO_SEED`):** En producción (`NODE_ENV=production`), `ALLOW_DEMO_SEED` permanece en `false` por defecto; no se siembran usuarios ni suscripciones demo automáticamente. En desarrollo local (`NODE_ENV != production`) puede habilitarse para pruebas locales.

---

## Salud, cuentas y sesión

| Método | Ruta | Auth / Rol | Descripción y contrato |
| --- | --- | --- | --- |
| `GET` | `/health` | Pública | Devuelve `200 {"status": "ok", "service": "midoc-api"}`. |
| `POST` | `/api/auth/register` | Pública | Crea cuenta `PACIENTE`, `DOCTOR` o `CLINICA`. Recibe `{email, password, role, name, phone?, specialty?, location?, city?, description?, price?, durationMin?}`. Responde `201 {"token", "user"}` (`400`/`409` en error). |
| `POST` | `/api/auth/login` | Pública | Recibe `{email, password}`. Responde `200 {"token", "user": {id, email, role}}` o `401`. Aplica límite por IP: `429` tras 5 intentos fallidos en 300 s. |
| `POST` | `/api/auth/refresh` | 🔒 Cualquier rol | Renueva el JWT por 1 hora adicional y responde `200 {"token", "user"}` (`401`/`404`). |
| `GET` | `/api/me` | 🔒 Cualquier rol | Responde `200 {"data": {id, email, role, name, phone, doctorId, doctor?, subscription?}}`. |
| `PUT` | `/api/me` | 🔒 Cualquier rol | Actualiza perfil propio: `{nombreCompleto\|nombre\|name?, telefono\|phone?, currentPassword?, newPassword?, especialidad\|specialty?, ubicacion\|location?, ciudad\|city?, biografia\|descripcion\|description?, precioConsulta\|price?, duracionCitaMin\|durationMin?}`. Devuelve `400` si `currentPassword` es incorrecta. |

---

## Flujo 1 · Búsqueda y agenda

| Método | Ruta | Auth / Rol | Descripción y contrato |
| --- | --- | --- | --- |
| `GET` | `/api/doctors` | Pública | Query `?specialty=&location=&q=&sort=NAME\|PRICE_ASC\|PRICE_DESC\|AVAILABILITY`. Lista únicamente profesionales con suscripción activa; incluye `promotions`, `promotionSummary` y `nextAvailableSlot`. |
| `GET` | `/api/doctors/{id}` | Pública | Devuelve perfil completo, horario semanal (`schedule`), `promotions` y `promotionSummary` (`400`/`404`). |
| `GET` | `/api/doctors/{id}/availability` | Pública | Query `?date=AAAA-MM-DD` (hoy hasta +90 días). Devuelve `{doctorId, date, durationMin, slots}`. |
| `PUT` | `/api/doctor/schedule` | 🔒 `DOCTOR`/`CLINICA` | `{blocks: [{day (1..7), start ("HH:MM"), end ("HH:MM")}]}` (máximo 30 bloques sin traslapes; 1 = lunes). |
| `POST` | `/api/appointments` | 🔒 `PACIENTE` | `{doctorId, dateTime, reason?}` + `Idempotency-Key` opcional. Valida horario libre, futuro y <=90 días; índice único evita doble reserva (`409`). Responde `201`. |
| `GET` | `/api/appointments` | 🔒 Cualquier rol | Query `?status=PENDIENTE\|CONFIRMADA\|CANCELADA\|COMPLETADA`. Lista citas del usuario con nombres de paciente/doctor. |
| `GET` | `/api/appointments/{id}` | 🔒 Participante | Detalle de la cita (`400`/`404`). |
| `PUT` | `/api/appointments/{id}/status` | 🔒 Participante | `{status: "CONFIRMADA"\|"CANCELADA"}`. `CONFIRMADA` es exclusivo del proveedor sobre citas `PENDIENTE`; `CANCELADA` aplica a citas futuras activas y libera el horario. |
| `PUT` | `/api/appointments/{id}/reschedule` | 🔒 Participante | `{dateTime}` mueve una cita futura activa a otro espacio disponible y genera aviso a la contraparte (`400`/`404`/`409`). |

---

## Flujo 2 · Expediente, consentimiento y documentos S3

| Método | Ruta | Auth / Rol | Descripción y contrato |
| --- | --- | --- | --- |
| `GET` | `/api/records` | 🔒 `PACIENTE` o `DOCTOR`/`CLINICA` | Paciente consulta su expediente; proveedor requiere `?patientId=`, suscripción activa (`402`) y consentimiento vigente (`403`). Cada lectura profesional se registra en RDS (`bitacora_acceso_expediente`) y DynamoDB. |
| `PUT` | `/api/records` | 🔒 `PACIENTE` | `{birthDate?, sex?, bloodType?, allergies[]?, chronicConditions[]?, medications[]?, notes?}`. |
| `GET` | `/api/records/access-log` | 🔒 `PACIENTE` | Devuelve historial cronológico de accesos al expediente (`[{id, actorId, actorName, actorRole, specialty, event, accessedAt}]`) combinando PostgreSQL y respaldo DynamoDB. |
| `POST` | `/api/consents` | 🔒 `PACIENTE` | `{doctorId, granted: true \| false}` otorga o revoca acceso al expediente y emite aviso transaccional al profesional. |
| `GET` | `/api/consents` | 🔒 `PACIENTE` | Lista médicos/clínicas con su estado de autorización (`[{doctorId, doctorName, specialty, granted, updatedAt}]`). |
| `POST` | `/api/records/documents` | 🔒 `PACIENTE` | `{name, contentType, size}` para `PDF`, `JPG`/`JPEG`, `PNG` o `DICOM` (`.dcm`/`.dicom` con `application/dicom`, `application/octet-stream` o vacío) de 1 B a 10 MB. Devuelve POST firmado a S3 (`expiresIn: 300`). |
| `GET` | `/api/records/documents` | 🔒 `PACIENTE` o `DOCTOR`/`CLINICA` | Proveedor requiere `?patientId=`, suscripción (`402`) y consentimiento (`403`); registra acceso. Devuelve URLs firmadas GET con vigencia de 300 s. |
| `DELETE` | `/api/records/documents/{documentId}` | 🔒 `PACIENTE` | Elimina el objeto privado en S3 (`{"data": {"deleted": true}}`). |

---

## Flujo 3 · Suscripción Stripe, consultas, recetas PDF, inventario y promociones

La suscripción mensual ($20.00 USD / 30 días para `DOCTOR` y `CLINICA`) opera mediante **Stripe Checkout Sessions y Webhook firmado** (ver [PAGOS-STRIPE.md](PAGOS-STRIPE.md)). El antiguo endpoint de pago simulado fue retirado definitivamente y responde **`410 Gone`**.

| Método | Ruta | Auth / Rol | Descripción y contrato |
| --- | --- | --- | --- |
| `POST` | `/api/subscriptions/checkout` | 🔒 `DOCTOR`/`CLINICA` | Recibe `{successUrl?, cancelUrl?}` + `Idempotency-Key` opcional. Crea sesión en Stripe (`mode=payment`, `$20.00 USD`), persiste intento `PENDIENTE` y devuelve `201 {"data": {sessionId, checkoutUrl, mode, amountUsd}}`. |
| `POST` | `/api/subscriptions/confirm` | 🔒 `DOCTOR`/`CLINICA` | Recibe `{sessionId}` (`cs_...`). Verifica en Stripe `payment_status == "paid"`, `livemode` y `metadata.doctorId`; activa/encadena 30 días de forma idempotente con `pg_advisory_xact_lock` y devuelve `200 {"data": {subscription, payment}}`. |
| `POST` | `/api/webhooks/stripe` | Pública (HMAC `Stripe-Signature`) | Verifica firma HMAC-SHA256 (`tolerancia 300 s`) con `STRIPE_WEBHOOK_SECRET` y `livemode`. Procesa `checkout.session.completed`, `checkout.session.expired` y `payment_intent.payment_failed`. |
| `GET` | `/api/subscriptions` | 🔒 `DOCTOR`/`CLINICA` | Devuelve `{subscription, paymentMode, history}` con estado vigente, modo (`test`/`live`) e historial (`referencia_pago`, `tarjeta_marca`, `tarjeta_ultimos4`, `modo_pago`, `stripe_session_id`). |
| `GET` | `/api/doctor/patients` | 🔒 `DOCTOR`/`CLINICA` (sub) | Lista pacientes que otorgaron consentimiento al profesional. |
| `POST` | `/api/consultations` | 🔒 `DOCTOR`/`CLINICA` (sub+consent) | `{patientId, appointmentId, diagnosis, treatment, notes?}` + `Idempotency-Key` opcional (cita del doctor con hora ya iniciada). Transacción ACID: marca cita `COMPLETADA`, crea `consulta` + `receta`, genera PDF real (`pdf_receta.py`), lo sube a S3 (`recetas/{receta_id}.pdf`) y devuelve `201` con `prescriptionId`, `documentKey`, `downloadUrl` y `hasPdf`. |
| `GET` | `/api/prescriptions/{id}` | 🔒 `PACIENTE` dueño o `DOCTOR`/`CLINICA` (sub+consent) | Devuelve metadatos clínicos de la receta más `hasPdf` y `downloadUrl` (URL firmada S3 por 300 s). |
| `GET` | `/api/doctor/inventory` | 🔒 `DOCTOR`/`CLINICA` (sub) | Lista privada de insumos del consultorio/clínica. |
| `POST` | `/api/doctor/inventory` | 🔒 `DOCTOR`/`CLINICA` (sub) | Upsert por nombre (insensible a mayúsculas): `{name, quantity (>= 0), unit}`. |
| `DELETE` | `/api/doctor/inventory/{id}` | 🔒 `DOCTOR`/`CLINICA` (sub) | Elimina un insumo propio. |
| `GET` | `/api/doctor/promotions` | 🔒 `DOCTOR`/`CLINICA` (sub) | Lista promociones propias, vigentes o pasadas. |
| `POST` | `/api/doctor/promotions` | 🔒 `DOCTOR`/`CLINICA` (sub) | `{title, description?, discountPercent (1..90), start, end (>= start)}`. Sólo las vigentes se muestran públicamente. |
| `DELETE` | `/api/doctor/promotions/{id}` | 🔒 `DOCTOR`/`CLINICA` (sub) | Retira una promoción propia. |

---

## Mensajes, notificaciones y EventBridge

| Método | Ruta | Auth / Rol | Descripción y contrato |
| --- | --- | --- | --- |
| `GET` | `/api/messages` | 🔒 Cualquier rol (`DOCTOR`/`CLINICA` sub) | Lista conversaciones propias con conteo de mensajes sin leer. |
| `GET` | `/api/messages/{userId}` | 🔒 Cualquier rol (`DOCTOR`/`CLINICA` sub) | Lee el hilo y marca mensajes recibidos como leídos. Requiere cita o consentimiento entre ambas partes. |
| `POST` | `/api/messages` | 🔒 Cualquier rol (`DOCTOR`/`CLINICA` sub) | `{recipientId, content (1..2000)}` + `Idempotency-Key` opcional. Genera aviso transaccional al destinatario. |
| `GET` | `/api/notifications` | 🔒 Cualquier rol | Lista avisos in-app y materializa recordatorios deduplicados (citas en 24 h, vencimiento de suscripción en 7 días). |
| `PUT` | `/api/notifications/{id}/read` | 🔒 Cualquier rol | Marca un aviso propio como leído (`404` si no pertenece al usuario). |
| *EventBridge* | `{"source": "midoc.reminders"}` | AWS EventBridge (`rate(15 minutes)`) | Invocación programada sin `requestContext`; genera recordatorios en RDS y devuelve `{"processedUsers": int, "status": "ok"}`. |

---

## Códigos de error HTTP

`400` dato inválido o `currentPassword` incorrecta · `401` sin sesión, JWT expirado o firma webhook inválida · `402` suscripción requerida o pago no completado · `403` rol o consentimiento insuficiente · `404` recurso inexistente o ajeno · `409` conflicto de horario, consulta duplicada o reutilización de `Idempotency-Key` con distinto payload · `410` endpoint de pago simulado retirado · `429` límite de intentos de inicio de sesión excedido · `502`/`503` error de pasarela Stripe o almacenamiento S3 no configurado.

---

## Frontend, Design System y configuración en tiempo de ejecución

- **Enrutamiento S3-safe (`HashLocationStrategy`):** Angular 22 utiliza `withHashLocation()` (`#/buscar`, `#/acceso`, `#/citas`, `#/expediente`, `#/mensajes`, `#/panel`, `#/panel/suscripcion`) con guards (`authGuard`, `patientGuard`, `doctorGuard`, `guestGuard`) para que recargas y retornos desde Stripe (`#/panel/suscripcion?stripe_status=success&session_id=...`) funcionen sobre S3 REST `/index.html` sin `404 NoSuchKey`.
- **Design System (`../design/system.md`):** Basado en `frontend/src/styles/_tokens.css` y 9 componentes primitivos en `frontend/src/app/ds/` (incluyendo `DsModalComponent` para todas las confirmaciones destructivas).
- **Configuración dinámica (`config.json`):** En `localhost`/`127.0.0.1` usa `http://localhost:3000` y `paymentMode = "test"`. En S3 lee `config.json` (`{"apiUrl": "https://...", "paymentMode": "test" | "live"}`), generado por `infrastructure/frontend_config.py` y publicado por `infrastructure/publish_frontend.py` con `cache-control: no-cache`.

---

## Límites documentados

- Las promociones de profesionales muestran el porcentaje y precio efectivo de forma informativa; no se canjean ni descuentan cobros por cita (las citas de pacientes no tienen cobro en la plataforma).
- Los avisos se entregan en la bandeja in-app (por restricción de SES en AWS Academy Learner Lab; ver [EVALUACION-INTEGRAL.md](EVALUACION-INTEGRAL.md)).
- La aplicación es un proyecto integrador académico y no cuenta con certificación regulatoria clínica (NOM-024/COFEPRIS/HIPAA).
