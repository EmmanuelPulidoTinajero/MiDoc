"""Regresiones en los límites HTTP y en la configuración de producción."""
import base64
import json
import os
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import app
from src import flujos
from src import local
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

    def test_allow_demo_seed_gating_en_produccion_y_local(self):
        with patch.dict(os.environ, {"NODE_ENV": "production"}, clear=True):
            self.assertFalse(app._allow_demo_seed())
        with patch.dict(os.environ, {"NODE_ENV": "production", "ALLOW_DEMO_SEED": "true"}, clear=True):
            self.assertTrue(app._allow_demo_seed())
        with patch.dict(os.environ, {"NODE_ENV": "test", "ALLOW_DEMO_SEED": "false"}, clear=True):
            self.assertFalse(app._allow_demo_seed())

        # Verifica que _database_connection en producción sin ALLOW_DEMO_SEED=true no inserta demo
        cursor = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        psycopg2_mock = MagicMock()
        psycopg2_mock.connect.return_value = conn
        sm_client = MagicMock()
        sm_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"username": "u", "password": "p", "host": "h"})
        }
        boto3_mock = MagicMock()
        boto3_mock.client.return_value = sm_client

        prev_init = app._DATABASE_INITIALIZED
        try:
            app._DATABASE_INITIALIZED = False
            with patch.dict(
                os.environ,
                {"NODE_ENV": "production", "DATABASE_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:db"},
                clear=True,
            ), patch.dict(sys.modules, {"boto3": boto3_mock, "psycopg2": psycopg2_mock}):
                app._database_connection()
            sqls = [c.args[0] for c in cursor.execute.call_args_list]
            self.assertFalse(any("paciente@midoc.local" in s for s in sqls))

            app._DATABASE_INITIALIZED = False
            cursor.execute.reset_mock()
            with patch.dict(
                os.environ,
                {
                    "NODE_ENV": "production",
                    "ALLOW_DEMO_SEED": "true",
                    "DATABASE_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:db",
                },
                clear=True,
            ), patch.dict(sys.modules, {"boto3": boto3_mock, "psycopg2": psycopg2_mock}):
                app._database_connection()
            sqls_seed = [c.args[0] for c in cursor.execute.call_args_list]
            self.assertTrue(any("paciente@midoc.local" in s for s in sqls_seed))
        finally:
            app._DATABASE_INITIALIZED = prev_init


class AdaptadorLambda(unittest.TestCase):
    def test_json_y_base64_invalidos_producen_400_con_cors(self):
        for body, encoded in [("{invalid", False), ("***", True),
                              (base64.b64encode(b"{invalid").decode(), True)]:
            with self.subTest(encoded=encoded, body=body):
                result = handler({"httpMethod": "POST", "path": "/api/auth/login",
                                  "body": body, "isBase64Encoded": encoded}, None)
                self.assertEqual(result["statusCode"], 400)
                self.assertIn("access-control-allow-origin", result["headers"])

    def test_lambda_source_ip_prevalece_sobre_xff_spoofed_en_rate_limit(self):
        flujos.reset_rate_limits(app.DB)
        self.addCleanup(flujos.reset_rate_limits, app.DB)
        for idx in range(flujos.MAX_LOGIN_INTENTOS):
            res = handler(
                {
                    "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.10"}},
                    "rawPath": "/api/auth/login",
                    "headers": {"X-Forwarded-For": f"10.9.9.{idx}"},
                    "body": json.dumps({"email": "paciente@midoc.local", "password": "mal"}),
                },
                None,
            )
            self.assertEqual(res["statusCode"], 401)
        bloqueado = handler(
            {
                "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.10"}},
                "rawPath": "/api/auth/login",
                "headers": {"X-Forwarded-For": "10.9.9.99"},
                "body": json.dumps({"email": "paciente@midoc.local", "password": "mal"}),
            },
            None,
        )
        self.assertEqual(bloqueado["statusCode"], 429)


class AdaptadorLocal(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, body=None, path="/api/doctor/inventory/prueba"):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_delete_y_patch_llegan_a_autorizacion_en_lugar_de_501(self):
        status, body = self.request("DELETE")
        self.assertEqual(status, 401)
        self.assertIn("error", body)

        status_patch, body_patch = self.request("PATCH", body="{}")
        self.assertEqual(status_patch, 401)
        self.assertIn("error", body_patch)

    def test_json_invalido_produce_400_en_lugar_de_cerrar_conexion(self):
        status, body = self.request("POST", "{invalid")
        self.assertEqual(status, 400)
        self.assertIn("JSON", body["error"])

    def test_local_usa_threading_http_server_para_concurrencia(self):
        self.assertIs(local.ThreadingHTTPServer, ThreadingHTTPServer)
        resultados = []

        def worker():
            resultados.append(self.request("GET", path="/health"))

        hilos = [threading.Thread(target=worker) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=3)
        self.assertEqual(len(resultados), 4)
        self.assertTrue(all(st == 200 and body["status"] == "ok" for st, body in resultados))


if __name__ == "__main__":
    unittest.main()
