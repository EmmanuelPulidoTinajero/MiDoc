# API de MiDoc (ampliación de los flujos)

La API cubre los tres flujos end-to-end del Reporte 1 y sus funciones complementarias de agenda, inventario, promociones, mensajería y avisos.

Todas las respuestas son JSON: `{"data": ...}` si todo salió bien o `{"error": "mensaje"}` si no. Las rutas
marcadas con 🔒 requieren `Authorization: Bearer <token>` (se obtiene en login o registro).

En AWS los identificadores son UUID (doctora demo `10000000-0000-0000-0000-000000000001`, paciente demo
`00000000-0000-0000-0000-000000000001`); en el modo local de demostración son textos como `d-1` o `u-patient-1`.
Las fechas/horas se manejan en hora de Ciudad de México (UTC-6) en formato ISO 8601, por ejemplo
`2026-10-20T10:00:00-06:00`.

## Cuentas y sesión

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST | `/api/auth/register` | Nueva. Crea cuenta `PACIENTE`, `DOCTOR` o `CLINICA` y regresa `{token, user}`. Doctor/clínica además envían `specialty`, `location`, `city`, `price`, `durationMin`. |
| POST | `/api/auth/login` | Sin cambios. |
| GET 🔒 | `/api/me` | Nueva. Datos de la sesión; para doctores incluye perfil, horario y suscripción. |

## Flujo 1 · Búsqueda y agenda

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/api/doctors?specialty=&location=&q=` | Filtros por ubicación y texto; sólo profesionales con suscripción vigente. Incluye promociones activas. |
| GET | `/api/doctors/{id}` | Perfil, horario semanal (`schedule`) y promociones vigentes. |
| GET | `/api/doctors/{id}/availability?date=AAAA-MM-DD` | Nueva. Horarios libres de ese día (`slots`). |
| POST 🔒 | `/api/appointments` | Ampliada: `{doctorId, dateTime, reason?}`. El horario debe estar libre, en el futuro y dentro de 90 días; un índice único impide reservas simultáneas. |
| GET 🔒 | `/api/appointments?status=` | Ampliada: incluye nombres de doctor/paciente y filtro por estado. |
| GET 🔒 | `/api/appointments/{id}` | Nueva. Detalle (solo el paciente o el doctor de la cita). |
| PUT 🔒 | `/api/appointments/{id}/status` | `{status:"CONFIRMADA"}` sólo para el profesional; `{status:"CANCELADA"}` para paciente o profesional. Sólo cambia citas futuras activas; cancelar libera el horario. |
| PUT 🔒 | `/api/appointments/{id}/reschedule` | `{dateTime}` mueve una cita futura activa a un espacio disponible; sólo participante de la cita. Avisa a la otra parte. |
| PUT 🔒 | `/api/doctor/schedule` | Nueva. Doctor: `{blocks: [{day: 1-7, start: "09:00", end: "14:00"}]}` (1 = lunes). |

## Flujo 2 · Expediente y consentimiento

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET 🔒 | `/api/records` | Ampliada: mismos campos (`patient_id`, `allergies`, `notes`) más datos clínicos e historial de consultas. El doctor necesita consentimiento y suscripción; cada acceso queda en la bitácora. |
| PUT 🔒 | `/api/records` | Nueva. Paciente: `{birthDate, sex, bloodType, allergies[], chronicConditions[], medications[], notes}`. |
| POST 🔒 | `/api/consents` | Ampliada: valida que el doctor exista. `{doctorId, granted: true \| false}` otorga o revoca. |
| GET 🔒 | `/api/consents` | Nueva. Paciente: a quién le ha dado acceso. |
| POST 🔒 | `/api/records/documents` | Paciente: `{name, contentType, size}`. Responde con POST firmado para subir PDF/JPG/PNG/DICOM de hasta 10 MB; el POST directo a S3 vence en 5 minutos. |
| GET 🔒 | `/api/records/documents?patientId=` | Paciente lista sus documentos; profesional requiere `patientId`, suscripción y consentimiento. Responde URLs firmadas GET que vencen en 5 minutos. |
| DELETE 🔒 | `/api/records/documents/{documentId}` | Paciente elimina un documento propio de S3. |

## Flujo 3 · Suscripción y consulta

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST 🔒 | `/api/subscriptions/pay` | Nueva. Doctor: `{cardHolder, cardNumber, expMonth, expYear, cvv}` → periodo de 30 días ($20 USD); si paga por adelantado se encadena. Pago simulado: tarjeta aprobada `4242 4242 4242 4242`, rechazada `4000 0000 0000 0002` (402). |
| GET 🔒 | `/api/subscriptions` | Ampliada: mismos campos más `start`, `end` y `active`. |
| GET 🔒 | `/api/doctor/patients` | Nueva. Doctor con suscripción: pacientes que le dieron acceso. |
| POST 🔒 | `/api/consultations` | Ampliada: requiere suscripción y consentimiento, la cita debe ser del doctor y no futura. Marca la cita `COMPLETADA`, guarda consulta y receta en una transacción y la consulta aparece en el historial del paciente. |
| GET 🔒 | `/api/prescriptions/{id}` | Paciente propietario o profesional autorizado recupera los datos de la receta; la interfaz permite imprimirla o guardarla como PDF. |
| GET 🔒 | `/api/doctor/inventory` | Lista privada de insumos; requiere suscripción vigente. |
| POST 🔒 | `/api/doctor/inventory` | Guarda/actualiza por nombre: `{name, quantity, unit}`. Cantidad no negativa. |
| DELETE 🔒 | `/api/doctor/inventory/{id}` | Elimina sólo un insumo del propio perfil profesional. |
| GET 🔒 | `/api/doctor/promotions` | Promociones propias, activas o pasadas. |
| POST 🔒 | `/api/doctor/promotions` | `{title, description?, discountPercent, start, end}`; descuento 1–90%, fechas válidas. |
| DELETE 🔒 | `/api/doctor/promotions/{id}` | Retira una promoción propia. Sólo las vigentes se muestran públicamente; el descuento no se cobra automáticamente. |

## Mensajes y notificaciones

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET 🔒 | `/api/messages` | Lista conversaciones propias con conteo de mensajes sin leer. |
| GET 🔒 | `/api/messages/{userId}` | Lee la conversación y marca mensajes recibidos como leídos. Requiere cita o consentimiento activo entre paciente y profesional. |
| POST 🔒 | `/api/messages` | `{recipientId, content}` (máximo 2000 caracteres); verifica que exista una cita o consentimiento. |
| GET 🔒 | `/api/notifications` | Lista los avisos del usuario. Materializa avisos de cita en las próximas 24 h y vencimiento de suscripción en 7 días; deduplica por evento. |
| PUT 🔒 | `/api/notifications/{id}/read` | Marca un aviso propio como leído. |

Los avisos se muestran dentro de la aplicación. EventBridge genera recordatorios y vencimientos cada 15 minutos aunque el navegador esté cerrado; la bandeja también se actualiza con la sesión abierta. No existe correo/push. Las consultas SES probadas fueron denegadas, pero el permiso de envío no se evaluó. No se usa el topic SNS de otro servicio.

## Códigos de error

`400` dato inválido · `401` sin sesión · `402` sin suscripción o pago rechazado · `403` rol o consentimiento
insuficiente · `404` no existe (o no es tuyo) · `409` horario ocupado o cita en un estado que no lo permite.

## Frontend

Pestañas según el rol: búsqueda y agenda (todos), "Mis citas", "Mi expediente" y "Mensajes" (paciente), "Agenda", "Mi panel" y "Mensajes" (doctor/clínica: suscripción simulada, horario semanal, pacientes autorizados, inventario, promociones y registro de consultas).
En `localhost` usa `http://localhost:3000`; desplegado en S3 lee la URL de la API de `config.json`, que
publica `infrastructure/frontend_config.tf`. Después de recompilar, ejecuta `python infrastructure/publish_frontend.py`.
No reemplaces `terraform_data.frontend_bucket` para actualizar código: su provisioner de destrucción borra el bucket.

## Límites

- Pagos de suscripción y descuentos son demostrativos; no se cobran ni canjean automáticamente.
- Los avisos son in-app. La configuración y autorización para correo/push aún no están resueltas.
- El frontend de entrega usa HTTPS. La aplicación sigue siendo una demostración académica sin aprobación para uso clínico real.
