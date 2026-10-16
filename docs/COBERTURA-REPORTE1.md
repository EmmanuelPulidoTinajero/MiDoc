# Cobertura funcional del Reporte de fase 1

Revisión del Reporte de fase 1 contra MiDoc. Las ampliaciones se desplegaron el 16 de octubre de 2026 con pruebas sintéticas de los tres flujos. Consultar la [revisión integral](REVISION-INTEGRAL.md) para defectos, correcciones desplegadas y evidencia. Correo SES/SNS no está implementado; las denegaciones de consultas no demuestran por sí solas que el envío esté prohibido.

## Flujos principales

| Requisito del reporte | Cobertura | Evidencia funcional |
| --- | --- | --- |
| Pacientes se registran gratis | Implementado | Registro y acceso con rol paciente. |
| Buscar doctor, consultorio, clínica u hospital por especialidad/ubicación | Implementado | Los establecimientos se representan como perfil `CLINICA`, conforme a Tarea 2; búsqueda por especialidad, ciudad/ubicación y texto. |
| Revisar perfil y disponibilidad | Implementado | Perfil público, horario semanal y consulta de espacios disponibles. |
| Agendar cita | Implementado | Validación de rol, suscripción del proveedor, horario, fecha y concurrencia. |
| Paciente crea/actualiza expediente | Implementado | Datos de salud relacionales y documentos privados en S3. |
| Otorgar y revocar consentimiento explícito | Implementado | Revalidado por servidor al leer expediente/archivos/receta; auditoría en RDS y evento complementario en DynamoDB. |
| Profesionales pagan $20 USD mensuales | Parcial | Suscripción y vigencia funcionales con tarjetas de prueba; no procesa pagos reales. |
| Profesional ve pacientes autorizados | Implementado | Panel condicionado a suscripción y consentimiento. |
| Registrar diagnóstico, tratamiento y notas | Implementado | Consulta ligada a una cita y al paciente. |
| Historial y seguimiento clínico | Implementado | Historial de consultas y recetas aparece en el expediente del paciente. |

## Funcionalidades adicionales propuestas en el mismo Reporte 1

| Función | Cobertura | Límites actuales |
| --- | --- | --- |
| Agenda del consultorio, confirmaciones y reprogramación | Implementado | Confirmación, cancelación y reprogramación probadas en AWS; reprogramar valida disponibilidad y avisa a ambas partes. La vista es una agenda accesible en tabla, no un calendario mensual visual. |
| Recordatorios de citas | Avisos internos automáticos | EventBridge ejecuta Lambda cada 15 minutos para generar avisos de las próximas 24 horas sin navegador abierto. No hay correo/push. |
| Receta digital y consulta | Implementado | Receta relacional ligada a la consulta; impresión/guardado PDF desde el navegador. |
| Inventario de insumos/medicamentos | Implementado y probado en AWS | Altas/actualización de existencias por nombre, unidad y cantidad; prueba eliminada al concluir. Acceso sólo del consultorio suscrito. |
| Promociones/descuentos del marketplace | Implementado y probado en AWS | Publicación, exposición pública durante fechas, descuento y retiro; la prueba se eliminó al concluir. El canje no es automático. |
| Mensajes de paciente/profesional | Implementado y probado en AWS | Conversación limitada a personas con cita o consentimiento; PostgreSQL y aviso interno. Mensaje sintético de prueba sin datos clínicos. |
| Avisos de nuevas citas, cambios, mensajes, recetas y vencimiento de suscripción | Parcial, probado en AWS | Bandeja in-app con lectura/no lectura, deduplicación y recordatorios programados EventBridge. No hay email/push; los avisos se consultan al abrir MiDoc. |

## SNS/SES y envío a correo

Tarea 2 no exige SES ni SNS. Su propuesta opcional menciona DynamoDB para mensajes/notificaciones, pero deja el servicio como posible ampliación; la prioridad explícita es RDS PostgreSQL y Secrets Manager. En la sesión Learner Lab, IAM devuelve `AccessDenied` para `ses:GetAccount` y `ses:ListEmailIdentities`. SNS sólo muestra el topic preexistente `RedshiftSNS`, que pertenece a otro uso y no se reutiliza. Por eso esta versión guarda conversaciones y notificaciones en PostgreSQL y no intenta enviar correos. Para activar correo hace falta una identidad remitente verificada y permiso de envío SES, o un topic SNS dedicado y confirmado para esta aplicación.

## Accesibilidad y experiencia

Se implementaron etiquetas enlazadas a controles, orden de encabezados, navegación por secciones, enlace para saltar al contenido, foco visible, destino de foco al cambiar de sección, mensajes de estado anunciables, tablas con encabezados/caption y desplazamiento horizontal en móvil, blancos táctiles amplios y respeto a `prefers-reduced-motion`. Estos patrones se contrastaron con WCAG 2.2 AA; no se declara conformidad formal: ocho vistas pasaron axe sin infracciones detectadas; se probó salto por teclado y ancho de 320/390 px. Falta lector de pantalla y auditoría manual completa.

Referencia: [WCAG 2.2, W3C](https://www.w3.org/TR/WCAG22/) y [novedades de WCAG 2.2](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/).

## Bloqueos para cumplimiento completo

- HTTPS resuelto con el endpoint REST público S3 /index.html, probado con Edge y cargas privadas CORS. No supone aprobación para uso clínico real.
- Cobros reales requieren proveedor de pagos, credenciales y revisión de cumplimiento; por ahora la suscripción es una simulación.
- El correo requiere los permisos e identidades SES/SNS indicados arriba.
- Recordatorios programados EventBridge desplegados sin crear roles IAM; correo/push permanecen pendientes.
- Los flujos integrales nuevos pasaron con datos sintéticos; queda pendiente una auditoría de accesibilidad asistiva.
