import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import metricas

MONITOREO = (RAIZ / "infrastructure" / "monitoring.tf").read_text(encoding="utf-8")
LAMBDA_TF = (RAIZ / "infrastructure" / "lambda.tf").read_text(encoding="utf-8")

TRIPLE = re.compile(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*([^,\]]+)')
BLOCK_SPLIT = re.compile(r'^(?=resource "|output "|variable "|locals\s*\{)', re.MULTILINE)

PLANNED_EVENT_METRICS = {
    "RemindersJobRuns",
    "RemindersJobErrors",
    "PaymentCheckoutCreated",
    "PaymentSucceeded",
    "PaymentFailed",
    "DocumentOpsErrors",
    "DynamoAuditErrors",
}


def _todas_las_metricas_midoc():
    combinadas = getattr(metricas, "TODAS_LAS_UNIDADES", None)
    if combinadas is not None:
        return set(combinadas)
    return set(metricas.UNIDADES) | PLANNED_EVENT_METRICS


def _bloques(texto, tipo_recurso):
    partes = BLOCK_SPLIT.split(texto)
    prefijo = f'resource "{tipo_recurso}"'
    return [parte for parte in partes if parte.lstrip().startswith(prefijo)]


def _valor(bloque, nombre):
    encontrado = re.search(rf"^\s*{nombre}\s*=\s*(.+)$", bloque, re.MULTILINE)
    return encontrado.group(1).strip() if encontrado else None


class MonitoreoTests(unittest.TestCase):
    """Valida alarmas MiDoc/AWS, SNS, Log Groups, Dashboard y Logs Insights en Terraform."""

    def test_declara_alarmas_aplicacion_e_infraestructura(self):
        alarmas = _bloques(MONITOREO, "aws_cloudwatch_metric_alarm")
        self.assertGreaterEqual(len(alarmas), 8)
        for alarma in alarmas:
            acciones = _valor(alarma, "alarm_actions")
            self.assertIsNotNone(acciones)
            self.assertIn("aws_sns_topic.alerts[0].arn", acciones)
            ok_acciones = _valor(alarma, "ok_actions")
            self.assertIsNotNone(ok_acciones)
            self.assertIn("aws_sns_topic.alerts[0].arn", ok_acciones)

    def test_namespaces_dimensiones_y_metricas_validas(self):
        dimension = re.search(r'monitoreo_servicio\s*=\s*\{\s*Service\s*=\s*"([^"]+)"\s*\}', MONITOREO)
        self.assertIsNotNone(dimension, "no se encontró la dimensión Service de las alarmas")
        self.assertEqual(dimension.group(1), metricas.SERVICIO)

        emitidas_midoc = {f'"{nombre}"' for nombre in _todas_las_metricas_midoc()}
        valid_lambda = {'"Errors"', '"Throttles"', '"Duration"', '"Invocations"'}
        valid_apigw = {'"5xx"', '"4xx"', '"Latency"', '"IntegrationLatency"', '"Count"'}
        valid_rds = {'"CPUUtilization"', '"FreeStorageSpace"', '"DatabaseConnections"'}

        namespaces_vistos = set()
        for alarma in _bloques(MONITOREO, "aws_cloudwatch_metric_alarm"):
            ns = (_valor(alarma, "namespace") or "").strip('"')
            metric_name = _valor(alarma, "metric_name")
            dims = _valor(alarma, "dimensions") or ""
            namespaces_vistos.add(ns)

            if ns == metricas.NAMESPACE:
                self.assertEqual(dims, "local.monitoreo_servicio")
                self.assertIn(metric_name, emitidas_midoc)
            elif ns == "AWS/Lambda":
                self.assertIn("FunctionName", dims)
                self.assertIn(metric_name, valid_lambda)
            elif ns == "AWS/ApiGateway":
                self.assertNotEqual(metric_name, '"5XXError"', "HTTP API v2 usa métrica '5xx', no '5XXError'")
                self.assertIn("ApiId", dims)
                self.assertIn(metric_name, valid_apigw)
            elif ns == "AWS/RDS":
                self.assertIn("DBInstanceIdentifier", dims)
                self.assertIn(metric_name, valid_rds)
                cuenta = _valor(alarma, "count") or ""
                self.assertIn("var.enable_rds", cuenta)
            else:
                self.fail(f"Namespace inesperado en alarma: {ns!r}")

        self.assertEqual(namespaces_vistos, {metricas.NAMESPACE, "AWS/Lambda", "AWS/ApiGateway", "AWS/RDS"})

    def test_cada_alarma_puede_disparar(self):
        for alarma in _bloques(MONITOREO, "aws_cloudwatch_metric_alarm"):
            estadisticos = [clave for clave in ("statistic", "extended_statistic") if _valor(alarma, clave)]
            self.assertEqual(len(estadisticos), 1, "se requiere exactamente una de statistic/extended_statistic")
            self.assertGreaterEqual(int(_valor(alarma, "evaluation_periods")), 1)
            umbral = _valor(alarma, "threshold")
            self.assertIsNotNone(umbral)
            self.assertGreaterEqual(float(umbral), 0)
            self.assertIsNotNone(_valor(alarma, "period"))
            self.assertIsNotNone(_valor(alarma, "comparison_operator"))
            self.assertIn(
                _valor(alarma, "treat_missing_data").strip('"'),
                {"notBreaching", "breaching", "missing", "ignore"},
            )

    def test_los_recursos_de_monitoreo_se_pueden_desactivar(self):
        tipos = (
            "aws_sns_topic",
            "aws_sns_topic_subscription",
            "aws_cloudwatch_metric_alarm",
            "aws_cloudwatch_dashboard",
            "aws_cloudwatch_query_definition",
        )
        total = 0
        for tipo in tipos:
            for bloque in _bloques(MONITOREO, tipo):
                total += 1
                cuenta = _valor(bloque, "count")
                self.assertIsNotNone(cuenta, f"Falta count en {tipo}")
                self.assertIn("var.enable_monitoring", cuenta)
        self.assertGreaterEqual(total, 13)

    def test_el_dashboard_muestra_metricas_aplicacion_e_infraestructura(self):
        triples = TRIPLE.findall(MONITOREO)
        del_dashboard_midoc = {
            metrica
            for namespace, metrica, dim_key, dim_val in triples
            if namespace == metricas.NAMESPACE and dim_key == "Service" and dim_val.strip('"') == metricas.SERVICIO
        }
        self.assertTrue(set(metricas.UNIDADES).issubset(del_dashboard_midoc))
        self.assertTrue(_todas_las_metricas_midoc().issubset(del_dashboard_midoc))

        namespaces_dashboard = {ns for ns, _, _, _ in triples}
        self.assertIn("AWS/Lambda", namespaces_dashboard)
        self.assertIn("AWS/ApiGateway", namespaces_dashboard)
        self.assertIn("AWS/RDS", namespaces_dashboard)

    def test_log_groups_access_logs_y_logs_insights(self):
        log_groups = _bloques(LAMBDA_TF, "aws_cloudwatch_log_group")
        self.assertGreaterEqual(len(log_groups), 2)
        nombres = {_valor(lg, "name") for lg in log_groups}
        self.assertTrue(any("/aws/lambda/" in (n or "") for n in nombres))
        self.assertTrue(any("/aws/apigateway/" in (n or "") for n in nombres))
        for lg in log_groups:
            self.assertIsNotNone(_valor(lg, "retention_in_days"))

        self.assertIn("access_log_settings", LAMBDA_TF)
        self.assertIn("aws_cloudwatch_log_group.apigw_http.arn", LAMBDA_TF)

        queries = _bloques(MONITOREO, "aws_cloudwatch_query_definition")
        self.assertGreaterEqual(len(queries), 3)


if __name__ == "__main__":
    unittest.main()
