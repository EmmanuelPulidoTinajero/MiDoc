# MiDoc

MiDoc es un marketplace de salud que conecta pacientes con profesionales y centros médicos. El paciente controla su expediente y decide con quién compartirlo; los profesionales gestionan citas, consultas y recetas desde un panel.

## Estado de fase 2

Este repositorio contiene la base de un MVP vertical con los tres flujos definidos en fase 1. La infraestructura temporal de validación fue destruida después de las pruebas; el repositorio conserva Terraform para reconstruirla.

1. Búsqueda de profesionales y agenda de citas.
2. Expediente médico y consentimiento explícito.
3. Suscripción del profesional y registro de consulta/receta.

El frontend está preparado para Angular 22. El backend está implementado en Python como runtime de una función AWS Lambda y se expone mediante API Gateway; no se ejecuta como un servidor persistente en producción. Esta separación es intencional: Angular es el frontend y Lambda ejecuta la API serverless.

## Estructura

```text
backend/       API HTTP, reglas de negocio y pruebas
frontend/      Aplicación Angular 22
infrastructure/ Terraform para Lambda, API Gateway, DynamoDB, RDS PostgreSQL y Secrets Manager
docs/          Arquitectura y decisiones técnicas
.github/       CI/CD con GitHub Actions
```

## Ejecución local

Requisitos: Python 3.12 o posterior para el backend y Node.js 20 o posterior para Angular. Lambda usa el runtime Python 3.12 y funciona localmente sin AWS usando datos de demostración en memoria.

```powershell
python -m unittest discover -s backend/test -v
python backend/src/local.py
```

La API queda disponible en `http://localhost:3000`. Para comprobarla:

```powershell
Invoke-RestMethod http://localhost:3000/health
Invoke-RestMethod http://localhost:3000/api/doctors
```

El frontend se instala y ejecuta así:

```powershell
npm install --prefix frontend
npm start --prefix frontend
```

Configura `API_URL` en el entorno de Angular para apuntar al backend. El frontend no contiene secretos.

## Variables de entorno del backend

| Variable | Requerida | Uso |
| --- | --- | --- |
| `PORT` | No | Puerto HTTP; por defecto `3000`. |
| `JWT_SECRET` | Sí en producción | Firma de tokens. En local se usa sólo para demo. |
| `DATABASE_URL` | No en demo | Conexión a PostgreSQL/RDS. |
| `AWS_REGION` | No en demo | Región AWS. |
| `SECRETS_MANAGER_SECRET_ID` | No en demo | Identificador del secreto administrado por AWS Secrets Manager. |

No guardes valores reales en Git. En AWS, `JWT_SECRET` y las credenciales de base de datos deben provenir de Secrets Manager y de un rol IAM de ejecución.

## Infraestructura y CI/CD

La carpeta `infrastructure` contiene Terraform y un ejemplo de variables. Terraform empaqueta `backend/src/lambda_function.py` como función Lambda Python 3.12, crea API Gateway, RDS PostgreSQL, DynamoDB y Secrets Manager. RDS usa por defecto `db.t3.micro`, 20 GB, PostgreSQL 16 y almacenamiento cifrado; su creación puede tardar varios minutos. El bucket S3 se administra mediante AWS CLI desde Terraform porque el Learner Lab deniega `s3:GetBucketObjectLockConfiguration`. El workflow `ci.yml` ejecuta pruebas Python del backend, build del frontend y validación de Terraform en cada cambio.

## Alcance y limitaciones declaradas

- Las suscripciones se representan mediante estados controlados para el MVP; no se integra una pasarela de pagos real.
- La autenticación es JWT propia porque la documentación de la tarea indica que Cognito no está disponible en AWS Academy. Las contraseñas se almacenan como hashes scrypt, nunca en texto plano.
- El adaptador local usa memoria para facilitar pruebas locales; en AWS, Terraform configura RDS PostgreSQL, la VPC de Lambda, grupos de seguridad y un endpoint privado de Secrets Manager. El backend inicializa el esquema PostgreSQL de forma idempotente con datos ficticios de demostración.
- Se usan datos ficticios. No subas expedientes reales.
- El monitoreo avanzado de fase 3 queda como ampliación. DynamoDB permanece provisionado para eventos y bitácora complementaria; las entidades principales se almacenan en RDS PostgreSQL.

## Equipo

| Integrante | Rol |
| --- | --- |
| Emmanuel Pulido Tinajero | DevOps, infraestructura y soporte técnico |
| David (Dakewer) | Frontend |
| Gilberto Anaya | Backend |
