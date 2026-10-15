# Prueba funcional temporal de MiDoc`r`n`r`n> Este despliegue fue utilizado para validar la integración AWS y posteriormente fue eliminado con `terraform destroy`. Las URLs de abajo son evidencia histórica; deben regenerarse al volver a ejecutar Terraform.`r`n
## URL pública del backend

```text
https://2obhgm1da2.execute-api.us-east-1.amazonaws.com
```

La URL correspondió a API Gateway HTTP y ejecutó el backend Python en AWS Lambda. El despliegue temporal utilizó RDS PostgreSQL para las entidades principales, DynamoDB para eventos, Secrets Manager y Lambda dentro de la VPC.

## URL pública del frontend

Después de ejecutar `terraform apply`, consulta:

```powershell
terraform -chdir=infrastructure output -raw frontend_url
```

El frontend se publica en un bucket S3 mediante AWS CLI desde Terraform. Esta ruta evita la lectura de Object Lock bloqueada en el provider de Terraform.

## Pruebas rápidas en PowerShell

```powershell
$api = "https://2obhgm1da2.execute-api.us-east-1.amazonaws.com"

# Salud
Invoke-RestMethod "$api/health"

# Búsqueda de profesionales
Invoke-RestMethod "$api/api/doctors"

# Login de paciente de demostración
$login = Invoke-RestMethod "$api/api/auth/login" -Method Post `
  -ContentType "application/json" `
  -Body '{"email":"paciente@midoc.local","password":"paciente-demo"}'
$headers = @{ Authorization = "Bearer $($login.token)" }

# Agenda
Invoke-RestMethod "$api/api/appointments" -Method Post -Headers $headers `
  -ContentType "application/json" `
  -Body '{"doctorId":"d-1","dateTime":"2026-10-20T10:00:00Z"}'

# Consentimiento
Invoke-RestMethod "$api/api/consents" -Method Post -Headers $headers `
  -ContentType "application/json" `
  -Body '{"doctorId":"d-1","granted":true}'

# Login de doctor y lectura del expediente autorizado
$doctor = Invoke-RestMethod "$api/api/auth/login" -Method Post `
  -ContentType "application/json" `
  -Body '{"email":"doctor@midoc.local","password":"doctor-demo"}'
$doctorHeaders = @{ Authorization = "Bearer $($doctor.token)" }
Invoke-RestMethod "$api/api/records?patientId=u-patient-1" -Headers $doctorHeaders
Invoke-RestMethod "$api/api/subscriptions" -Headers $doctorHeaders
```

## Frontend local contra la API desplegada

El frontend Angular usa la API local cuando se abre en `localhost` y la URL pública de arriba cuando se sirve desde otro host. Para ejecutarlo:

```powershell
npm install --prefix frontend
npm start --prefix frontend
```

El bucket fue público sólo para lectura de archivos del frontend y se cifró en reposo. No contenía secretos ni datos clínicos.

## Eliminación posterior

Cuando termines las pruebas, desde `infrastructure` ejecuta:

```powershell
terraform destroy -auto-approve
```

Este comando elimina Lambda, API Gateway, RDS, DynamoDB, Secrets Manager y el bucket S3 creados por esta ejecución.
