# Validación RDS

> Estado posterior a las pruebas: el usuario solicitó retirar el entorno AWS el 16/10/2026. Código y evidencia publicados en el commit cc315ec; el estado operativo descrito abajo es histórico. Ver [CIERRE-AWS.md](CIERRE-AWS.md).

Fecha:16/10/2026. Fuente relacional: PostgreSQL16.13 en us-east-1, instancia midoc-20261016130331567100000009. Estado available, PubliclyAccessible=false, StorageEncrypted=true.

Lambda midoc-api usa Python3.12, LabRole existente, VPC y credenciales administradas desde Secrets Manager. Su cliente exige sslmode=require. No se imprimieron secretos. RDS acepta5432 desde el security group de Lambda.

Los tres recorridos quedaron verificados con persistencia real: usuarios/suscripciones, horarios/citas/estados, expediente/consentimientos, mensajes/avisos, inventario/promociones y consulta/receta/historial. La consulta esperó la hora real de su cita y también se registró desde Edge; repetirla devuelve409. Evidencia: [evidencia-aws-e2e.json](evidencia-aws-e2e.json).

La inicialización usa schema.sql bajo bloqueo advisory; la semilla inserta la suscripción inicial sólo si no existe periodo. No elimina duplicados históricos. Los cambios de negocio y sus avisos ahora comparten transacción y conexión. Regresiones locales verifican rollback ante fallo; no se indujeron errores RDS deliberados en nube.

Pendiente: ejecutor de migraciones versionadas (001/002 históricas incompletas), usuario de aplicación separado, TLS verify-full con CA, cold starts concurrentes y backup/restore. RDS no es Multi-AZ y el despliegue conserva skip_final_snapshot=true. No se afirma disponibilidad clínica ni recuperación certificada.
