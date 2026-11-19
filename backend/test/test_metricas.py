"""Pruebas del módulo de métricas EMF y logging JSON estructurado (sin AWS)."""
import contextlib
import io
import json
import logging
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

    def test_metricas_de_pago_stripe(self):
        self.assertEqual(
            metricas.de_peticion("POST", "/api/subscriptions/checkout", 201, 1)["PaymentCheckoutCreated"],
            1,
        )
        self.assertNotIn(
            "PaymentSucceeded",
            metricas.de_peticion("POST", "/api/subscriptions/confirm", 200, 1),
        )
        self.assertEqual(
            metricas.de_peticion("POST", "/api/subscriptions/confirm", 402, 1)["PaymentFailed"],
            1,
        )
        self.assertEqual(
            metricas.de_peticion("POST", "/api/webhooks/stripe", 401, 1)["PaymentFailed"],
            1,
        )

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
        valores = {
            "RequestLatencyMs": 1,
            "ServerErrors": 1,
            "AppointmentsCreated": 1,
            "ConsultationsRegistered": 1,
            "LoginFailures": 1,
        }
        self.assertEqual(set(valores), set(metricas.UNIDADES))
        metricas.construir_registro(valores)

        todas = {
            **valores,
            "RemindersJobRuns": 1,
            "RemindersJobErrors": 1,
            "PaymentCheckoutCreated": 1,
            "PaymentSucceeded": 1,
            "PaymentFailed": 1,
            "DocumentOpsErrors": 1,
            "DynamoAuditErrors": 1,
        }
        self.assertEqual(set(todas), set(metricas.TODAS_LAS_UNIDADES))
        doc = metricas.construir_registro(todas)
        self.assertEqual(len(doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]), 12)


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

    def test_registrar_metrica_individual_y_redaccion_json_logging(self):
        salida = io.StringIO()
        with patch.dict(os.environ, {"METRICS_ENABLED": "true"}, clear=True), contextlib.redirect_stdout(salida):
            metricas.registrar_metrica("RemindersJobRuns", 1)
        doc = json.loads(salida.getvalue())
        self.assertEqual(doc["RemindersJobRuns"], 1)

        # Redacción cero PII/secretos en JsonLogFormatter
        buf = io.StringIO()
        handler_log = logging.StreamHandler(buf)
        handler_log.setFormatter(metricas.JsonLogFormatter())
        log_test = logging.getLogger("midoc.http")
        prev_handlers = list(log_test.handlers)
        prev_prop = log_test.propagate
        log_test.handlers = [handler_log]
        log_test.propagate = False
        log_test.setLevel(logging.INFO)
        try:
            metricas.log_peticion(
                request_id="req-123",
                route="/api/auth/login",
                method="POST",
                status=200,
                duration_ms=14.25,
                user_role="PACIENTE",
            )
            metricas.log_evento(
                "WARNING",
                "Bearer tok123 sk_test_abc123 user@midoc.local password=secreto",
            )
        finally:
            log_test.handlers = prev_handlers
            log_test.propagate = prev_prop

        lineas = [json.loads(line) for line in buf.getvalue().splitlines()]
        self.assertEqual(lineas[0]["requestId"], "req-123")
        self.assertEqual(lineas[0]["userRole"], "PACIENTE")
        self.assertEqual(lineas[0]["status"], 200)
        self.assertNotIn("tok123", buf.getvalue())
        self.assertNotIn("sk_test_abc123", buf.getvalue())
        self.assertNotIn("user@midoc.local", buf.getvalue())
        self.assertNotIn("secreto", buf.getvalue())

    def test_log_evento_redacta_campos_anidados_y_passwords(self):
        buf = io.StringIO()
        handler_log = logging.StreamHandler(buf)
        handler_log.setFormatter(metricas.JsonLogFormatter())
        log_test = logging.getLogger("midoc.http")
        prev_handlers = list(log_test.handlers)
        prev_prop = log_test.propagate
        log_test.handlers = [handler_log]
        log_test.propagate = False
        log_test.setLevel(logging.INFO)
        try:
            metricas.log_evento(
                "INFO",
                "x",
                detail={
                    "email": "a@b.com",
                    "key": "sk_test_123",
                    "currentPassword": "My Secret Pass",
                    "nested": ["whsec_nested999", {"newPassword": "Other Secret"}],
                },
            )
        finally:
            log_test.handlers = prev_handlers
            log_test.propagate = prev_prop

        raw = buf.getvalue()
        lineas = raw.strip().splitlines()
        self.assertEqual(len(lineas), 1)
        doc = json.loads(lineas[0])
        self.assertEqual(doc["detail"]["email"], "[REDACTED_EMAIL]")
        self.assertEqual(doc["detail"]["key"], "[REDACTED_STRIPE_KEY]")
        self.assertEqual(doc["detail"]["currentPassword"], "[REDACTED]")
        self.assertNotIn("a@b.com", raw)
        self.assertNotIn("sk_test_123", raw)
        self.assertNotIn("My Secret Pass", raw)
        self.assertNotIn("whsec_nested999", raw)
        self.assertNotIn("Other Secret", raw)

    def test_error_no_controlado_en_app_emite_json_redactado_y_no_filtra_a_root(self):
        import app  # noqa: E402

        midoc_logger = logging.getLogger("midoc")
        root_logger = logging.getLogger()
        prev_midoc_handlers = list(midoc_logger.handlers)
        prev_midoc_level = midoc_logger.level
        prev_midoc_prop = midoc_logger.propagate
        prev_root_handlers = list(root_logger.handlers)
        prev_root_level = root_logger.level

        stderr_buf = io.StringIO()
        root_buf = io.StringIO()
        root_capture = logging.StreamHandler(root_buf)
        try:
            root_logger.handlers = [root_capture]
            root_logger.setLevel(logging.DEBUG)
            with contextlib.redirect_stderr(stderr_buf):
                metricas.configurar_logging()
                with patch.object(
                    app,
                    "_handle",
                    side_effect=RuntimeError(
                        "Stripe failed with sk_test_51Secret user@midoc.local password=Secret123"
                    ),
                ):
                    resp = app.handle("GET", "/health")
            self.assertEqual(resp["statusCode"], 500)
        finally:
            midoc_logger.handlers = prev_midoc_handlers
            midoc_logger.setLevel(prev_midoc_level)
            midoc_logger.propagate = prev_midoc_prop
            root_logger.handlers = prev_root_handlers
            root_logger.setLevel(prev_root_level)

        self.assertEqual(root_buf.getvalue(), "")
        lineas = stderr_buf.getvalue().strip().splitlines()
        self.assertEqual(len(lineas), 1)
        doc = json.loads(lineas[0])
        self.assertEqual(doc["level"], "ERROR")
        self.assertIn("traceback", doc)
        self.assertNotIn("sk_test_51Secret", lineas[0])
        self.assertNotIn("user@midoc.local", lineas[0])
        self.assertNotIn("Secret123", lineas[0])


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

    def test_recordatorios_emite_json_job_y_metricas(self):
        salida = io.StringIO()
        with patch.dict(os.environ, {"METRICS_ENABLED": "true", "NODE_ENV": "test"}), \
                contextlib.redirect_stdout(salida):
            res = self.handler({"source": "midoc.reminders"}, None)
        self.assertEqual(res["status"], "ok")
        lineas = [json.loads(line) for line in salida.getvalue().splitlines() if line.startswith("{")]
        self.assertTrue(any(l.get("RemindersJobRuns") == 1 for l in lineas))
        self.assertTrue(any(l.get("job") == "reminders" for l in lineas))

        salida_err = io.StringIO()
        with patch.dict(os.environ, {"METRICS_ENABLED": "true", "NODE_ENV": "test"}), \
                patch("flujos.generar_recordatorios", side_effect=RuntimeError("db fail")), \
                contextlib.redirect_stdout(salida_err):
            with self.assertRaises(RuntimeError):
                self.handler({"source": "midoc.reminders"}, None)
        lineas_err = [json.loads(line) for line in salida_err.getvalue().splitlines() if line.startswith("{")]
        self.assertTrue(any(l.get("RemindersJobErrors") == 1 for l in lineas_err))


if __name__ == "__main__":
    unittest.main()
