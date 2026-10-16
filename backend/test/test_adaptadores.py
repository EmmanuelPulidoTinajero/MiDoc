"""Regresiones en los límites HTTP y en la configuración de producción."""
import base64
import json
import os
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import app
from src.lambda_function import handler
from src.local import Handler


class ConfiguracionProduccion(unittest.TestCase):
    def test_produccion_sin_rds_no_usa_cuentas_en_memoria(self):
        with patch.dict(os.environ, {"NODE_ENV": "production"}, clear=True):
            response = app.handle("POST", "/api/auth/login", body={
                "email": "paciente@midoc.local", "password": "paciente-demo"})
        self.assertEqual(response["statusCode"], 503)

    def test_produccion_exige_secrets_manager_aunque_haya_jwt_en_entorno(self):
        with patch.dict(os.environ, {"NODE_ENV": "production", "JWT_SECRET": "unsafe-env-secret"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SECRETS_MANAGER_SECRET_ID"):
                app._load_jwt_secret()

    def test_login_normaliza_correo_como_registro(self):
        with patch.dict(os.environ, {"NODE_ENV": "test"}):
            response = app.handle("POST", "/api/auth/login", body={
                "email": " PACIENTE@MIDOC.LOCAL ", "password": "paciente-demo"})
        self.assertEqual(response["statusCode"], 200)


class AdaptadorLambda(unittest.TestCase):
    def test_json_y_base64_invalidos_producen_400_con_cors(self):
        for body, encoded in [("{invalid", False), ("***", True),
                              (base64.b64encode(b"{invalid").decode(), True)]:
            with self.subTest(encoded=encoded, body=body):
                result = handler({"httpMethod": "POST", "path": "/api/auth/login",
                                  "body": body, "isBase64Encoded": encoded}, None)
                self.assertEqual(result["statusCode"], 400)
                self.assertIn("access-control-allow-origin", result["headers"])


class AdaptadorLocal(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, body=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, "/api/doctor/inventory/prueba", body=body)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_delete_llega_a_autorizacion_en_lugar_de_501(self):
        status, body = self.request("DELETE")
        self.assertEqual(status, 401)
        self.assertIn("error", body)

    def test_json_invalido_produce_400_en_lugar_de_cerrar_conexion(self):
        status, body = self.request("POST", "{invalid")
        self.assertEqual(status, 400)
        self.assertIn("JSON", body["error"])


if __name__ == "__main__":
    unittest.main()
