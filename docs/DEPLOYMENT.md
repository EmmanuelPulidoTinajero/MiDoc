# Despliegue

## Validación local

```powershell
python -m unittest discover -s backend/test -v
```

## Terraform

1. Configura credenciales AWS mediante el mecanismo oficial del laboratorio; no las escribas en archivos del repositorio.
2. Copia `infrastructure/terraform.tfvars.example` a un archivo local no versionado.
3. Ejecuta `terraform -chdir=infrastructure init`.
4. Ejecuta `terraform -chdir=infrastructure validate`.
5. Define `TF_VAR_jwt_secret` con un valor aleatorio de al menos 32 caracteres, o agrégalo sólo a un archivo local `terraform.tfvars` no versionado.
6. Revisa `terraform -chdir=infrastructure plan -var-file=terraform.tfvars`.
7. Ejecuta `terraform -chdir=infrastructure apply -var-file=terraform.tfvars` sólo después de revisar el plan.

La configuración compatible con la cuenta detectada crea y publica el frontend mediante un script AWS CLI ejecutado por `terraform_data`, una tabla DynamoDB de eventos, un secreto de Secrets Manager, una función Lambda Python 3.12 y una API HTTP de API Gateway. Se evita `aws_s3_bucket` porque una SCP del laboratorio bloquea la lectura de Object Lock que hace el provider. RDS PostgreSQL se crea con la configuración validada en Learner Lab; el esquema relacional se conserva en `backend/migrations/001_initial.sql`. Terraform usa las credenciales actuales del CLI (`voclabs`) y Lambda ejecuta con el rol existente `LabRole`.

La cuenta detectada tiene una VPC por defecto con subredes públicas, pero no tiene NAT Gateway. Terraform crea un endpoint privado para Secrets Manager, asocia Lambda a dos subredes y restringe RDS para aceptar PostgreSQL sólo desde el grupo de seguridad de Lambda.

Terraform crea la versión inicial del secreto de aplicación con esta forma y después ignora cambios accidentales del valor para no rotarlo en cada `apply`. Para rotarlo, actualiza el secreto explícitamente desde Secrets Manager:

La infraestructura crea RDS PostgreSQL por defecto con la clase `db.t3.micro`, 20 GB y almacenamiento cifrado. AWS puede tardar varios minutos en pasar la instancia de `creating` a `available`; no se debe interrumpir Terraform durante ese proceso. La instancia se crea privada. Terraform configura la VPC de Lambda, los grupos de seguridad, el endpoint privado de Secrets Manager y el paquete Lambda con `psycopg2-binary`; al primer acceso, el backend inicializa el esquema PostgreSQL de forma idempotente con datos ficticios de demostración.

```json
{"jwt_secret":"genera-un-valor-largo-y-aleatorio"}
```

No imprimas el valor del secreto en terminales compartidas ni lo agregues al repositorio.

## GitHub Actions

El workflow valida el backend y Terraform en cada push y pull request. Para habilitar despliegue real se deben configurar credenciales federadas OIDC y permisos IAM específicos; nunca se deben usar claves AWS hardcodeadas.
