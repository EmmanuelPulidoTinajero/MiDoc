import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Los módulos de la ampliación viven junto a este archivo (en Lambda, en local y en pruebas).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import flujos  # noqa: E402
import reglas  # noqa: E402

logger = logging.getLogger(__name__)


def _load_jwt_secret() -> str:
    configured = os.environ.get("JWT_SECRET")
    if configured:
        return configured
    if os.environ.get("NODE_ENV") != "production":
        return "local-development-only-change-me"
    secret_id = os.environ.get("SECRETS_MANAGER_SECRET_ID")
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
    )
    global _DATABASE_INITIALIZED
    if not _DATABASE_INITIALIZED:
        with connection.cursor() as cursor:
            schema = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
            cursor.execute(schema)
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
                "VALUES ('10000000-0000-0000-0000-000000000001', 'ACTIVA', 20, CURRENT_DATE, CURRENT_DATE + 30) "
                "ON CONFLICT DO NOTHING"
            )
            flujos.semilla_postgres(cursor)
        connection.commit()
        _DATABASE_INITIALIZED = True
    return connection


def _database_ready() -> bool:
    return os.environ.get("NODE_ENV") == "production" and bool(os.environ.get("DATABASE_SECRET_ARN"))


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


def _db_doctors(specialty: str):
    rows = _query(
        "SELECT id::text, nombre_completo, especialidad, ubicacion, precio_consulta "
        "FROM perfil_doctor WHERE (%s = '' OR lower(especialidad) LIKE '%%' || lower(%s) || '%%') ORDER BY nombre_completo",
        (specialty, specialty),
    )
    return [{"id": row[0], "name": row[1], "specialty": row[2], "location": row[3], "price": float(row[4])} for row in rows]


def _db_user(email: str, password: str):
    rows = _query("SELECT id::text, email, rol, password_hash FROM usuario WHERE email = %s", (email,))
    if not rows or not verify_password(password, rows[0][3]):
        return None
    return {"id": rows[0][0], "email": rows[0][1], "role": rows[0][2]}


def _db_appointment(user_id: str, doctor_id: str, date_time: str):
    rows = _query(
        "INSERT INTO cita (paciente_id, doctor_id, fecha_hora) VALUES (%s, %s, %s) RETURNING id::text",
        (user_id, doctor_id, date_time),
    )
    return {"id": rows[0][0], "patientId": user_id, "doctorId": doctor_id, "dateTime": date_time, "status": "PENDIENTE"}


def _db_doctor_id(user_id: str):
    rows = _query("SELECT id::text FROM perfil_doctor WHERE usuario_id = %s", (user_id,))
    return rows[0][0] if rows else None


def _db_consent(patient_id: str, doctor_id: str, granted: bool):
    rows = _query(
        "INSERT INTO consentimiento_expediente (paciente_id, doctor_id, estado_acceso) VALUES (%s, %s, %s) "
        "ON CONFLICT (paciente_id, doctor_id) DO UPDATE SET estado_acceso = EXCLUDED.estado_acceso, fecha_actualizacion = now() "
        "RETURNING estado_acceso, fecha_actualizacion",
        (patient_id, doctor_id, granted),
    )
    return {"patientId": patient_id, "doctorId": doctor_id, "granted": rows[0][0], "updatedAt": rows[0][1].isoformat()}


def _db_has_consent(patient_id: str, doctor_id: str):
    rows = _query("SELECT estado_acceso FROM consentimiento_expediente WHERE paciente_id = %s AND doctor_id = %s", (patient_id, doctor_id))
    return bool(rows and rows[0][0])


def _db_record(patient_id: str, actor_id: str):
    rows = _query("SELECT paciente_id::text, alergias, notas FROM expediente WHERE paciente_id = %s", (patient_id,))
    _query("INSERT INTO bitacora_acceso_expediente (paciente_id, actor_id) VALUES (%s, %s)", (patient_id, actor_id), fetch=False)
    if not rows:
        return {"patient_id": patient_id, "allergies": [], "notes": ""}
    return {"patient_id": rows[0][0], "allergies": rows[0][1] or [], "notes": rows[0][2] or ""}


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


DB = {
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
            "access-control-allow-headers": "content-type, authorization",
            "access-control-allow-methods": "GET,POST,PUT,OPTIONS",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


_APP = sys.modules[__name__]


def handle(method: str, path: str, headers: dict | None = None, body: dict | None = None) -> dict:
    """Convierte los errores de validación y de base de datos en respuestas JSON (400/404/409)
    en lugar de un 500 sin cuerpo, para que el frontend pueda mostrar el mensaje."""
    if body is not None and not isinstance(body, dict):
        return _response(400, {"error": "El cuerpo de la petición debe ser un objeto JSON"})
    try:
        return _handle(method, path, headers, body)
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
        logger.exception("Error no controlado en %s %s", method, path)
        return _response(500, {"error": "Error interno del servidor"})


def _handle(method: str, path: str, headers: dict | None = None, body: dict | None = None) -> dict:
    headers = headers or {}
    body = body or {}
    parsed = urlparse(path)
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    if method == "OPTIONS":
        return _response(204, {})
    if method == "GET" and parsed.path == "/health":
        return _response(200, {"status": "ok", "service": "midoc-api"})
    if method == "GET" and parsed.path == "/api/doctors":
        # Filtros: specialty (original), location y q; solo doctores con suscripción vigente.
        return flujos.buscar_doctores(_APP, query)
    if method == "POST" and parsed.path == "/api/auth/login":
        if _database_ready():
            user = _db_user(body.get("email", ""), body.get("password", "")) if _valid(body.get("password")) else None
            if not user:
                return _response(401, {"error": "Credenciales inválidas"})
            return _response(200, {"token": create_token(user), "user": user})
        user = next((item for item in DB["users"] if item["email"] == body.get("email") and _valid(body.get("password")) and verify_password(body["password"], item["password_hash"])), None)
        if not user:
            return _response(401, {"error": "Credenciales inválidas"})
        return _response(200, {"token": create_token(user), "user": {"id": user["id"], "email": user["email"], "role": user["role"]}})

    # Registro, perfil de doctor y disponibilidad (no requieren sesión).
    publica = flujos.atender_publico(_APP, method, parsed.path, query, body)
    if publica is not None:
        return publica

    user = authenticate(headers)
    if not user:
        return _response(401, {"error": "Autenticación requerida"})

    if method == "POST" and parsed.path == "/api/appointments":
        if user["role"] != "PACIENTE":
            return _response(403, {"error": "Sólo un paciente puede agendar"})
        if not _valid(body.get("doctorId")) or not _valid(body.get("dateTime")):
            return _response(400, {"error": "doctorId y dateTime son requeridos"})
        # Valida doctor con suscripción, fecha futura y que el horario esté libre.
        return flujos.agendar_cita(_APP, user, body)

    if method == "GET" and parsed.path == "/api/appointments":
        # Mismos campos que antes más nombres del doctor/paciente; filtro opcional ?status=
        return flujos.listar_citas(_APP, user, query)

    if method == "POST" and parsed.path == "/api/consents":
        if user["role"] != "PACIENTE":
            return _response(403, {"error": "Sólo el paciente administra consentimientos"})
        if not _valid(body.get("doctorId")) or not isinstance(body.get("granted"), bool):
            return _response(400, {"error": "doctorId y granted son requeridos"})
        flujos.validar_doctor_para_consentimiento(_APP, body["doctorId"])
        if _database_ready():
            return _response(200, {"data": _db_consent(user["sub"], body["doctorId"], body["granted"])})
        consent = {"patientId": user["sub"], "doctorId": body["doctorId"], "granted": body["granted"], "updatedAt": datetime.now(timezone.utc).isoformat()}
        DB["consents"] = [item for item in DB["consents"] if not (item["patientId"] == user["sub"] and item["doctorId"] == body["doctorId"])]
        DB["consents"].append(consent)
        return _response(200, {"data": consent})

    if method == "GET" and parsed.path == "/api/records":
        # Mismos campos que antes (patient_id, allergies, notes) más datos clínicos,
        # documentos e historial de consultas. El doctor necesita consentimiento y
        # suscripción vigente; cada acceso queda en la bitácora.
        return flujos.ver_expediente(_APP, user, query)

    if method == "POST" and parsed.path == "/api/consultations":
        if user["role"] not in ("DOCTOR", "CLINICA"):
            return _response(403, {"error": "Sólo un doctor puede registrar consultas"})
        if not all(_valid(body.get(key)) for key in ("patientId", "appointmentId", "diagnosis")):
            return _response(400, {"error": "patientId, appointmentId y diagnosis son requeridos"})
        # Requiere suscripción y consentimiento; marca la cita COMPLETADA, crea la
        # receta con su PDF en S3 y la consulta aparece en el historial del paciente.
        return flujos.registrar_consulta(_APP, user, body)

    if method == "GET" and parsed.path == "/api/subscriptions":
        # Mismos campos que antes más vigencia (start, end, active) del periodo actual.
        return flujos.ver_suscripcion(_APP, user)

    # Rutas de la ampliación: expediente editable, documentos en S3, pago de la
    # suscripción, horario del doctor, estado de citas, recetas, etc.
    extra = flujos.atender_autenticado(_APP, user, method, parsed.path, query, body)
    if extra is not None:
        return extra

    return _response(404, {"error": "Ruta no encontrada"})
