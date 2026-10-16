# Revisión integral de MiDoc

> Estado posterior a las pruebas: el usuario solicitó retirar el entorno AWS el 16/10/2026. Código y evidencia publicados en el commit cc315ec; el estado operativo descrito abajo es histórico. Ver [CIERRE-AWS.md](CIERRE-AWS.md).

Fecha: 16 de octubre de 2026. Alcance: los tres PDF originales, código, frontend, persistencia, Terraform y pruebas reales en AWS Academy Learner Lab. El video permanece pendiente por instrucción del usuario.

## Dictamen y evidencia

Los tres flujos centrales funcionan en AWS con PostgreSQL como fuente relacional y Lambda ejecutándose con el rol existente `LabRole`. Las correcciones de esta revisión están desplegadas. El frontend usa HTTPS sin necesitar CloudFront. Se completaron recordatorios automáticos con EventBridge y se observó una ejecución programada real en CloudWatch.

No se declara cumplimiento total ni aprobación para uso clínico real. La suscripción es simulada; no hay correo/push, auditoría manual WCAG completa, CD ni monitoreo final. Los cambios y las evidencias fueron publicados en GitHub (cc315ec). El video sigue pendiente.

| Evidencia reproducible | Resultado |
| --- | --- |
| `python -m unittest discover -s backend/test -v` | 36 pruebas aprobadas: negocio, validaciones, adaptadores, producción, transacciones y recordatorios. Local Python 3.14; CI configura 3.12. |
| Build Angular con Node 24.18.1 | Aprobado. CI actualizado a Node 24 porque Angular 22 no admite Node 20. |
| `docs/evidencia-aws-e2e.json` | Tres flujos completos, 43 peticiones API verificadas más consulta y receta desde Edge. Incluye resultados negativos esperados. |
| `docs/evidencia-browser.json` | Seis recorridos de interfaz, ocho vistas axe sin infracciones detectadas, sin errores JavaScript. Anchos 320/390 px comprobados. |
| `docs/evidencia-recordatorios.json` | Invocación automática EventBridge observada en CloudWatch; frecuencia original de 15 minutos restaurada. |
| DynamoDB | Dos eventos del primer paciente sintético comprobados mediante Query por partición. |
| RDS/Lambda | PostgreSQL 16.13 available, privado y cifrado; Lambda Python 3.12 Active/Successful con LabRole. |

## 1. Qué gobierna el alcance

| Documento | Requisitos y decisiones |
| --- | --- |
| Reporte de fase 1, pp. 1–2 | Registro gratuito paciente; búsqueda por especialidad/ubicación y perfil/disponibilidad; citas; expediente propio con consentimiento explícito; suscripción profesional de USD20/mes; consultas e historial. También propone seguimiento, agenda/recordatorios, recetas, inventario, promociones, mensajes y avisos. |
| Tarea 2, pp. 1–4 | RDS PostgreSQL y entidades relacionales; roles PACIENTE/DOCTOR/CLINICA. Secrets Manager y autenticación JWT propia sustituyen Cognito User Pools según la investigación del equipo. |
| Tarea 2, pp. 5–6 | DynamoDB opcional para auditoría; no reemplaza PostgreSQL. SES/SNS no son servicios exigidos por este documento. |
| Proyecto Integrador, p. 4 | Fase dos: mayoría de solución en AWS (objetivo >=80%), scripts reproducibles, documentación actualizada, participación de tres integrantes, video <=10 minutos y PDF <=4 páginas con repo/video, arquitectura, servicios, decisiones y tres flujos. |
| Proyecto Integrador, pp. 2, 5–6 | >=5 servicios y tres recorridos observables; CD preparado para el hito del 12 de noviembre y monitoreo final con cinco métricas, dos alarmas y dashboard. No se presentan como terminados hoy. |
| Instrucciones del usuario | Usar sólo IAM existente, mejorar UX/WCAG y dejar el video pendiente. Se preservaron los PDF originales. |

## 2. Matriz de aceptación

| Función | Estado y alcance real |
| --- | --- |
| Registro paciente, doctor y clínica/hospital | Implementado. Centros médicos usan CLINICA conforme a Tarea 2. Registro paciente probado desde Edge y profesional por API. |
| Búsqueda, perfil y disponibilidad | Implementado y probado en nube/interfaz. Profesionales sin suscripción no son visibles. |
| Reserva, confirmación, cancelación y reprogramación | Implementado. API valida roles, horarios, estados y conflictos; reprogramación/cancelación también probadas desde Edge. Agenda en tabla accesible, sin calendario mensual. |
| Expediente editable | Implementado y persistente en RDS. Guardado probado desde API y navegador. |
| Consentimiento y revocación | Implementado. Acceso profesional exige suscripción y consentimiento vigente; revocar devuelve 403 en nube. No elimina mensajes previos. |
| Documentos privados | S3 separado con bloqueo público/cifrado y POST/GET firmados por 300 segundos. PDF sintético probado por API; DICOM con MIME genérico cargado/eliminado desde Edge HTTPS y CORS. |
| Suscripción USD20 | Parcial por diseño demo: tarjeta de prueba aprobada/rechazada y vigencia de 30 días, sin cobro real. |
| Consulta, diagnóstico/tratamiento/notas, receta e historial | Implementado y probado en RDS con cita cuya hora real ya comenzó. Consulta e impresión de receta verificadas también desde Edge. Repetir consulta devuelve 409. |
| Inventario | Altas/actualización por nombre, cantidades/unidades y eliminación; probado en AWS. |
| Promociones | Publicar con vigencia/descuento, mostrar perfil y retirar; probado en AWS. Sin canje/cobro automático. |
| Mensajería | Relación por cita o consentimiento, persistencia y aviso interno; probado en AWS. Revocar consentimiento clínico no cancela la relación por citas previas. |
| Avisos | Citas/estados/reprogramación, mensajes y recetas en bandeja, con lectura y deduplicación. |
| Recordatorios y vencimientos | Generación automática cada 15 minutos en EventBridge, independiente del navegador; consulta de bandeja al abrir MiDoc. Sin entrega email/push. |
| Seguridad del transporte | Web mediante endpoint REST S3 HTTPS /index.html; API HTTPS; archivos firmados HTTPS; PostgreSQL sslmode=require. Falta verify-full con CA. |
| >=5 servicios | Lambda, API Gateway, RDS, S3, Secrets Manager y DynamoDB usados; EventBridge añade ejecución periódica. Logs en CloudWatch. |
| >=80% en nube | Web, API, persistencia, objetos, secretos, auditoría y trabajo periódico están en AWS. Compilación/Terraform/pruebas son locales; no se inventa un porcentaje exacto sin denominador de aceptación. |
| Reporte y equipo | PDF de cuatro páginas; historial Git de tres integrantes. Falta publicar estos cambios en Git y el video pedido queda pendiente. |

## 3. Defectos corregidos y desplegados

- Operaciones de citas, consulta y mensajes podían persistir y después responder 500 al fallar su notificación. Ahora negocio y avisos comparten una conexión/transacción PostgreSQL; fallar el aviso revierte ambos. Pruebas inyectan fallos en memoria y comprueban commit/rollback del adaptador PostgreSQL. La falla inducida no se ejecutó contra datos AWS.
- Se serializan escrituras por actor en PostgreSQL para evitar periodos de suscripción calculados simultáneamente por el mismo usuario. Restricciones de horario y estado protegen las reservas/consultas repetidas. Mensajes/pagos no tienen todavía una clave idempotente del cliente para reintentos tras una pérdida de respuesta de red.
- La semilla ya no inserta una suscripción nueva en cada cold start; inicialización serializada e INSERT sólo si no existe periodo. No se eliminaron duplicados históricos. No se ejecutó una campaña dedicada de cold starts concurrentes.
- Producción sin RDS falla de forma explícita; no usa memoria. JWT en producción exige Secrets Manager y no acepta sustitución mediante JWT_SECRET de entorno.
- Conexión PostgreSQL exige TLS. Login normaliza correo igual que registro. JSON/base64 inválidos devuelven 400; servidor local soporta DELETE.
- El frontend limpia datos del paciente anterior, comparte la lista correcta de documentos y reconoce DICOM con MIME vacío/genérico por extensión permitida.
- Confirmación visible después de reprogramar; botones de cambio sólo antes del inicio; formulario de consulta deshabilitado si es inválido.
- Se corrigió el desbordamiento móvil del selector de archivos. Formularios/datos clínicos se adaptan a 320 px; tablas conservan desplazamiento interno.
- Se evita editar expediente y panel antes de cargar los datos: la respuesta inicial ya no reemplaza notas/horarios escritos durante la espera. Si falla la carga se ofrece reintento. Se comprueba el texto de notas devuelto por RDS y su persistencia al recargar desde Edge.
- Publicación segura mediante `infrastructure/publish_frontend.py`: sincroniza browser/, preserva config y evita reemplazar el bucket. El provisioner de destrucción del bucket público sigue siendo destructivo y no debe usarse para publicar cambios.
- HTTPS del frontend resuelto mediante S3 REST. CORS médico incluye su origen HTTPS. No fue necesario crear una distribución CloudFront.
- EventBridge genera recordatorios con permiso de invocación limitado a la regla; conserva LabRole. Se probó temporalmente a un minuto y se restauró a quince.

## 4. Riesgos y trabajo pendiente priorizado

1. Publicar cambios revisables en Git para alinear el repositorio con AWS. El video sigue pendiente por decisión del usuario; no se inventa URL.
2. Formalizar migraciones versionadas: schema.sql se ejecuta durante inicialización con credenciales maestras administradas; migraciones históricas 001/002 no describen todas las ampliaciones. Separar migración/ejecución y probar restauración y clon limpio.
3. Completar idempotencia del cliente y pruebas de concurrencia/errores de red. La transacción evita fallos parciales, pero no impide repetir un mensaje/pago si se pierde la respuesta después de commit. Reprogramaciones simultáneas de distintos actores requieren una política explícita de reconfirmación/versiones.
4. Correo/push no implementado. Requiere identidad remitente o suscripciones confirmadas y verificación de permisos de envío. No publicar en RedshiftSNS ni enviar a direcciones de terceros.
5. WCAG: axe y teclado básico no certifican conformidad. Falta lector de pantalla, revisión manual del foco/errores y zoom completo.
6. Seguridad/operación: limitar login, rotación probada de JWT, certificados PostgreSQL verify-full, política de cuentas demo, paginación S3, validación real de contenido/antimalware, backup/restore y disponibilidad bajo carga.
7. RDS no es Multi-AZ; skip_final_snapshot=true y estado Terraform local requieren protección. La sesión Learner Lab y el presupuesto limitan disponibilidad. El entorno se retiró por instrucción posterior del usuario; ver CIERRE-AWS.md.
8. CD y monitoreo completo corresponden a hitos posteriores. CI está configurado y el push cc315ec fue publicado; su resultado remoto debe consultarse en GitHub Actions.

Revocar consentimiento bloquea nuevas URLs/lecturas; una URL S3 ya firmada puede durar hasta 300 segundos. Es un límite que debe conservarse en la aceptación. La receta imprimible es de demostración, sin validación legal clínica.

## 5. Permisos: conclusiones acotadas

Se observaron AccessDenied de cloudfront:ListDistributions/GetDistribution, ses:GetAccount/ListEmailIdentities y lectura de políticas IAM. No prueban denegación de CreateDistribution, SendEmail o todas las acciones SNS. Tarea 2 documenta la elección de no utilizar User Pools. No se crearon roles, no se modificó LabRole ni se reutilizó RedshiftSNS. Lambda sí recibió el permiso del recurso limitado a EventBridge, del mismo modo que API Gateway ya tenía su permiso de invocación.

La aprobación automática rechazó inicialmente un apply por interpretar que borraría el frontend. Se comprobó el JSON del plan y se aplicó uno acotado: únicamente reconstrucción/configuración local y actualización Lambda; ningún bucket ni RDS fue eliminado. El despliegue posterior de EventBridge también fue aprobado. No queda bloqueado por esa revisión ningún cambio descrito como desplegado.

## 6. Reproducir las verificaciones

```powershell
python -m unittest discover -s backend/test -v
npm run build --prefix frontend
terraform -chdir=infrastructure fmt -check -recursive
terraform -chdir=infrastructure validate
python backend/test/smoke_aws.py --api-url https://4otc5sejki.execute-api.us-east-1.amazonaws.com --report docs/evidencia-aws-e2e.json --browser
python backend/test/smoke_browser.py
python backend/test/smoke_reminders.py
python reporte/generar_entrega.py
```

Las pruebas smoke son explícitas, crean cuentas sintéticas y hacen escrituras reales. Playwright se instaló sólo en una carpeta temporal y usa Edge instalado; no es dependencia Lambda. Se eliminan archivos, insumos y promociones de prueba, se cancela la cita auxiliar, se revoca el acceso al final y se vacía el horario del profesional sintético. Las cuentas, historial y mensajes sintéticos permanecen identificados como E2E DEMO. La prueba del navegador crea pacientes ficticios adicionales; no usa datos médicos reales ni imprime tokens.

La rúbrica asigna 70 puntos al video, 20 al repositorio y 10 al PDF: dejar el video pendiente impide declarar entrega académica completa, aunque los recorridos técnicos estén verificados.
