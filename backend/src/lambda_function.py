import base64
import json

from app import handle


def handler(event, _context):
    request_context = event.get("requestContext", {}).get("http", {})
    method = request_context.get("method", event.get("httpMethod", "GET"))
    path = event.get("rawPath", event.get("path", "/"))
    query = event.get("rawQueryString", "")
    if query:
        path = f"{path}?{query}"
    body = event.get("body")
    if body:
        decoded = base64.b64decode(body) if event.get("isBase64Encoded") else body
        body = json.loads(decoded)
    else:
        body = {}
    return handle(method, path, event.get("headers", {}), body)
