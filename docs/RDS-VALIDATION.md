# Validación de RDS en AWS Learner Lab

## Resultado

MiDoc utiliza una instancia PostgreSQL privada creada y administrada por Terraform en `us-east-1`. La instancia de esta validación temporal fue destruida al finalizar las pruebas; esta documentación describe la configuración reproducible.

| Propiedad | Valor |
| --- | --- |
| Identidad creadora | rol asumido `voclabs` |
| Rol de ejecución de Lambda | `LabRole` |
| Motor | PostgreSQL 16.13 |
| Clase | `db.t3.micro` |
| Almacenamiento | 20 GB, cifrado |
| Acceso público | No |
| Zona | `us-east-1d` |
| Base inicial | `midoc` |
| Estado validado | `available` |

La creación inicial tardó aproximadamente 5 minutos 53 segundos. Lambda quedó conectada a dos subredes de la VPC, RDS acepta TCP 5432 sólo desde su grupo de seguridad y Secrets Manager se consulta mediante un endpoint privado.

## Persistencia integrada

El backend incluye `psycopg2-binary` en el paquete Lambda. En el primer acceso, crea de forma idempotente las tablas de usuarios, perfiles, citas, consentimientos, expedientes, consultas, suscripciones y bitácora; también carga datos ficticios de demostración. Las operaciones de doctores, login, citas, consentimiento, expediente, consultas y suscripciones ya utilizan PostgreSQL en AWS.

## Verificación

```powershell
terraform -chdir=infrastructure output -raw database_endpoint
aws rds describe-db-instances --region us-east-1 `
  --query 'DBInstances[].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Class:DBInstanceClass,Engine:Engine,Version:EngineVersion,Encrypted:StorageEncrypted,Public:PubliclyAccessible}' `
  --output table
```

No se deben publicar credenciales ni el valor de ningún secreto. Para eliminar todos los recursos temporales al finalizar las pruebas:

```powershell
terraform -chdir=infrastructure destroy -auto-approve
```
