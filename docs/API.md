# API de MiDoc (ampliación de los flujos)

Esta rama amplía el backend y el frontend existentes para cubrir los 3 flujos prometidos en la fase 1.

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
| GET | `/api/doctors?specialty=&location=&q=` | Ampliada: filtros por ubicación y texto; solo profesionales con suscripción vigente. |
| GET | `/api/doctors/{id}` | Nueva. Perfil y horario semanal (`schedule`). |
| GET | `/api/doctors/{id}/availability?date=AAAA-MM-DD` | Nueva. Horarios libres de ese día (`slots`). |
| POST 🔒 | `/api/appointments` | Ampliada: `{doctorId, dateTime, reason?}`. El horario debe estar libre, en el futuro y dentro de 90 días; un índice único impide reservas simultáneas. |
| GET 🔒 | `/api/appointments?status=` | Ampliada: incluye nombres de doctor/paciente y filtro por estado. |
| GET 🔒 | `/api/appointments/{id}` | Nueva. Detalle (solo el paciente o el doctor de la cita). |
| PUT 🔒 | `/api/doctor/schedule` | Nueva. Doctor: `{blocks: [{day: 1-7, start: "09:00", end: "14:00"}]}` (1 = lunes). |

## Flujo 2 · Expediente y consentimiento

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET 🔒 | `/api/records` | Ampliada: mismos campos (`patient_id`, `allergies`, `notes`) más datos clínicos e historial de consultas. El doctor necesita consentimiento y suscripción; cada acceso queda en la bitácora. |
| PUT 🔒 | `/api/records` | Nueva. Paciente: `{birthDate, sex, bloodType, allergies[], chronicConditions[], medications[], notes}`. |
| POST 🔒 | `/api/consents` | Ampliada: valida que el doctor exista. `{doctorId, granted: true \| false}` otorga o revoca. |
| GET 🔒 | `/api/consents` | Nueva. Paciente: a quién le ha dado acceso. |

## Flujo 3 · Suscripción y consulta

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST 🔒 | `/api/subscriptions/pay` | Nueva. Doctor: `{cardHolder, cardNumber, expMonth, expYear, cvv}` → periodo de 30 días ($20 USD); si paga por adelantado se encadena. Pago simulado: tarjeta aprobada `4242 4242 4242 4242`, rechazada `4000 0000 0000 0002` (402). |
| GET 🔒 | `/api/subscriptions` | Ampliada: mismos campos más `start`, `end` y `active`. |
| GET 🔒 | `/api/doctor/patients` | Nueva. Doctor con suscripción: pacientes que le dieron acceso. |
| POST 🔒 | `/api/consultations` | Ampliada: requiere suscripción y consentimiento, la cita debe ser del doctor y no futura. Marca la cita `COMPLETADA`, guarda consulta y receta en una transacción y la consulta aparece en el historial del paciente. |

## Códigos de error

`400` dato inválido · `401` sin sesión · `402` sin suscripción o pago rechazado · `403` rol o consentimiento
insuficiente · `404` no existe (o no es tuyo) · `409` horario ocupado o cita en un estado que no lo permite.

## Frontend

Pestañas según el rol: búsqueda y agenda (todos), "Mis citas" y "Mi expediente" (paciente), "Agenda" y
"Mi panel" (doctor/clínica: suscripción, horario semanal, pacientes autorizados y registro de consultas).
En `localhost` usa `http://localhost:3000`; desplegado en S3 lee la URL de la API de `config.json`, que
publica `infrastructure/frontend_config.tf`. Después de recompilar el frontend hay que volver a publicarlo con
`terraform apply -replace=terraform_data.frontend_bucket`.

## Cambios en archivos existentes

Para facilitar el merge, lo nuevo vive en archivos nuevos (`backend/src/flujos.py`, `backend/src/reglas.py`,
`backend/test/test_flujos.py`, `backend/migrations/002_ampliacion_flujos.sql`,
`infrastructure/frontend_config.*` y los componentes de `frontend/src/app/`). En los existentes solo:

- `backend/src/app.py`: importa `flujos`; las rutas existentes conservan sus validaciones y delegan la parte
  ampliada; `handle` convierte errores de validación y de base de datos en 400/404/409 en lugar de 500; CORS
  admite `PUT`; la semilla completa los datos demo (nombres y horario de la doctora).
- `backend/src/local.py`: acepta `PUT` y el preflight `OPTIONS` del navegador.
- `backend/src/schema.sql`: al final, columnas y tablas nuevas con `ADD COLUMN IF NOT EXISTS` (idempotente).
- `backend/test/test_app.py`: `test_patient_can_book` agenda en un horario libre real; antes usaba una fecha fija
  (04:00 en Ciudad de México) que ahora se rechaza por estar fuera del horario y que además quedaría en el pasado.
- `frontend/src/app/app.component.*`, `main.ts`, `styles.css`: la pantalla de búsqueda pasa a su propio
  componente y se agregan las demás pestañas con la misma paleta.

## Pendiente (siguiente iteración)

- Estudios médicos en S3: subida con URL firmada, confirmación, descarga y borrado (requiere bucket privado y
  endpoint de S3 para la Lambda dentro de la VPC).
- Receta en PDF generada al registrar la consulta y descarga desde el historial.
- Confirmar y cancelar citas (doctor/paciente) y liberar el horario.
- Edición del perfil público del doctor.
