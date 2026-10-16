import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import handle


class Handler(BaseHTTPRequestHandler):
    def do_request(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            body = None
            response = {"statusCode": 400, "headers": {"content-type": "application/json; charset=utf-8",
                        "access-control-allow-origin": "*"},
                        "body": json.dumps({"error": "El cuerpo debe contener JSON válido"})}
        else:
            response = handle(self.command, self.path, dict(self.headers), body)
        self.send_response(response["statusCode"])
        for key, value in response["headers"].items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(response["body"].encode())

    do_GET = do_request
    do_POST = do_request
    do_PUT = do_request
    do_DELETE = do_request
    do_OPTIONS = do_request  # preflight de CORS del navegador


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(__import__("os").environ.get("PORT", "3000"))), Handler).serve_forever()
