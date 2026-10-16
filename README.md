# MiDoc

MiDoc es un marketplace de salud que conecta pacientes con profesionales y centros médicos. El paciente administra su expediente y autoriza quién puede consultarlo; los profesionales gestionan disponibilidad, citas, suscripción, pacientes, mensajes, inventario y promociones.

## Alcance de fase 2

El MVP cubre los tres flujos end-to-end del proyecto integrador:

1. **Búsqueda y cita:** el paciente filtra profesionales, consulta disponibilidad, agenda y puede cancelar; el profesional confirma o cancela.
2. **Expediente y consentimiento:** el paciente crea y actualiza su expediente, concede o revoca acceso y administra estudios/documentos privados en S3. El acceso profesional requiere consentimiento vigente y queda registrado en PostgreSQL y DynamoDB.
3. **Suscripción y consulta:** el profesional registra una suscripción de demostración, publica su horario, atiende una cita autorizada y guarda diagnóstico, tratamiento y receta en PostgreSQL. El paciente puede abrir la receta e imprimirla o guardarla como PDF desde el navegador.

Los pagos son simulados: no hay cobros reales ni pasarela de pagos. Usa sólo datos ficticios; el sistema no está aprobado para expedientes reales.

El panel permite reprogramar citas, consultar historial clínico, registrar existencias de insumos y publicar promociones con vigencia. La mensajería requiere una cita o consentimiento entre las personas. Avisos de citas, mensajes, recetas y vencimientos aparecen en la bandeja in-app. El correo no está integrado: se denegaron consultas de configuración SES y no se probó el envío ni la creación de un topic SNS dedicado.

## Servicios y decisiones

| Servicio | Uso en MiDoc |
| --- | --- |
| AWS Lambda | Ejecuta la API Python 3.12 sin servidor persistente. |
| API Gateway HTTP | Publica la API mediante HTTPS. |
| RDS PostgreSQL | Fuente de verdad relacional para usuarios, citas, consentimiento, expedientes, suscripciones, consultas, recetas, mensajes, inventario, promociones y avisos. RDS es privado, cifrado y accesible desde Lambda. |
| Secrets Manager | Guarda la llave JWT y las credenciales administradas de RDS. Lambda consulta los secretos usando el rol existente `LabRole`. |
| S3 | Publica los archivos estáticos del frontend; un bucket separado, privado y cifrado almacena documentos clínicos con URLs firmadas por cinco minutos. |
| DynamoDB | Bitácora complementaria de lecturas de expedientes, con claves `PACIENTE#id` y `ACCESO#fecha#id`. PostgreSQL mantiene el registro transaccional principal. |
| IAM / `LabRole` | Rol de ejecución ya existente en AWS Academy. Terraform no crea ni modifica roles o políticas. |
| CloudWatch Logs | Recibe los logs de Lambda. Métricas personalizadas, alertas y dashboard corresponden a la fase final. |
| EventBridge | Genera recordatorios de citas y vencimientos cada 15 minutos aunque el navegador esté cerrado. |

La propuesta de fase 1 mencionaba Cognito. Tarea 2 documenta que AWS Academy no permite crear los User Pools requeridos; por eso la autenticación usa JWT propio y contraseñas con hash scrypt. No se crean recursos de Cognito ni se solicitan permisos adicionales. DynamoDB se limita a la bitácora que Tarea 2 propuso como posible sexto servicio.

Tarea 2 no requiere SNS ni SES. En la sesión activa, SES responde `AccessDenied` y SNS sólo muestra el topic `RedshiftSNS`; no enviamos correo ni publicamos avisos de MiDoc en recursos de otro sistema. La aplicación usa avisos internos almacenados en PostgreSQL.

### Restricciones verificadas en el Learner Lab

- La cuenta usa `voclabs` para provisionar y el rol existente `LabRole` para Lambda.
- Las consultas de solo lectura confirmaron la VPC por defecto y el rol `LabRole`.
- Las consultas `cloudfront:ListDistributions` y `cloudfront:GetDistribution` devolvieron `AccessDenied`; no prueban una prohibición completa del servicio. El frontend usa el endpoint REST HTTPS de S3 con `/index.html`, sin necesitar CloudFront.
- La lectura de políticas IAM fue denegada. Por instrucción del usuario se conservan los roles existentes. EventBridge recibe únicamente un permiso de invocación sobre Lambda limitado a la regla MiDoc; no se modifica LabRole.
- Los recursos del entorno son efímeros y la disponibilidad depende de que la sesión del laboratorio siga activa.

**Demo activa:** [abrir MiDoc por HTTPS](https://midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html). Web, API y documentos usan HTTPS. Se conservan cuentas y datos ficticios; no hay aprobación para uso clínico real.

Verificación del 16/10/2026: 36 pruebas locales, tres flujos reales en AWS, seis recorridos en Edge y ocho vistas sin infracciones detectadas por axe. Los resultados y pendientes están en [la revisión integral](docs/REVISION-INTEGRAL.md).

## Ejecutar localmente

Requisitos: Python 3.12 o posterior y Node.js 24.15 o posterior dentro de la rama 24 (CI usa Node 24). Angular 22 instalado no admite Node 20.

```powershell
python -m unittest discover -s backend/test -v
python backend/src/local.py
npm ci --prefix frontend
npm start --prefix frontend
```

El backend local usa memoria para datos ficticios. La API queda en `http://localhost:3000`; Angular queda en `http://localhost:4200`. La carga de archivos requiere S3 configurado y funciona en AWS.

## Desplegar en AWS Academy

1. Inicia la sesión del Learner Lab y confirma que `aws sts get-caller-identity` devuelva el rol `voclabs`.
2. Compila el frontend: `npm run build --prefix frontend`.
3. Desde PowerShell, configura un secreto aleatorio temporal en el entorno; no escribas valores reales en archivos versionados.
4. Ejecuta Terraform:

```powershell
Copy-Item infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
# Reemplaza jwt_secret por un valor aleatorio largo en el archivo local ignorado por Git.
terraform -chdir=infrastructure init
terraform -chdir=infrastructure validate
terraform -chdir=infrastructure plan -var-file=terraform.tfvars
terraform -chdir=infrastructure apply -var-file=terraform.tfvars
```

Terraform prepara un paquete limpio para Lambda en `backend/.lambda-build` sin alterar `backend/src`, crea RDS PostgreSQL, API Gateway, DynamoDB, Secrets Manager, endpoints privados para S3/DynamoDB/Secrets Manager y publica el sitio y el bucket privado de documentos. El coste del entorno depende de la duración de RDS y del endpoint de Secrets Manager; el Learner Lab puede suspender recursos al expirar.

Consulta las URLs actuales con:

```powershell
terraform -chdir=infrastructure output -raw api_url
terraform -chdir=infrastructure output -raw frontend_url
```

No ejecutes `terraform destroy` mientras haya archivos que quieras conservar. El bucket privado de documentos se conserva fuera del ciclo de borrado automático. La validación de la fase 2 debe hacerse con el despliegue activo, mostrando los tres flujos y al menos 80% de la aplicación en AWS.

## Seguridad y calidad

- JWT de una hora, contraseñas con scrypt, autorización por rol y verificación de consentimiento en el servidor.
- Validación de fechas, estados de cita, datos y archivos (PDF/JPG/PNG/DICOM hasta 10 MB); consultas SQL parametrizadas e integridad relacional.
- PostgreSQL cifrado y privado. Los documentos usan bucket S3 privado, cifrado en reposo, URLs firmadas de cinco minutos y autorización antes de emitir la URL.
- Los archivos no se sirven públicamente. El frontend usa enlaces firmados sin credenciales de sesión.
- El workflow `.github/workflows/ci.yml` ejecuta pruebas de backend, build de Angular y validación de Terraform. Falta CD; no hay identidad de despliegue de GitHub configurada o validada en este proyecto.
- El demo y las cuentas semilla son ficticios. La suscripción usa tarjetas de prueba y no ejecuta transacciones.
- La interfaz incorpora navegación por teclado, salto al contenido, foco visible, estados anunciables, formularios etiquetados y tablas desplazables en móvil. Véase [cobertura del Reporte 1 y revisión WCAG](docs/COBERTURA-REPORTE1.md); requiere validación manual con lector de pantalla.

## Documentación

- [Arquitectura y decisiones](docs/ARCHITECTURE.md)
- [Contrato de API](docs/API.md)
- [Cobertura de funciones del Reporte 1 y accesibilidad](docs/COBERTURA-REPORTE1.md)
- [Revisión integral y prioridades de aceptación](docs/REVISION-INTEGRAL.md)
- [Despliegue reproducible](docs/DEPLOYMENT.md)
- [Validación de RDS](docs/RDS-VALIDATION.md)
- [Prueba de despliegue y evidencia](docs/DEPLOYMENT-TEST.md)
- [Reporte de fase 2](reporte/REPORTE-FASE2.md)
- [Borrador de entrega PDF, 4 páginas; video pendiente](reporte/ENTREGA-FASE2.pdf)

## Equipo

| Integrante | Rol |
| --- | --- |
| Emmanuel Pulido Tinajero | DevOps, infraestructura y soporte técnico |
| David (Dakewer) | Frontend |
| Gilberto Anaya | Backend |
