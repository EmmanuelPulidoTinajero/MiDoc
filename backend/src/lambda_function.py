import base64
import binascii
import json
import logging
import os
import time
import uuid

from app import handle, _response
import app
import flujos
import metricas

if os.environ.get("NODE_ENV") == "production":
    metricas.configurar_logging()


def handler(event, _context):
    if os.environ.get("NODE_ENV") == "production" and not logging.getLogger("midoc").handlers:
        metricas.configurar_logging()
    # API Gateway siempre incluye requestContext; un cuerpo HTTP no puede
    # convertirse en este evento de invocación directa.
    if event.get("source") == "midoc.reminders" and "requestContext" not in event:
        inicio = time.perf_counter()
        metricas.registrar_metrica("RemindersJobRuns", 1)
        try:
            resultado = flujos.generar_recordatorios(app)
        except Exception as error:
            metricas.registrar_metrica("RemindersJobErrors", 1)
            metricas.log_evento(
                "ERROR",
                "reminders_job_failed",
                job="reminders",
                errorType=type(error).__name__,
                durationMs=round((time.perf_counter() - inicio) * 1000, 2),
            )
            raise
        print(json.dumps({"job": "reminders", **resultado}), flush=True)
        metricas.log_evento(
            "INFO",
            "reminders_job_completed",
            job="reminders",
            processedUsers=resultado.get("processedUsers", 0),
            durationMs=round((time.perf_counter() - inicio) * 1000, 2),
        )
        return resultado

    rc = event.get("requestContext") or {}
    request_context = rc.get("http") or {}
    source_ip = request_context.get("sourceIp") or (rc.get("identity") or {}).get("sourceIp")
    method = request_context.get("method", event.get("httpMethod", "GET"))
    raw_path = event.get("rawPath", event.get("path", "/"))
    query = event.get("rawQueryString", "")
    path = f"{raw_path}?{query}" if query else raw_path
    request_id = (
        getattr(_context, "aws_request_id", None)
        or rc.get("requestId")
        or str(uuid.uuid4())
    )

    inicio = time.perf_counter()
    raw_input = event.get("body")
    raw_body = b""
    respuesta = None
    if raw_input:
        try:
            if event.get("isBase64Encoded"):
                decoded_bytes = base64.b64decode(raw_input, validate=True)
            else:
                decoded_bytes = raw_input.encode("utf-8") if isinstance(raw_input, str) else raw_input
            raw_body = decoded_bytes
            body = json.loads(decoded_bytes)
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            body = {}
            respuesta = _response(400, {"error": "El cuerpo debe contener JSON válido"})
    else:
        body = {}

    metricas.limpiar_contexto()
    if respuesta is None:
        respuesta = handle(
            method,
            path,
            event.get("headers", {}),
            body,
            raw_body=raw_body,
            client_ip=source_ip,
        )
    duracion_ms = (time.perf_counter() - inicio) * 1000
    metricas.registrar_peticion(method, path, respuesta["statusCode"], duracion_ms)
    metricas.log_peticion(
        request_id=request_id,
        route=raw_path.split("?", 1)[0] or "/",
        method=method,
        status=respuesta["statusCode"],
        duration_ms=duracion_ms,
        user_role=metricas.obtener_rol(),
    )
    return respuesta
