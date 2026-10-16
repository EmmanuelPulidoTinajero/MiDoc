# Verificación real de fase dos

Fecha: 16/10/2026. Entorno: us-east-1, AWS Academy Learner Lab. Sólo cuentas/datos sintéticos.

## Evidencia actual

- [Prueba de los tres flujos](evidencia-aws-e2e.json): 43 peticiones API verificadas más registro de consulta y apertura de receta en Edge. Incluye pago aprobado/rechazado, conflictos, roles, reserva/confirmación/reprogramación/cancelación, expediente, autorización/revocación, S3 privado, inventario, promociones, mensajes y consulta/historial/receta.
- [Prueba de interfaces](evidencia-browser.json): seis recorridos, ocho vistas axe sin infracciones detectadas, sin errores JS y anchos de 320/390px comprobados. Incluye registro, reprogramación con éxito visible, expediente y DICOM con MIME genérico cargado por HTTPS/CORS.
- [Recordatorios programados](evidencia-recordatorios.json): invocación automática real observada en CloudWatch, sin navegador. Regla restaurada a rate(15 minutes).
- 36 pruebas locales aprobadas, build Angular aprobado y Terraform fmt/validate correctos.
- RDS PostgreSQL16.13 available, privado/cifrado. Lambda Python3.12 Active/Successful con LabRole. DynamoDB Query confirmó dos eventos del primer paciente sintético.

Frontend: https://midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html

API: https://4otc5sejki.execute-api.us-east-1.amazonaws.com

El frontend se sirve por el endpoint REST HTTPS de S3. El endpoint antiguo website HTTP no se usa como URL de entrega. CORS del bucket privado admite el origen HTTPS. Las URLs clínicas firmadas duran300segundos.

## Límites

Suscripciones sin cobros reales; sin correo/push; sin certificación WCAG manual completa. Las pruebas smoke generan datos E2E DEMO persistentes y eliminan objetos/insumos/promociones temporales. No se indujeron fallos de infraestructura en AWS. La reversión ante fallo de aviso se probó mediante regresiones locales del repositorio y de commit/rollback del adaptador SQL.

El video queda pendiente por instrucción del usuario. Los recursos permanecen activos y consumen presupuesto. Ver [revisión integral](REVISION-INTEGRAL.md) para requisitos, correcciones y pendientes reales.
