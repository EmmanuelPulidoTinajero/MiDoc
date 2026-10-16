# Despliegue de fase 2 · AWS Academy

## Requisitos

- Learner Lab activo y AWS CLI autenticado como `voclabs` en `us-east-1`.
- El rol existente `LabRole` debe poder ejecutar Lambda, leer Secrets Manager, registrar eventos en DynamoDB, usar S3 y conectarse a RDS. Terraform no crea roles ni modifica políticas.
- Terraform 1.6 o posterior, Python 3.12 o posterior con `pip`, Node.js 24.15+ dentro de la rama 24.

Comprueba la identidad antes de desplegar:

```powershell
aws sts get-caller-identity
```

Tarea 2 documenta la restricción de Cognito User Pools. Las pruebas previas observaron denegaciones al consultar CloudFront y políticas IAM; no se comprobó la creación de una distribución. El frontend usa el endpoint REST HTTPS de S3 con /index.html, sin necesitar CloudFront. API y documentos también usan HTTPS. EventBridge ejecuta recordatorios cada 15 minutos con permiso de invocación limitado a la Lambda existente.

## Preparación

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
Copy-Item infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
```

Edita `infrastructure/terraform.tfvars` localmente y reemplaza el `jwt_secret` de ejemplo por un valor aleatorio largo. El archivo está ignorado por Git. No muestres el valor ni lo compartas. La entrada de Terraform lo marca sensible, pero el estado local también contiene el secreto: protege `infrastructure/terraform.tfstate` y sus respaldos. En un equipo de trabajo se debe configurar un backend remoto cifrado y con acceso restringido.

## Plan y despliegue

```powershell
terraform -chdir=infrastructure init
terraform -chdir=infrastructure fmt -check -recursive
terraform -chdir=infrastructure validate
terraform -chdir=infrastructure plan -var-file=terraform.tfvars
terraform -chdir=infrastructure apply -var-file=terraform.tfvars
```

El plan crea RDS PostgreSQL cifrado (`db.t3.micro`, 20 GB), API Gateway, Lambda en la VPC, tabla DynamoDB, Secrets Manager, endpoints de VPC para Secrets Manager/S3/DynamoDB, bucket S3 del frontend y bucket S3 privado de documentos. RDS, Secrets Manager y el endpoint interface tienen cargos por tiempo y almacenamiento; revisa los precios del laboratorio antes de dejar recursos encendidos.

Terraform usa `infrastructure/build_lambda.py` para construir las fuentes Python y dependencias Linux/Python 3.12 en `backend/.lambda-build`, sin instalar binarios dentro de `backend/src`. Empaqueta el resultado en `backend/lambda-package.zip`. El pipeline requiere `pip` y acceso al índice de paquetes durante el primer despliegue.

El script de S3 usa AWS CLI porque la política del Learner Lab deniega `s3:GetBucketObjectLockConfiguration` al provider AWS. El bucket de documentos tiene bloqueo de acceso público, cifrado AES-256 y CORS limitado a los orígenes de MiDoc/local. El bucket del frontend sólo contiene archivos estáticos públicos.

## Verificación funcional

Para actualizar el frontend sobre el mismo bucket, compila y ejecuta `python infrastructure/publish_frontend.py`. Terraform no detecta automáticamente cambios de `dist/`. El script elige `dist/midoc-frontend/browser`, preserva `config.json` durante el sync y lee las salidas del estado. No reemplaces `terraform_data.frontend_bucket` para publicar cambios: su provisioner destroy vacía y elimina el bucket.

```powershell
$api = terraform -chdir=infrastructure output -raw api_url
$site = terraform -chdir=infrastructure output -raw frontend_url
Invoke-RestMethod "$api/health"
Invoke-RestMethod "$api/api/doctors"
Start-Process $site
```

Sigue el checklist de [DEPLOYMENT-TEST.md](DEPLOYMENT-TEST.md). Comprueba en la consola de AWS que RDS esté `available` y Lambda `Active`; no imprimas credenciales, secretos ni tokens en una grabación.

## Persistencia y limpieza

En el primer acceso de cada entorno Lambda se ejecuta `backend/src/schema.sql`. Los archivos de `backend/migrations/` son históricos y no cubren las ampliaciones recientes; no hay un ejecutor de migraciones versionadas. Se desplegaron el bloqueo de inicialización, la inserción semilla sólo si falta un periodo y la conexión PostgreSQL con TLS obligatorio. Los periodos duplicados ya existentes no se eliminaron.

El bucket privado de expedientes se deja fuera del borrado automático para evitar eliminar documentos por accidente. Si usaste sólo datos de demostración y realmente quieres borrarlo, verifica primero el bucket exacto `midoc-documents-<account-id>` y sus objetos, luego usa AWS CLI deliberadamente. `terraform destroy` elimina otros recursos y RDS, pero no borra ese bucket de documentos.

## CI/CD

`.github/workflows/ci.yml` valida pruebas, compilación y Terraform en push/PR. Aún falta CD: no hay una identidad de GitHub Actions configurada y validada para desplegar. No se ha demostrado que el laboratorio prohíba todas las alternativas de federación.
