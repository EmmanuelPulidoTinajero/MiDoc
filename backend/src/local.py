import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import handle


class Handler(BaseHTTPRequestHandler):
    def do_request(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        response = handle(self.command, self.path, dict(self.headers), json.loads(raw))
        self.send_response(response["statusCode"])
        for key, value in response["headers"].items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(response["body"].encode())

    do_GET = do_request
    do_POST = do_request


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(__import__("os").environ.get("PORT", "3000"))), Handler).serve_forever()
