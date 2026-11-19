import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Los módulos de la ampliación viven junto a este archivo (en Lambda, en local y en pruebas).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import flujos  # noqa: E402
import metricas  # noqa: E402
import reglas  # noqa: E402
import servicios_aws  # noqa: E402

logger = logging.getLogger("midoc.app")


def _load_jwt_secret() -> str:
    if os.environ.get("NODE_ENV") != "production":
        return os.environ.get("JWT_SECRET") or "local-development-only-change-me"
    secret_id = os.environ.get("SECRETS_MANAGER_SECRET_ID") or os.environ.get("APP_SECRET_ARN")
    if not secret_id:
        raise RuntimeError("SECRETS_MANAGER_SECRET_ID es obligatorio en producción")
    import boto3
    secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
    values = json.loads(secret)
    if not values.get("jwt_secret"):
        raise RuntimeError("El secreto de Secrets Manager debe incluir jwt_secret")
    return values["jwt_secret"]


JWT_SECRET = _load_jwt_secret()
_DATABASE_INITIALIZED = False


def _allow_demo_seed() -> bool:
    valor = os.environ.get("ALLOW_DEMO_SEED")
    if valor is not None:
        return valor.strip().lower() == "true"
    return os.environ.get("NODE_ENV") != "production"


def _database_connection():
    if os.environ.get("NODE_ENV") != "production":
        return None
    import boto3
    import psycopg2

    secret_arn = os.environ.get("DATABASE_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("DATABASE_SECRET_ARN es obligatorio en producción")
    secret = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"])
    connection = psycopg2.connect(
        host=os.environ.get("DATABASE_HOST", secret.get("host", "")),
        port=secret.get("port", 5432),
        dbname=os.environ.get("DATABASE_NAME", secret.get("dbname", "midoc")),
        user=secret["username"],
        password=secret["password"],
        connect_timeout=5,
        sslmode="require",
    )
    global _DATABASE_INITIALIZED
    if not _DATABASE_INITIALIZED:
        with connection.cursor() as cursor:
            # Los arranques concurrentes no deben competir por DDL ni duplicar la semilla.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('midoc-schema-init'))")
            schema = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
            cursor.execute(schema)
            if _allow_demo_seed():
                cursor.execute(
                    "INSERT INTO usuario (id, email, password_hash, rol) VALUES "
                    "('00000000-0000-0000-0000-000000000001', 'paciente@midoc.local', %s, 'PACIENTE'), "
                    "('00000000-0000-0000-0000-000000000002', 'doctor@midoc.local', %s, 'DOCTOR') "
                    "ON CONFLICT (email) DO NOTHING",
                    (_demo_hash("paciente-demo", "patient-demo-salt"), _demo_hash("doctor-demo", "doctor-demo-salt")),
                )
                cursor.execute(
                    "INSERT INTO perfil_doctor (id, usuario_id, nombre_completo, especialidad, ubicacion, precio_consulta) "
                    "VALUES ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002', 'Dra. Ana López', 'Medicina familiar', 'Guadalajara', 600) "
                    "ON CONFLICT (usuario_id) DO NOTHING"
                )
                cursor.execute(
                    "INSERT INTO expediente (paciente_id, alergias, notas) VALUES ('00000000-0000-0000-0000-000000000001', ARRAY[]::text[], 'Expediente de demostración') "
                    "ON CONFLICT (paciente_id) DO NOTHING"
                )
                cursor.execute(
                    "INSERT INTO suscripcion (doctor_id, estado, monto, fecha_inicio, fecha_fin) "
                    "SELECT '10000000-0000-0000-0000-000000000001', 'ACTIVA', 20, CURRENT_DATE, CURRENT_DATE + 29 "
                    "WHERE NOT EXISTS (SELECT 1 FROM suscripcion "
                    "WHERE doctor_id = '10000000-0000-0000-0000-000000000001')"
                )
                flujos.semilla_postgres(cursor)
        connection.commit()
        _DATABASE_INITIALIZED = True
    return connection


def _database_ready() -> bool:
    production = os.environ.get("NODE_ENV") == "production"
    if production and not os.environ.get("DATABASE_SECRET_ARN"):
        raise reglas.ErrorApi(503, "La base de datos de producción no está configurada")
    return production


def _audit_record_access(patient_id: str, actor_id: str) -> None:
    """Escribe un evento complementario en DynamoDB; PostgreSQL conserva la bitácora transaccional.

    La bitácora de DynamoDB complementa, no autoriza: si falla, la lectura del expediente ya
    autorizada sigue adelante y el error queda registrado sin PII.
    """
    try:
        servicios_aws.registrar_acceso(patient_id, actor_id)
    except Exception as error:  # noqa: BLE001 - la auditoría nunca debe bloquear la lectura
        metricas.registrar_metrica("DynamoAuditErrors", 1)
        logger.warning("auditoria_dynamodb_fallida error=%s", type(error).__name__)


def _query(sql: str, params: tuple = (), fetch: bool = True):
    connection = _database_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.fetchall() if fetch else None
        connection.commit()
        return result
    finally:
        connection.close()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, expected = stored.split(":", 1)
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def _demo_hash(password: str, salt: str) -> str:
    return hash_password(password, salt.encode())


def _empty_db() -> dict:
    return {
        "users": [],
        "doctors": [],
        "appointments": [],
        "consents": [],
        "records": [],
        "prescriptions": [],
        "subscriptions": [],
    }


def _demo_db() -> dict:
    return {
        "users": [
            {"id": "u-patient-1", "email": "paciente@midoc.local", "role": "PACIENTE", "password_hash": _demo_hash("paciente-demo", "patient-demo-salt")},
            {"id": "u-doctor-1", "email": "doctor@midoc.local", "role": "DOCTOR", "password_hash": _demo_hash("doctor-demo", "doctor-demo-salt")},
        ],
        "doctors": [
            {"id": "d-1", "user_id": "u-doctor-1", "name": "Dra. Ana López", "specialty": "Medicina familiar", "location": "Guadalajara", "price": 600}
        ],
        "appointments": [],
        "consents": [],
        "records": [{"patient_id": "u-patient-1", "allergies": [], "notes": "Expediente de demostración"}],
        "prescriptions": [],
        "subscriptions": [{"doctor_id": "d-1", "status": "ACTIVA", "amount": 20}],
    }


DB = _demo_db() if _allow_demo_seed() else _empty_db()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def create_token(user: dict) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": user["id"], "role": user["role"], "exp": int(time.time()) + 3600}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def authenticate(headers: dict) -> dict | None:
    authorization = headers.get("authorization", headers.get("Authorization", ""))
    if not authorization.startswith("Bearer "):
        return None
    try:
        encoded_header, encoded_payload, signature = authorization[7:].split(".")
        expected = _b64(hmac.new(JWT_SECRET.encode(), f"{encoded_header}.{encoded_payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        padding = "=" * (-len(encoded_payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(f"{encoded_payload}{padding}"))
        return claims if claims["exp"] >= int(time.time()) else None
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _valid(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "content-type, authorization, idempotency-key",
            "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


_APP = sys.modules[__name__]


def handle(
    method: str,
    path: str,
    headers: dict | None = None,
    body: dict | None = None,
    raw_body: bytes | str | None = None,
    client_ip: str | None = None,
) -> dict:
    """Convierte los errores de validación y de base de datos en respuestas JSON (400/404/409)
    en lugar de un 500 sin cuerpo, para que el frontend pueda mostrar el mensaje."""
    if body is not None and not isinstance(body, dict):
        return _response(400, {"error": "El cuerpo de la petición debe ser un objeto JSON"})
    try:
        return _handle(method, path, headers, body, raw_body=raw_body, client_ip=client_ip)
    except reglas.ErrorApi as error:
        return _response(error.status, {"error": error.mensaje})
    except Exception as error:
        codigo = getattr(error, "pgcode", None)
        if codigo in ("22P02", "22007", "22008"):
            return _response(400, {"error": "Algún dato tiene un formato inválido"})
        if codigo == "23503":
            return _response(404, {"error": "Un registro relacionado no existe"})
        if codigo == "23505":
            return _response(409, {"error": "El registro ya existe"})
        logger.exception("Error no controlado en %s %s", method, path.split("?", 1)[0])
        return _response(500, {"error": "Error interno del servidor"})


def _handle(
    method: str,
    path: str,
    headers: dict | None = None,
    body: dict | None = None,
    raw_body: bytes | str | None = None,
    client_ip: str | None = None,
) -> dict:
    headers = headers or {}
    body = body or {}
    parsed = urlparse(path)
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    if method == "OPTIONS":
        return _response(204, {})
    if method == "GET" and parsed.path == "/health":
        return _response(200, {"status": "ok", "service": "midoc-api"})
    if method == "POST" and parsed.path == "/api/webhooks/stripe":
        return flujos.webhook_stripe(_APP, headers, raw_body, body)
    if method == "GET" and parsed.path == "/api/doctors":
        # Filtros: specialty (original), location, q y sort; solo doctores con suscripción vigente.
        return flujos.buscar_doctores(_APP, query)
    if method == "POST" and parsed.path == "/api/auth/login":
        return flujos.iniciar_sesion(_APP, body, headers, client_ip=client_ip)

    # Registro, perfil de doctor y disponibilidad (no requieren sesión).
    publica = flujos.atender_publico(_APP, method, parsed.path, query, body)
    if publica is not None:
        return publica

    user = authenticate(headers)
    if not user:
        return _response(401, {"error": "Autenticación requerida"})
    metricas.establecer_rol(user.get("role", "ANONYMOUS"))

    if method == "POST" and parsed.path == "/api/auth/refresh":
        return flujos.refrescar_sesion(_APP, user)

    if method == "POST" and parsed.path == "/api/appointments":
        if user["role"] != "PACIENTE":
            return _response(403, {"error": "Sólo un paciente puede agendar"})
        if not _valid(body.get("doctorId")) or not _valid(body.get("dateTime")):
            return _response(400, {"error": "doctorId y dateTime son requeridos"})
        # Valida doctor con suscripción, fecha futura y que el horario esté libre.
        return flujos.agendar_cita(_APP, user, body, headers)

    if method == "GET" and parsed.path == "/api/appointments":
        # Mismos campos que antes más nombres del doctor/paciente; filtro opcional ?status=
        return flujos.listar_citas(_APP, user, query)

    if method == "PUT" and parsed.path.startswith("/api/appointments/") and parsed.path.endswith("/reschedule"):
        appointment_id = parsed.path.removeprefix("/api/appointments/").removesuffix("/reschedule").strip("/")
        if not appointment_id or "/" in appointment_id or not _valid(body.get("dateTime")):
            return _response(400, {"error": "appointmentId y dateTime válidos son requeridos"})
        return flujos.reprogramar_cita(_APP, user, appointment_id, body)

    if method == "PUT" and parsed.path.startswith("/api/appointments/") and parsed.path.endswith("/status"):
        appointment_id = parsed.path.removeprefix("/api/appointments/").removesuffix("/status").strip("/")
        if not appointment_id or "/" in appointment_id:
            return _response(404, {"error": "Ruta no encontrada"})
        return flujos.actualizar_estado_cita(_APP, user, appointment_id, body)

    if method == "POST" and parsed.path == "/api/consents":
        return flujos.administrar_consentimiento(_APP, user, body)

    if method == "GET" and parsed.path == "/api/records":
        # Mismos campos que antes (patient_id, allergies, notes) más datos clínicos,
        # documentos e historial de consultas. El doctor necesita consentimiento y
        # suscripción vigente; cada acceso queda en la bitácora.
        return flujos.ver_expediente(_APP, user, query)

    if method == "GET" and parsed.path.startswith("/api/prescriptions/"):
        prescription_id = parsed.path.removeprefix("/api/prescriptions/").strip("/")
        if not prescription_id or "/" in prescription_id:
            return _response(404, {"error": "Ruta no encontrada"})
        return flujos.ver_receta(_APP, user, prescription_id)

    if method == "POST" and parsed.path == "/api/consultations":
        if user["role"] not in ("DOCTOR", "CLINICA"):
            return _response(403, {"error": "Sólo un doctor puede registrar consultas"})
        if not all(_valid(body.get(key)) for key in ("patientId", "appointmentId", "diagnosis")):
            return _response(400, {"error": "patientId, appointmentId y diagnosis son requeridos"})
        # Requiere suscripción y consentimiento; marca la cita COMPLETADA, crea la
        # receta con su PDF en S3 y la consulta aparece en el historial del paciente.
        return flujos.registrar_consulta(_APP, user, body, headers)

    if method == "GET" and parsed.path == "/api/subscriptions":
        return flujos.ver_suscripcion(_APP, user)

    if method == "POST" and parsed.path == "/api/subscriptions/pay":
        return _response(410, {"error": "El pago simulado fue retirado; utiliza POST /api/subscriptions/checkout"})

    extra = flujos.atender_autenticado(_APP, user, method, parsed.path, query, body, headers)
    if extra is not None:
        return extra

    return _response(404, {"error": "Ruta no encontrada"})
