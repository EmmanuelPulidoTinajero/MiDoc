# Despliegue Reproducible de MiDoc (Fase 3 · AWS Academy)

## Requisitos previos

- Sesión activa de AWS Academy Learner Lab y AWS CLI autenticado como `voclabs` en `us-east-1`.
- Rol existente `LabRole` en la cuenta con permisos para Lambda, Secrets Manager, DynamoDB, S3, RDS, CloudWatch y EventBridge (Terraform no crea roles IAM).
- Herramientas locales: **Terraform >= 1.6**, **Python >= 3.12** con `pip`, **Node.js >= 24.15** (rama 24; Angular 22 no admite Node 20).

Comprueba la identidad activa antes de desplegar:

```powershell
aws sts get-caller-identity
```

---

## Preparación y configuración (`terraform.tfvars`)

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
Copy-Item infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
```

Edita `infrastructure/terraform.tfvars` localmente (archivo ignorado por Git) sin exponer secretos en commits ni registros:

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `jwt_secret` | *(requerido)* | Secreto aleatorio largo para firmar JWT HS256 (mínimo 32 caracteres recomendados). |
| `payment_mode` | `"test"` | `"test"` (Stripe Sandbox `sk_test_...`) o `"live"` (Producción `sk_live_...`). |
| `stripe_secret_key` | `""` | Llave secreta de Stripe. Terraform valida el prefijo según `payment_mode` (`sk_test_` vs `sk_live_`). |
| `stripe_webhook_secret` | `""` | Secreto `whsec_...` del endpoint `/api/webhooks/stripe` (opcional si sólo se confirma en retorno). |
| `stripe_price_amount_cents` | `2000` | Monto de la suscripción mensual en centavos USD (`2000` = $20.00 USD). |
| `enable_nat_gateway` | `true` | Aprovisiona 2 subredes privadas (`172.31.96.0/20`, `172.31.112.0/20`), EIP y NAT Gateway para salida HTTPS hacia `api.stripe.com`. |
| `enable_monitoring` | `true` | Crea Log Groups (14 días), access logs API GW, SNS, 10 alarmas, 4 Logs Insights queries y dashboard `midoc-estado`. |
| `alert_email` | `""` | Correo electrónico opcional para suscribirse al tópico SNS `${project}-alerts`. |
| `allow_demo_seed` | `false` | Debe permanecer en `false` en producción para no sembrar cuentas ni suscripciones demo. |
| `delete_medical_bucket_on_destroy` | `true` | Si es `true`, `terraform destroy` vacía y elimina también el bucket privado de documentos clínicos. |

Para alternar entre modo prueba y producción antes de desplegar, consulta la guía detallada en [PAGOS-STRIPE.md](PAGOS-STRIPE.md).

---

## Plan y despliegue con Terraform

```powershell
terraform -chdir=infrastructure init
terraform -chdir=infrastructure fmt -check -recursive
terraform -chdir=infrastructure validate
terraform -chdir=infrastructure plan -var-file=terraform.tfvars
terraform -chdir=infrastructure apply -var-file=terraform.tfvars
```

El plan aprovisiona:
- **Red y cómputo:** 2 subredes privadas, EIP + NAT Gateway, endpoints privados VPC (Secrets Manager, S3, DynamoDB), API Gateway HTTP v2 y Lambda Python 3.12 (`midoc-api`, empaquetado por `infrastructure/build_lambda.py` en `backend/.lambda-build` con `psycopg2-binary` Linux).
- **Datos y secretos:** RDS PostgreSQL 16.13 privado/cifrado (`db.t3.micro`, 20 GB), tabla DynamoDB `application_events`, secreto `midoc-application-*` y secreto `midoc-stripe-*` (ambos con `recovery_window_in_days = 0`), más dos buckets S3 (`s3_frontend.py` y `s3_medical.py`).
- **Automatización y monitoreo:** Regla EventBridge `midoc-reminders` (`rate(15 minutes)`), Log Groups `/aws/lambda/midoc-api` y `/aws/apigateway/midoc-http-api`, tópico SNS `midoc-alerts`, 10 alarmas CloudWatch, 4 consultas Logs Insights y dashboard `midoc-estado`.

> **Importante sobre cambios sólo de frontend:** Para actualizar el frontend compilado sobre el bucket existente sin destruir el bucket, ejecuta:
> ```powershell
> npm run build --prefix frontend
> python infrastructure/publish_frontend.py --payment-mode test
> ```
> No reemplaces el recurso `terraform_data.frontend_bucket`, ya que su provisioner `destroy` vacía y elimina el bucket.

---

## Verificación local y en nube

### 1. Suites automatizadas locales (sin AWS activo)
```powershell
python -m unittest discover -s backend/test -p "test_*.py"          # 101 pruebas unitarias/integración
npx --prefix frontend tsc -p frontend/tsconfig.app.json --noEmit
npx --prefix frontend tsc -p frontend/tsconfig.spec.json --noEmit
npm --prefix frontend test                                          # 20 archivos / 57 pruebas Vitest
npm --prefix frontend run e2e                                       # 8 pruebas Playwright (desktop + mobile)
python tests/e2e/run_e2e.py --mode self-test --tier all             # 197 casos en 4 niveles (o --mode live --target local --stripe-mode mock)
```

### 2. Verificación en vivo tras `terraform apply`
```powershell
$api = terraform -chdir=infrastructure output -raw api_url
$site = terraform -chdir=infrastructure output -raw frontend_url
Invoke-RestMethod "$api/health"
Invoke-RestMethod "$api/api/doctors"
Start-Process $site
```
Y para ejecutar la batería E2E completa contra la nube real (incluyendo Stripe modo prueba y CloudWatch):
```powershell
python tests/e2e/run_e2e.py --mode live --target cloud --stripe-mode live_cloud --with-browser --tier all
```
Consulta también la guía en [../tests/e2e/README.md](../tests/e2e/README.md) y el registro histórico de Fase 2 en [DEPLOYMENT-TEST.md](DEPLOYMENT-TEST.md).

---

## Persistencia, migraciones y destrucción total (`terraform destroy`)

- **Esquema y migraciones versionadas:** `backend/migrations/` contiene `001_initial.sql`, `002_ampliacion_flujos.sql`, `003_inventario_promociones_avisos_mensajes.sql` y `004_stripe_suscripcion_y_perfil.sql`, mantenidas en paridad 1:1 con `backend/src/schema.sql` y validadas por `backend/test/test_migraciones.py`.
- **Destrucción automática y verificación de cero recursos:**
  - Con `delete_medical_bucket_on_destroy = true` (valor por defecto), `terraform destroy` ejecuta `s3_frontend.py destroy` y `s3_medical.py destroy` (abortando cargas multiparte y borrando versiones/marcadores), elimina NAT Gateway, EIP, subredes privadas, RDS, API Gateway, Lambda, DynamoDB, CloudWatch, SNS y secretos (`recovery_window_in_days = 0`).
  - Si se requiere conservar documentos clínicos en un despliegue específico, cambia `delete_medical_bucket_on_destroy = false` antes de destruir.
  - Al finalizar cualquier `terraform destroy`, valida que no queden recursos remanentes en la cuenta ejecutando:
    ```powershell
    terraform -chdir=infrastructure destroy -var-file=terraform.tfvars -auto-approve
    python infrastructure/verify_teardown.py --report docs/evidencia-destruccion-aws.json
    ```
    El script `verify_teardown.py` audita dinámicamente **21 categorías de recursos AWS** más el estado de Terraform (`terraformManagedResources`), confirma la preservación de `LabRole` y sólo devuelve código de salida `0` (`result: "PASS"`) cuando no queda ningún recurso activo del proyecto. Ver detalles históricos y pendientes de M5 en [CIERRE-AWS.md](CIERRE-AWS.md).

---

## CI/CD en GitHub Actions

- **Integración Continua (`.github/workflows/ci.yml`):** Ejecuta en push/PR a `main` las pruebas backend (`unittest`), validación Terraform (`fmt`, `init -backend=false`, `validate`, `py_compile`) y validación frontend (`tsc`, `vitest`, `build`).
- **Entrega Continua (`.github/workflows/cd.yml`):** Se dispara en `push` a `main` y `workflow_dispatch` (`payment_mode`, `enable_monitoring`, `run_smoke`), ejecuta `preflight` (validación de secretos, prefijo Stripe y `aws sts get-caller-identity`) seguido de `deploy` (`terraform apply`, `publish_frontend.py` y smoke checks HTTP/CloudWatch). Ver configuración completa de secretos efímeros de Learner Lab en [OBSERVABILIDAD-Y-CICD.md](OBSERVABILIDAD-Y-CICD.md).
