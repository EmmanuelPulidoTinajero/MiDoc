# Observabilidad en CloudWatch y Automatización CI/CD

**Requisitos cubiertos:** `R5`, `REQ-F3-02`, `REQ-F3-03`, `REQ-F2-17`.  
**Archivos de código e infraestructura:** `backend/src/metricas.py`, `backend/src/lambda_function.py`, `backend/src/app.py`, `infrastructure/lambda.tf`, `infrastructure/monitoring.tf`, `infrastructure/reminders.tf`, `backend/test/test_metricas.py`, `backend/test/test_monitoreo.py`, `.github/workflows/ci.yml`, `.github/workflows/cd.yml`.

---

## 1. Observabilidad en AWS CloudWatch y SNS

La instrumentación de MiDoc supera el mínimo de la rúbrica (5 métricas, 2 alarmas, 1 dashboard) cubriendo aplicación HTTP, trabajos programados EventBridge, pagos Stripe, S3, DynamoDB, API Gateway HTTP v2, Lambda y RDS PostgreSQL.

### 1.1 Logs estructurados JSON con redacción automática (`backend/src/metricas.py`)

- **Flujos separados (`stdout` vs `stderr`):**
  - Las métricas EMF se imprimen como JSON de una sola línea en `stdout` para que CloudWatch Logs las extraiga de forma automática sin requerir el permiso IAM `cloudwatch:PutMetricData` sobre `LabRole`.
  - Los logs de aplicación utilizan la jerarquía de loggers `"midoc"` (`midoc.app`, `midoc.metricas`, `midoc.http`) con `propagate = False` escribiendo en `stderr` mediante `JsonLogFormatter` (`backend/src/metricas.py:89-150`), activo automáticamente cuando `NODE_ENV=production` (`backend/src/lambda_function.py:14-20`).
- **Campos emitidos:** `timestamp` (UTC ISO 8601), `level`, `message`, `requestId`, `route`, `method`, `status`, `durationMs`, `userRole`, `event`, `job`, además de `error` y `traceback` cuando existe excepción.
- **Redacción recursiva de secretos y PII (`redactar`):** Antes de serializar cualquier entrada o traceback, `JsonLogFormatter` enmascara:
  - Claves sensibles (`password`, `currentpassword`, `newpassword`, `password_hash`, `secret`, `stripe_secret_key`, `stripe_webhook_secret`, `jwt_secret`, `authorization`, y cualquier clave que contenga `"password"`) -> `"[REDACTED]"`.
  - Tokens `Bearer ...` -> `Bearer [REDACTED]`.
  - Llaves Stripe (`sk_*`, `pk_*`, `whsec_*`) -> `[REDACTED_STRIPE_KEY]`.
  - Correos electrónicos -> `[REDACTED_EMAIL]`.

### 1.2 Grupos de Logs explícitos y Access Logs de API Gateway (`infrastructure/lambda.tf`)

| Recurso Terraform | Nombre del Log Group | Retención | Contenido |
| --- | --- | --- | --- |
| `aws_cloudwatch_log_group.lambda_api` | `/aws/lambda/${var.project_name}-api` | `14` días | Logs JSON estructurados (`stderr`) y métricas EMF (`stdout`) de `midoc-api` |
| `aws_cloudwatch_log_group.apigw_http` | `/aws/apigateway/${var.project_name}-http-api` | `14` días | Logs JSON de acceso de API Gateway HTTP v2 (13 campos) |

El bloque `access_log_settings` de `aws_apigatewayv2_stage.default` (habilitado por `var.enable_monitoring`) registra: `requestId`, `sourceIp`, `requestTime`, `protocol`, `httpMethod`, `routeKey`, `path`, `status`, `responseLength`, `integrationStatus`, `integrationLatency`, `responseLatency` e `integrationErrorMessage`.

### 1.3 Catálogo completo de métricas EMF (12 métricas en namespace `MiDoc`)

Todas las métricas comparten la dimensión `Service = "midoc-api"` (`Dimensions = [["Service"]]`) y se emiten cuando `METRICS_ENABLED=true`:

| # | Métrica | Unidad | Grupo | Cuándo se emite |
| --- | --- | --- | --- | --- |
| 1 | `RequestLatencyMs` | `Milliseconds` | Core (`UNIDADES`) | Cada petición HTTP atendida por `app.handler` |
| 2 | `ServerErrors` | `Count` | Core (`UNIDADES`) | Valor `1` cuando HTTP `status >= 500`, `0` en caso contrario |
| 3 | `AppointmentsCreated` | `Count` | Core (`UNIDADES`) | `POST /api/appointments` con respuesta `201` |
| 4 | `ConsultationsRegistered` | `Count` | Core (`UNIDADES`) | `POST /api/consultations` con respuesta `201` |
| 5 | `LoginFailures` | `Count` | Core (`UNIDADES`) | `POST /api/auth/login` con respuesta `401` |
| 6 | `RemindersJobRuns` | `Count` | Eventos (`UNIDADES_EVENTOS`) | Cada ejecución de EventBridge `midoc.reminders` (`lambda_function.py:25`) |
| 7 | `RemindersJobErrors` | `Count` | Eventos (`UNIDADES_EVENTOS`) | Error en ejecución de `flujos.generar_recordatorios` (`lambda_function.py:29`) |
| 8 | `PaymentCheckoutCreated` | `Count` | Eventos (`UNIDADES_EVENTOS`) | `POST /api/subscriptions/checkout` con respuesta `201` |
| 9 | `PaymentSucceeded` | `Count` | Eventos (`UNIDADES_EVENTOS`) | Activación efectiva (`activada == True`) en `/api/subscriptions/confirm` o `/api/webhooks/stripe` |
| 10 | `PaymentFailed` | `Count` | Eventos (`UNIDADES_EVENTOS`) | Respuesta `>= 400` (`!= 401`) en checkout/confirm/webhook o evento Stripe `checkout.session.expired` / `payment_intent.payment_failed` |
| 11 | `DocumentOpsErrors` | `Count` | Eventos (`UNIDADES_EVENTOS`) | Error S3 al generar carga, listar, borrar o subir/firmar PDFs (`servicios_aws.py`) |
| 12 | `DynamoAuditErrors` | `Count` | Eventos (`UNIDADES_EVENTOS`) | Falla no bloqueante al escribir o consultar auditoría en DynamoDB (`app.py:119`, `flujos.py:1434`) |

### 1.4 Tópico SNS y las 10 alarmas de CloudWatch (`infrastructure/monitoring.tf`)

- **Tópico SNS:** `aws_sns_topic.alerts` (`${var.project_name}-alerts`, por defecto `midoc-alerts`), creado si `var.enable_monitoring = true`.
- **Suscripción opcional por correo:** `aws_sns_topic_subscription.alerts_email` (`protocol = "email"`) se crea únicamente si `var.alert_email != ""` (requiere confirmar el correo de suscripción AWS SNS). Nunca se reutiliza `RedshiftSNS`.
- **Política común de alarmas:** Todas configuran `treat_missing_data = "notBreaching"` y enlazan tanto `alarm_actions` como `ok_actions` a `aws_sns_topic.alerts[0].arn`.

| # | Recurso Terraform | Nombre de alarma | Namespace | Métrica y dimensión | Estadística | Periodo / Eval. | Umbral | Condición |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `errores_servidor` | `${project}-api-errores-5xx` | `MiDoc` | `ServerErrors` (`Service=midoc-api`) | `Sum` | `300s` / `1` | `> 5` | `enable_monitoring` |
| 2 | `latencia_p95` | `${project}-api-latencia-p95` | `MiDoc` | `RequestLatencyMs` (`Service=midoc-api`) | `p95` | `300s` / `2` | `> 3000` ms | `enable_monitoring` |
| 3 | `reminders_errors` | `${project}-reminders-errors` | `MiDoc` | `RemindersJobErrors` (`Service=midoc-api`) | `Sum` | `900s` / `1` | `> 0` | `enable_monitoring` |
| 4 | `payment_failed` | `${project}-payment-failed` | `MiDoc` | `PaymentFailed` (`Service=midoc-api`) | `Sum` | `300s` / `1` | `> 3` | `enable_monitoring` |
| 5 | `lambda_errors` | `${project}-lambda-errors` | `AWS/Lambda` | `Errors` (`FunctionName=${project}-api`) | `Sum` | `300s` / `1` | `> 0` | `enable_monitoring` |
| 6 | `lambda_throttles` | `${project}-lambda-throttles` | `AWS/Lambda` | `Throttles` (`FunctionName=${project}-api`) | `Sum` | `300s` / `1` | `> 0` | `enable_monitoring` |
| 7 | `apigw_5xx` | `${project}-apigw-5xx` | `AWS/ApiGateway` | `5xx` (`ApiId=...`) | `Sum` | `300s` / `1` | `> 5` | `enable_monitoring` |
| 8 | `rds_cpu` | `${project}-rds-cpu` | `AWS/RDS` | `CPUUtilization` (`DBInstanceIdentifier`) | `Average` | `300s` / `2` | `> 80` % | `enable_monitoring && enable_rds` |
| 9 | `rds_storage` | `${project}-rds-storage` | `AWS/RDS` | `FreeStorageSpace` (`DBInstanceIdentifier`) | `Average` | `300s` / `1` | `< 2147483648` (2 GiB) | `enable_monitoring && enable_rds` |
| 10 | `rds_connections` | `${project}-rds-connections` | `AWS/RDS` | `DatabaseConnections` (`DBInstanceIdentifier`) | `Average` | `300s` / `2` | `> 45` | `enable_monitoring && enable_rds` |

### 1.5 Dashboard `midoc-estado` y 4 consultas de Logs Insights (`infrastructure/monitoring.tf`)

- **Dashboard (`aws_cloudwatch_dashboard.estado`, nombre `${var.project_name}-estado`):** Incluye 7 widgets (6 si `enable_rds = false`):
  1. Estado consolidado de las 10 alarmas (o 7 sin RDS).
  2. Uso clínico (`AppointmentsCreated`, `ConsultationsRegistered`, `LoginFailures`).
  3. Pagos Stripe, recordatorios y resiliencia (`PaymentCheckoutCreated`, `PaymentSucceeded`, `PaymentFailed`, `RemindersJobRuns`, `RemindersJobErrors`, `DocumentOpsErrors`, `DynamoAuditErrors`).
  4. Latencia API y API Gateway (`MiDoc/RequestLatencyMs` p95 y Average, `AWS/ApiGateway/Latency` p95, `AWS/ApiGateway/IntegrationLatency` Average, línea de umbral en `3000 ms`).
  5. Errores y tráfico (`MiDoc/ServerErrors`, `AWS/Lambda` `Invocations`/`Errors`/`Throttles`/`Duration`, `AWS/ApiGateway` `Count`/`4xx`/`5xx`).
  6. Salud de RDS PostgreSQL (`CPUUtilization`, `DatabaseConnections`, `FreeStorageSpace`).
  7. Logs recientes combinados de `/aws/lambda/${project}-api` y `/aws/apigateway/${project}-http-api` (últimos 25 eventos).
- **Consultas guardadas en CloudWatch Logs Insights (`aws_cloudwatch_query_definition`):**
  1. `${var.project_name}/api-errors` -> `/aws/lambda/${project}-api`: filtra `ERROR`, `Traceback` o `statusCode`/`status` `5xx`.
  2. `${var.project_name}/slow-requests` -> `/aws/lambda/${project}-api` y `/aws/apigateway/${project}-http-api`: filtra `RequestLatencyMs > 1000 or responseLatency > 1000`.
  3. `${var.project_name}/payments-and-reminders` -> `/aws/lambda/${project}-api`: filtra `/stripe|payment|checkout|reminders/i`.
  4. `${var.project_name}/apigw-5xx-access` -> `/aws/apigateway/${project}-http-api`: filtra `status >= 400`.

### 1.6 Pruebas automatizadas del contrato de monitoreo

```powershell
python -m unittest discover -s backend/test -p "test_metricas.py" -v
python -m unittest discover -s backend/test -p "test_monitoreo.py" -v
```
`test_monitoreo.py` verifica sobre los archivos `.tf` reales: cantidad de alarmas, `alarm_actions` + `ok_actions` hacia SNS, métrica `5xx` de API Gateway HTTP v2, dimensión `Service="midoc-api"`, gating por `var.enable_monitoring` y `var.enable_rds`, presencia de las 12 métricas EMF en el dashboard y definición de los Log Groups + Logs Insights queries.

---

## 2. Automatización en GitHub Actions (CI y CD)

### 2.1 Flujo de Integración Continua — `.github/workflows/ci.yml` (`MiDoc CI`)

- **Disparadores:** `push` a `main`, `pull_request` hacia `main` y `workflow_dispatch`. Permisos mínimos: `contents: read`.
- **Jobs paralelos:**
  1. `backend` (`ubuntu-latest`, `backend/`): Python `3.12`, instala `requirements.txt`, ejecuta `python -m unittest discover -s test -v`.
  2. `infrastructure` (`ubuntu-latest`, `infrastructure/`): Python `3.12` + Terraform (`hashicorp/setup-terraform@v3`), ejecuta `terraform fmt -check -recursive`, `terraform init -backend=false`, `terraform validate` y `python -m py_compile *.py`.
  3. `frontend` (`ubuntu-latest`, `frontend/`): Node `24` (con caché de `frontend/package-lock.json`), `npm ci`, `npx tsc -p tsconfig.app.json --noEmit`, `npx tsc -p tsconfig.spec.json --noEmit`, `npm test` y `npm run build`.

### 2.2 Flujo de Entrega Continua — `.github/workflows/cd.yml` (`MiDoc CD`)

> **Nota sobre visibilidad en `gh workflow list`:** El archivo `.github/workflows/cd.yml` se creó en la rama `feat/producto-completo`. GitHub Actions registra el workflow en `gh workflow list` una vez que la rama se integra o sube a `main`.

- **Disparadores:** `push` a `main` y `workflow_dispatch` con parámetros:
  - `payment_mode`: `test` (por defecto) o `live`.
  - `enable_monitoring`: booleano (`true` por defecto).
  - `run_smoke`: booleano (`true` por defecto).
- **Concurrencia:** `group: midoc-cd-${{ github.ref }}`, `cancel-in-progress: false` para no interrumpir un `terraform apply` en curso.
- **Job 1 — `preflight`:**
  - Evalúa si existen los 4 secretos mínimos (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `TF_VAR_jwt_secret`). En `push`, si faltan credenciales evita romper el historial con un aviso (`can_deploy=false`); en `workflow_dispatch`, falla explícitamente (`exit 1`).
  - Verifica coherencia entre `payment_mode` y el prefijo de `TF_VAR_stripe_secret_key` (`sk_test_` vs `sk_live_`; `live` exige llave no vacía).
  - Comprueba que la sesión temporal de AWS Academy Learner Lab siga vigente con `aws sts get-caller-identity --region us-east-1`.
- **Job 2 — `deploy` (`needs: preflight`, `if: needs.preflight.outputs.can_deploy == 'true'`):**
  - Compila el frontend Angular (`npm ci`, `npm run build`).
  - Si se definió `TF_STATE_BUCKET`, genera `backend_override.tf` para estado remoto S3 (`key = "midoc/terraform.tfstate"`, `region = "us-east-1"`).
  - Ejecuta `terraform init` y `terraform apply -auto-approve -input=false` con las variables `TF_VAR_*`.
  - Ejecuta `python infrastructure/publish_frontend.py --payment-mode ...` para sincronizar `dist/` y `config.json`.
  - Si `run_smoke == 'true'`, valida `GET /health`, `GET /api/doctors`, carga del `frontend_url`, estructura de `config.json` y existencia en CloudWatch de las alarmas y los 2 Log Groups (`/aws/lambda/${PROJECT_PREFIX}-api` y `/aws/apigateway/${PROJECT_PREFIX}-http-api`).

### 2.3 Secretos exactos requeridos por `cd.yml`

| Secreto en GitHub Actions | Obligatorio | Propósito |
| --- | --- | --- |
| `AWS_ACCESS_KEY_ID` | Sí | Llave temporal de la sesión AWS Academy (`voclabs`) |
| `AWS_SECRET_ACCESS_KEY` | Sí | Secreto temporal de la sesión AWS Academy (`voclabs`) |
| `AWS_SESSION_TOKEN` | Sí | Token efímero de sesión de AWS Academy Learner Lab |
| `TF_VAR_jwt_secret` | Sí | Secreto largo aleatorio para firmar JWT HS256 (mínimo 32 caracteres recomendados) |
| `TF_VAR_stripe_secret_key` | Recomendado (obligatorio en `live`) | Llave Stripe `sk_test_...` o `sk_live_...` |
| `TF_VAR_stripe_webhook_secret` | Opcional | Secreto `whsec_...` para firma HMAC de `/api/webhooks/stripe` |
| `TF_VAR_alert_email` | Opcional | Correo electrónico para suscripción a alarmas SNS |
| `TF_STATE_BUCKET` | Opcional (muy recomendado para CD repetible) | Bucket S3 existente donde guardar `midoc/terraform.tfstate` entre ejecuciones efímeras de runners |

### 2.4 Flujo operativo con credenciales efímeras de Learner Lab y `gh` CLI

Cada vez que inicies sesión en AWS Academy Learner Lab, actualiza los secretos temporales antes de disparar `cd.yml`:

```powershell
# 1. Cargar secretos de sesión temporal (desde AWS Details -> AWS CLI)
gh secret set AWS_ACCESS_KEY_ID --body "<ACCESS_KEY>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<SECRET_KEY>"
gh secret set AWS_SESSION_TOKEN --body "<SESSION_TOKEN>"

# 2. Configurar secretos de aplicación/Stripe (una vez por cambio de modo)
gh secret set TF_VAR_jwt_secret --body "<SECRETO_JWT_LARGO>"
gh secret set TF_VAR_stripe_secret_key --body "sk_test_..."
gh secret set TF_VAR_stripe_webhook_secret --body "whsec_..."
gh secret set TF_VAR_alert_email --body "equipo@ejemplo.com"

# 3. Inspeccionar workflows y ejecuciones
gh workflow list
gh run list --limit 10

# 4. Disparar CD manualmente en modo prueba
gh workflow run cd.yml -f payment_mode=test -f enable_monitoring=true -f run_smoke=true
```
