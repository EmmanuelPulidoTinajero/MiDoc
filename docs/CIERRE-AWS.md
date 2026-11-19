# Cierre, Remediación y Validación AWS de MiDoc

Este documento separa claramente:
1. El **cierre histórico de Fase 2 (16/10/2026)** y las evidencias preservadas de aquel despliegue.
2. Las **remediaciones implementadas en código e infraestructura (Hitos M1–M4)** para resolver los hallazgos de teardown, pagos, observabilidad, PDFs, frontend y CI/CD.
3. La **lista de verificación de Entrega Final / Fase 3 (Hito M5)**, actualmente **pendiente de ejecución en vivo** sobre la cuenta AWS configurada.

---

## Sección 1 — Cierre histórico de Fase 2 (16/10/2026)

El 16 de octubre de 2026 (commit `cc315ec`, cuenta AWS `647018795197`, región `us-east-1`, proyecto `midoc`) se ejecutó la validación de Fase 2 y posteriormente se solicitó el retiro del entorno de laboratorio.

### Endpoints e infraestructura históricos (retirados)
- **API Gateway histórico (retirado):** `https://4otc5sejki.execute-api.us-east-1.amazonaws.com`
- **Frontend S3 REST histórico (retirado):** `https://midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html`
- **Instancia RDS histórica (retirada):** `midoc-20261016130331567100000009` (PostgreSQL 16.13, `PubliclyAccessible=false`, `StorageEncrypted=true`).

### Evidencia JSON preservada de Fase 2

| Archivo de evidencia | Fecha (UTC) | Resultado | Métricas verificadas |
| --- | --- | --- | --- |
| [evidencia-aws-e2e.json](evidencia-aws-e2e.json) | `2026-10-16T14:29:24Z` | `PASS` | **43 peticiones HTTP** verificadas en los 3 flujos E2E (`cloudFlows: [1, 2, 3]`), incluyendo pruebas negativas (`402`, `403`, `409`), datos sintéticos y consulta desde navegador |
| [evidencia-browser.json](evidencia-browser.json) | `2026-10-16T14:35:18Z` | `PASS` | Microsoft Edge headless / Playwright: **6 recorridos**, **8 vistas axe** con **205 verificaciones aprobadas y 0 infracciones**, `pageErrors: []`, anchos 320 px / 390 px |
| [evidencia-recordatorios.json](evidencia-recordatorios.json) | `2026-10-16T14:29:13Z` | `PASS` | Regla EventBridge `midoc-reminders` restaurada a `rate(15 minutes)`; invocación automática registrada con `processedUsers: 2`, `status: "ok"` |
| [evidencia-destruccion-aws.json](evidencia-destruccion-aws.json) | `2026-10-16T14:46:41Z` | `PENDING` | Teardown parcial: 0 recursos en Lambda, API GW, RDS, snapshots, DynamoDB, S3, Secrets, Logs, EventBridge y VPC Endpoints; permanecieron **1 Security Group (`sg-0cc5831717592d5d5`)** y **2 interfaces ENI (`eni-0f32fe5530ecb6079`, `eni-04a4b2526c34ab64b`)**; `LabRole` preservado |

> **Nota histórica sobre `evidencia-aws-e2e.json`:** Dicha evidencia de Fase 2 probó el antiguo endpoint simulado de tarjetas antes de su retiro definitivo y sustitución por Stripe Checkout en Fase 3.

---

## Sección 2 — Remediaciones implementadas en Hitos M1–M4

Para garantizar un despliegue y `terraform destroy` completamente limpios y trazables en Fase 3, se aplicaron las siguientes correcciones en el repositorio:

1. **Limpieza de estado Terraform obsoleto y Security Groups huérfanos (M1):**
   - Se limpió el bloqueo huérfano del estado anterior (`011e1a33-38cd-fd0c-cc85-d617b336e327`, del 16/10/2026) y la entrada huérfana de `aws_security_group.lambda`, confirmando 0 Security Groups residuales del proyecto antes de M5.
2. **Ciclo de destrucción automático y completo de buckets S3 y secretos (M1):**
   - `infrastructure/main.tf` y `infrastructure/s3_medical.py` ahora configuran `when = destroy` en `terraform_data.medical_documents_bucket` controlado por `var.delete_medical_bucket_on_destroy` (por defecto `true`), vaciando cargas multiparte, versiones y marcadores de borrado antes de eliminar el bucket privado.
   - Tanto `aws_secretsmanager_secret.application` como `aws_secretsmanager_secret.stripe` usan `recovery_window_in_days = 0` para permitir destrucción inmediata sin bloqueos de ventana de recuperación de 7–30 días.
3. **Verificador dinámico de destrucción total (`infrastructure/verify_teardown.py`, M1):**
   - Se actualizó para consultar dinámicamente **21 categorías de recursos** (`lambda`, `apiGateway`, `rds`, `snapshots`, `dbSubnetGroups`, `dynamodb`, `s3`, `secrets`, `eventbridge`, `logs`, `alarms`, `dashboards`, `queryDefinitions`, `sns`, `securityGroups`, `subnets`, `routeTables`, `natGateways`, `eips`, `vpcEndpoints`, `networkInterfaces`), verificar el estado de `terraform.tfstate` (`terraformManagedResources`) y confirmar la preservación de `LabRole` (`preservedRole`). Emite `result: "PASS"` (código de salida `0`) únicamente cuando las 21 categorías y los recursos gestionados quedan vacíos.
4. **Cierre funcional y técnico de Fase 3 (M1–M4):**
   - **Pagos reales con Stripe** (`backend/src/pagos_stripe.py`, NAT Gateway y subredes privadas `172.31.96.0/20`, `172.31.112.0/20`, Secrets Manager `midoc-stripe-*`, retiro `410 Gone` del pago simulado). Ver [PAGOS-STRIPE.md](PAGOS-STRIPE.md).
   - **Observabilidad y CI/CD completos** (12 métricas EMF, 10 alarmas, SNS `${project}-alerts`, 2 Log Groups con retención 14 días, API GW access logs, dashboard `midoc-estado`, 4 Logs Insights queries, `.github/workflows/ci.yml` + `.github/workflows/cd.yml`). Ver [OBSERVABILIDAD-Y-CICD.md](OBSERVABILIDAD-Y-CICD.md).
   - **Recetas PDF reales en S3** (`backend/src/pdf_receta.py`), migraciones `001`–`004`, límite `429` en login, `Idempotency-Key`, `ALLOW_DEMO_SEED=false` en producción, `PUT /api/me`, `POST /api/auth/refresh`, `GET /api/records/access-log`.
   - **Design System desde cero y enrutamiento S3-safe** (`design/system.md`, `_tokens.css`, 9 componentes en `frontend/src/app/ds/`, `HashLocationStrategy`, `frontend/e2e/`).
   - **Trazabilidad documental y cierre de enlaces** ([EVALUACION-INTEGRAL.md](EVALUACION-INTEGRAL.md), [PAGOS-STRIPE.md](PAGOS-STRIPE.md), [OBSERVABILIDAD-Y-CICD.md](OBSERVABILIDAD-Y-CICD.md) y actualización de `README.md`, [API.md](API.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DEPLOYMENT.md](DEPLOYMENT.md) y [REVISION-INTEGRAL.md](REVISION-INTEGRAL.md)).

---

## Sección 3 — Entrega Final / Fase 3 (Pendiente de ejecución en Hito M5)

La ejecución en vivo contra AWS Academy Learner Lab y la destrucción posterior pertenecen al **Hito M5**. Al concluir M5, esta sección deberá poblarse únicamente con las salidas reales observadas en AWS:

- [ ] **Despliegue Terraform en vivo (`terraform apply`):**
  - Cuenta y región verificadas (`aws sts get-caller-identity`).
  - Salidas reales registradas (`api_url`, `frontend_url`, `database_endpoint`, `medical_documents_bucket`, `stripe_secret_arn`, `dashboard_name`, `alerts_topic_arn`, `log_groups`).
- [ ] **Validación E2E en nube (100%):**
  - `python tests/e2e/run_e2e.py --mode live --target cloud --stripe-mode live_cloud --with-browser --tier all` (197 casos en los 4 niveles contra la nube real + Stripe modo prueba `sk_test_`).
  - `frontend/e2e` (Playwright desktop + mobile contra despliegue o verificación de interfaz) y `backend/test/smoke_reminders.py` (invocación EventBridge `midoc.reminders`).
- [ ] **Verificación en vivo de CloudWatch y GitHub Actions:**
  - Consulta real de métricas en namespace `MiDoc`, eventos en `/aws/lambda/midoc-api` y `/aws/apigateway/midoc-http-api`, estado de las 10 alarmas y ejecución en GitHub Actions (`gh workflow list` / `gh run list`).
- [ ] **Destrucción total (`terraform destroy`) y prueba de cero remanentes:**
  - Ejecución de `terraform -chdir=infrastructure destroy -var-file=terraform.tfvars -auto-approve`.
  - Ejecución de `python infrastructure/verify_teardown.py --report docs/evidencia-destruccion-aws.json` confirmando `result: "PASS"`, `terraformManagedResources: []` y las 21 claves en `remaining` vacías (`[]`), conservando únicamente `LabRole`.
  - Actualización de los JSON de evidencia (`docs/evidencia-aws-e2e.json`, `docs/evidencia-browser.json`, `docs/evidencia-recordatorios.json`, `docs/evidencia-destruccion-aws.json`) con marcas de tiempo reales de M5.
