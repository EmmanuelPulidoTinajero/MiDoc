# MiDoc

MiDoc es un marketplace de salud que conecta pacientes con profesionales y centros médicos (`PACIENTE`, `DOCTOR`, `CLINICA`). El paciente administra su expediente clínico, concede o revoca acceso explícito y sube estudios privados en S3; los profesionales y clínicas gestionan su suscripción mensual ($20 USD) mediante **Stripe**, horarios semanales, citas, consultas, recetas digitales en PDF, inventario, promociones y mensajería.

> **Estado del proyecto (Fase 3 · Hitos M1–M4 completados localmente; validación en vivo M5 pendiente):** La implementación de pagos reales con Stripe (`test`/`live`), recetas PDF en S3, Design System desde cero, observabilidad completa en CloudWatch y pipelines CI/CD está terminada y verificada en local. El despliegue histórico de Fase 2 (16/10/2026) fue retirado; el historial y los pasos pendientes de nube en vivo (Hito M5) están documentados en [CIERRE-AWS.md](docs/CIERRE-AWS.md).

## Alcance funcional

MiDoc cubre los tres flujos end-to-end del proyecto integrador y todas las ampliaciones comprometidas:

1. **Búsqueda y cita:** el paciente filtra profesionales por especialidad, ubicación, texto y ordenamiento (`NAME`, `PRICE_ASC`, `PRICE_DESC`, `AVAILABILITY`), consulta perfil, promociones vigentes y horarios libres (UTC-6), agenda, reprograma o cancela; el profesional confirma o cancela y configura su disponibilidad semanal.
2. **Expediente y consentimiento:** el paciente crea y actualiza su expediente clínico, concede o revoca acceso explícito por médico/clínica, audita quién consultó su expediente (`GET /api/records/access-log`) y gestiona documentos privados (`PDF`, `JPG`, `PNG`, `DICOM` <= 10 MB) en S3 mediante URLs firmadas de 300 s. Cada lectura profesional queda registrada en PostgreSQL y DynamoDB.
3. **Suscripción real con Stripe y consulta médica:** los roles `DOCTOR` y `CLINICA` contratan su suscripción mensual ($20.00 USD / 30 días) mediante **Stripe Checkout Sessions** (`POST /api/subscriptions/checkout`, `POST /api/subscriptions/confirm` y webhook HMAC `POST /api/webhooks/stripe`), alternando limpiamente entre modo prueba (`sk_test_...`) y producción (`sk_live_...`) antes del despliegue. Al atender una cita, el profesional registra diagnóstico, tratamiento y notas, y genera una **receta digital en PDF** real almacenada en S3 (`recetas/{receta_id}.pdf`) con descarga firmada e impresión.

El sistema incluye inventario de insumos/medicamentos, promociones del marketplace (informativas sobre el perfil del proveedor), mensajería directa condicionada por cita o consentimiento, bandeja de avisos transaccional in-app y recordatorios automáticos cada 15 minutos con **Amazon EventBridge**.

## Servicios AWS y decisiones de arquitectura

| Servicio | Uso en MiDoc (Fase 3) |
| --- | --- |
| **AWS Lambda** | Ejecuta la API Python 3.12 (`midoc-api`) y los recordatorios programados dentro de subredes privadas VPC usando `LabRole`. |
| **API Gateway HTTP v2** | Publica la API REST por HTTPS, aplica CORS y emite logs JSON de acceso hacia CloudWatch. |
| **NAT Gateway + VPC** | Da salida HTTPS desde las subredes privadas (`172.31.96.0/20`, `172.31.112.0/20`) hacia `https://api.stripe.com/v1/*`, manteniendo VPC Endpoints privados para S3, DynamoDB y Secrets Manager. |
| **RDS PostgreSQL 16.13** | Fuente de verdad transaccional (`PubliclyAccessible=false`, cifrado, `sslmode=require`) con migraciones `001`–`004` alineadas con `schema.sql`. |
| **Secrets Manager** | Almacena la llave JWT (`midoc-application-*`), credenciales de RDS y la configuración Stripe (`midoc-stripe-*`: `payment_mode`, `stripe_secret_key`, `stripe_webhook_secret`, `price_amount_cents`), todos con `recovery_window_in_days = 0`. |
| **Amazon S3 (2 buckets)** | Bucket público para la SPA Angular 22 (`HashLocationStrategy` + `config.json` en endpoint REST HTTPS `/index.html`) y bucket privado cifrado AES-256 para estudios clínicos y recetas PDF. |
| **Amazon DynamoDB** | Bitácora complementaria de acceso a expedientes (`pk=PACIENTE#<id>`, `sk=ACCESO#<fecha>#<uuid>`), tolerante a fallos en lectura. |
| **Amazon EventBridge** | Regla `midoc-reminders` (`rate(15 minutes)`) que materializa avisos de citas próximas (24 h) y vencimientos de suscripción (7 días). |
| **CloudWatch + SNS** | Logs JSON con redacción de PII/secretos, **2 Log Groups** (14 días), **12 métricas EMF** en namespace `MiDoc`, **10 alarmas**, tópico **SNS** dedicado (`midoc-alerts`), **4 consultas Logs Insights** y dashboard `midoc-estado`. |
| **IAM (`LabRole`)** | Se reutiliza el rol preexistente de AWS Academy Learner Lab sin crear roles ni alterar políticas globales. |

- **Sustitución de Cognito (`REQ-T2-08`):** Conforme a `tarea 2.pdf`, AWS Academy Learner Lab no permite aprovisionar Cognito User Pools; la autenticación utiliza JWT HS256 propio, hash `scrypt` y AWS Secrets Manager.
- **Restricciones de SES y CloudFront en Learner Lab:** Las consultas a SES devolvieron `AccessDenied` y SNS sólo mostraba `RedshiftSNS`; las notificaciones a pacientes/doctores se gestionan mediante bandeja in-app en PostgreSQL + EventBridge, mientras que el monitoreo usa el tópico propio `midoc-alerts`. El frontend sirve `/index.html` por S3 REST HTTPS con `HashLocationStrategy` sin requerir CloudFront.
- **Despliegue histórico retirado (16/10/2026):** La antigua URL de Fase 2 (`https://midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html`) se encuentra retirada; consulta [CIERRE-AWS.md](docs/CIERRE-AWS.md) y [la revisión integral](docs/REVISION-INTEGRAL.md).

## Ejecutar y probar localmente

Requisitos: **Python 3.12+** y **Node.js 24.15+** (rama 24; Angular 22 no admite Node 20).

```powershell
# 1. Pruebas automatizadas locales
python -m unittest discover -s backend/test -p "test_*.py"          # 101 pruebas backend
npx --prefix frontend tsc -p frontend/tsconfig.app.json --noEmit
npx --prefix frontend tsc -p frontend/tsconfig.spec.json --noEmit
npm ci --prefix frontend
npm --prefix frontend test                                          # 20 archivos / 57 pruebas Vitest
npm --prefix frontend run e2e                                       # 8 pruebas Playwright (desktop + mobile)
python tests/e2e/run_e2e.py --mode self-test --tier all             # 197 casos E2E (caja negra, 4 niveles)

# 2. Levantar aplicación local (memoria + mock Stripe opcional con STRIPE_API_BASE)
python backend/src/local.py
npm start --prefix frontend
```

La API local queda en `http://localhost:3000` y Angular en `http://localhost:4200`. Para probar el flujo Stripe en local sin salir a Internet, configura `PAYMENT_MODE=test`, `STRIPE_SECRET_KEY=sk_test_...` y opcionalmente `STRIPE_API_BASE` apuntando a un stub local (ver `tests/e2e/run_e2e.py --mode live --target local --stripe-mode mock --tier all`).

## Desplegar en AWS Academy y destruir sin remanentes

1. Inicia sesión en Learner Lab y valida la identidad activa: `aws sts get-caller-identity`.
2. Compila el frontend y prepara `infrastructure/terraform.tfvars` (ignorado por Git):

```powershell
npm run build --prefix frontend
Copy-Item infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
# Configura jwt_secret, payment_mode ("test" o "live"), stripe_secret_key,
# stripe_webhook_secret (opcional), alert_email (opcional) y allow_demo_seed = false.
terraform -chdir=infrastructure init
terraform -chdir=infrastructure fmt -check -recursive
terraform -chdir=infrastructure validate
terraform -chdir=infrastructure plan -var-file=terraform.tfvars
terraform -chdir=infrastructure apply -var-file=terraform.tfvars
```

3. Verifica los outputs y ejecuta las pruebas en vivo:

```powershell
terraform -chdir=infrastructure output -raw api_url
terraform -chdir=infrastructure output -raw frontend_url
python tests/e2e/run_e2e.py --mode live --target cloud --stripe-mode live_cloud --with-browser --tier all
```

4. Al concluir la validación, destruye toda la infraestructura y confirma **cero recursos residuales**:

```powershell
terraform -chdir=infrastructure destroy -var-file=terraform.tfvars -auto-approve
python infrastructure/verify_teardown.py --report docs/evidencia-destruccion-aws.json
```

Con `delete_medical_bucket_on_destroy = true` (valor por defecto en `infrastructure/variables.tf`), `terraform destroy` vacía y elimina tanto el bucket del frontend como el bucket privado de documentos, además de RDS, NAT Gateway, subredes privadas, secretos (`recovery_window_in_days = 0`) y recursos CloudWatch. `verify_teardown.py` audita dinámicamente **21 categorías de recursos** y conserva únicamente `LabRole`.

## Seguridad, Design System y CI/CD

- **Autenticación y datos:** JWT HS256 de 1 hora, contraseñas con `scrypt`, límite `429` en login (5 intentos/300 s), encabezado `Idempotency-Key`, autorización por rol/consentimiento en servidor, `ALLOW_DEMO_SEED=false` en producción, PostgreSQL cifrado (`sslmode=require`) y buckets S3 privados cifrados AES-256 con URLs firmadas de 300 s.
- **Design System desde cero:** Tokens WCAG 2.x en `frontend/src/styles/_tokens.css`, 9 componentes primitivos en `frontend/src/app/ds/`, enrutamiento `HashLocationStrategy` y especificación en [design/system.md](design/system.md).
- **CI/CD en GitHub Actions:** `.github/workflows/ci.yml` ejecuta pruebas backend, validación Terraform (`fmt`, `validate`, `py_compile`) y checks frontend (`tsc`, `vitest`, `build`). `.github/workflows/cd.yml` automatiza `preflight`, `terraform apply`, `publish_frontend.py` y smoke checks en `main` y `workflow_dispatch`. Consulta [OBSERVABILIDAD-Y-CICD.md](docs/OBSERVABILIDAD-Y-CICD.md).

## Documentación

- [Evaluación integral, trazabilidad y alcance (R1/R2)](docs/EVALUACION-INTEGRAL.md)
- [Pasarela de pagos Stripe: comparativa y guía prueba/producción (R3)](docs/PAGOS-STRIPE.md)
- [Observabilidad CloudWatch y automatización CI/CD (R5)](docs/OBSERVABILIDAD-Y-CICD.md)
- [Cierre AWS, remediaciones y validación pendiente M5 (R6)](docs/CIERRE-AWS.md)
- [Sistema de diseño MiDoc (R4)](design/system.md)
- [Arquitectura y decisiones](docs/ARCHITECTURE.md)
- [Contrato de API](docs/API.md)
- [Despliegue reproducible](docs/DEPLOYMENT.md)
- [Suite E2E de 4 niveles (caja negra)](tests/e2e/README.md)
- [Cobertura funcional del Reporte 1 y accesibilidad](docs/COBERTURA-REPORTE1.md)
- [Revisión integral y cierre de backlog](docs/REVISION-INTEGRAL.md)
- [Validación histórica de RDS (16/10/2026)](docs/RDS-VALIDATION.md)
- [Prueba histórica de despliegue y evidencia (16/10/2026)](docs/DEPLOYMENT-TEST.md)
- [Reporte histórico de fase 2](reporte/REPORTE-FASE2.md)
- [Entrega PDF de fase 2 (archivo histórico)](reporte/ENTREGA-FASE2.pdf)

## Equipo

| Integrante | Rol |
| --- | --- |
| Emmanuel Pulido Tinajero | DevOps, infraestructura y soporte técnico |
| David (Dakewer) | Frontend |
| Gilberto Anaya | Backend |
