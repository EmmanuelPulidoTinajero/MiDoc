"""Pruebas del módulo de métricas EMF (sin AWS)."""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import metricas  # noqa: E402


class ValoresPorPeticion(unittest.TestCase):
    def test_peticion_normal_solo_reporta_latencia_y_cero_errores(self):
        valores = metricas.de_peticion("GET", "/api/doctors?specialty=x", 200, 12.3456)
        self.assertEqual(valores, {"RequestLatencyMs": 12.35, "ServerErrors": 0})

    def test_error_5xx_marca_server_errors(self):
        self.assertEqual(metricas.de_peticion("GET", "/api/records", 500, 5)["ServerErrors"], 1)
        self.assertEqual(metricas.de_peticion("GET", "/api/records", 503, 5)["ServerErrors"], 1)
        self.assertEqual(metricas.de_peticion("GET", "/api/records", 404, 5)["ServerErrors"], 0)

    def test_cita_creada_solo_con_201(self):
        self.assertEqual(metricas.de_peticion("POST", "/api/appointments", 201, 1)["AppointmentsCreated"], 1)
        self.assertNotIn("AppointmentsCreated", metricas.de_peticion("POST", "/api/appointments", 409, 1))
        self.assertNotIn("AppointmentsCreated", metricas.de_peticion("GET", "/api/appointments", 200, 1))

    def test_consulta_registrada_solo_con_201(self):
        self.assertEqual(metricas.de_peticion("POST", "/api/consultations", 201, 1)["ConsultationsRegistered"], 1)
        self.assertNotIn("ConsultationsRegistered", metricas.de_peticion("POST", "/api/consultations", 403, 1))

    def test_login_fallido_solo_con_401(self):
        self.assertEqual(metricas.de_peticion("POST", "/api/auth/login", 401, 1)["LoginFailures"], 1)
        self.assertNotIn("LoginFailures", metricas.de_peticion("POST", "/api/auth/login", 200, 1))

    def test_ruta_con_diagonal_final_se_normaliza(self):
        self.assertEqual(metricas.de_peticion("POST", "/api/appointments/", 201, 1)["AppointmentsCreated"], 1)


class RegistroEmf(unittest.TestCase):
    def test_estructura_emf_valida(self):
        registro = metricas.construir_registro(
            {"RequestLatencyMs": 40.5, "ServerErrors": 0, "LoginFailures": 1}, marca_ms=1_700_000_000_000)
        declaracion = registro["_aws"]["CloudWatchMetrics"][0]
        self.assertEqual(registro["_aws"]["Timestamp"], 1_700_000_000_000)
        self.assertEqual(declaracion["Namespace"], "MiDoc")
        self.assertEqual(declaracion["Dimensions"], [["Service"]])
        self.assertEqual(
            declaracion["Metrics"],
            [{"Name": "RequestLatencyMs", "Unit": "Milliseconds"},
             {"Name": "ServerErrors", "Unit": "Count"},
             {"Name": "LoginFailures", "Unit": "Count"}])
        # EMF exige que cada métrica declarada y la dimensión existan en la raíz del documento
        self.assertEqual(registro["Service"], "midoc-api")
        for metrica in declaracion["Metrics"]:
            self.assertIn(metrica["Name"], registro)

    def test_todas_las_metricas_tienen_unidad(self):
        valores = {"RequestLatencyMs": 1, "ServerErrors": 1, "AppointmentsCreated": 1,
                   "ConsultationsRegistered": 1, "LoginFailures": 1}
        self.assertEqual(set(valores), set(metricas.UNIDADES))
        metricas.construir_registro(valores)


class Habilitacion(unittest.TestCase):
    def emitir(self, entorno):
        salida = io.StringIO()
        with patch.dict(os.environ, entorno, clear=True), contextlib.redirect_stdout(salida):
            metricas.registrar_peticion("GET", "/health", 200, 3)
        return salida.getvalue()

    def test_no_emite_fuera_de_produccion(self):
        self.assertEqual(self.emitir({}), "")
        self.assertEqual(self.emitir({"NODE_ENV": "test"}), "")

    def test_emite_una_linea_json_en_produccion(self):
        texto = self.emitir({"NODE_ENV": "production"})
        self.assertEqual(len(texto.strip().splitlines()), 1)
        self.assertEqual(json.loads(texto)["Service"], "midoc-api")

    def test_variable_explicita_tiene_prioridad(self):
        self.assertNotEqual(self.emitir({"METRICS_ENABLED": "true"}), "")
        self.assertEqual(self.emitir({"NODE_ENV": "production", "METRICS_ENABLED": "false"}), "")

    def test_un_error_al_emitir_no_se_propaga(self):
        with patch.dict(os.environ, {"METRICS_ENABLED": "true"}, clear=True), \
                patch.object(metricas, "construir_registro", side_effect=RuntimeError("falla")), \
                self.assertLogs(metricas.logger, level="WARNING"):
            metricas.registrar_peticion("GET", "/health", 200, 3)


class MetricasEnLambda(unittest.TestCase):
    """El handler de Lambda emite exactamente un documento EMF por petición HTTP."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from src import app  # noqa: F401  (agrega src/ a sys.path como en producción)
        from src.lambda_function import handler
        cls.handler = staticmethod(handler)

    def invocar(self, evento):
        salida = io.StringIO()
        with patch.dict(os.environ, {"METRICS_ENABLED": "true", "NODE_ENV": "test"}), \
                contextlib.redirect_stdout(salida):
            respuesta = self.handler(evento, None)
        lineas = [json.loads(linea) for linea in salida.getvalue().splitlines() if linea.startswith("{")]
        return respuesta, lineas

    def test_health_emite_latencia_y_cero_errores(self):
        respuesta, lineas = self.invocar({"httpMethod": "GET", "path": "/health"})
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertEqual(len(lineas), 1)
        self.assertEqual(lineas[0]["ServerErrors"], 0)
        self.assertGreaterEqual(lineas[0]["RequestLatencyMs"], 0)

    def test_login_rechazado_cuenta_como_login_fallido(self):
        evento = {"httpMethod": "POST", "path": "/api/auth/login",
                  "body": json.dumps({"email": "paciente@midoc.local", "password": "incorrecta"})}
        respuesta, lineas = self.invocar(evento)
        self.assertEqual(respuesta["statusCode"], 401)
        self.assertEqual(lineas[0]["LoginFailures"], 1)

    def test_login_correcto_no_cuenta_como_fallo(self):
        evento = {"httpMethod": "POST", "path": "/api/auth/login",
                  "body": json.dumps({"email": "paciente@midoc.local", "password": "paciente-demo"})}
        respuesta, lineas = self.invocar(evento)
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertNotIn("LoginFailures", lineas[0])

    def test_sin_metricas_fuera_de_produccion_la_respuesta_no_cambia(self):
        salida = io.StringIO()
        with patch.dict(os.environ, {"NODE_ENV": "test"}, clear=False), contextlib.redirect_stdout(salida):
            os.environ.pop("METRICS_ENABLED", None)
            respuesta = self.handler({"httpMethod": "GET", "path": "/health"}, None)
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertEqual(salida.getvalue(), "")


if __name__ == "__main__":
    unittest.main()