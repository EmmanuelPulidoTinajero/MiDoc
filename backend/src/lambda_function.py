import base64
import binascii
import json

from app import handle, _response
import app
import flujos


def handler(event, _context):
    # API Gateway siempre incluye requestContext; un cuerpo HTTP no puede
    # convertirse en este evento de invocación directa.
    if event.get("source") == "midoc.reminders" and "requestContext" not in event:
        resultado = flujos.generar_recordatorios(app)
        print(json.dumps({"job": "reminders", **resultado}))
        return resultado
    request_context = event.get("requestContext", {}).get("http", {})
    method = request_context.get("method", event.get("httpMethod", "GET"))
    path = event.get("rawPath", event.get("path", "/"))
    query = event.get("rawQueryString", "")
    if query:
        path = f"{path}?{query}"
    body = event.get("body")
    if body:
        try:
            decoded = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body
            body = json.loads(decoded)
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            return _response(400, {"error": "El cuerpo debe contener JSON válido"})
    else:
        body = {}
    return handle(method, path, event.get("headers", {}), body)
