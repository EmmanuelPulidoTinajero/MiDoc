import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import metricas

MONITOREO = (RAIZ / "infrastructure" / "monitoring.tf").read_text(encoding="utf-8")

TRIPLE = re.compile(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"Service"\s*,\s*"([^"]+)"')
DESACTIVABLE = re.compile(r"count\s*=\s*var\.enable_monitoring\s*\?\s*1\s*:\s*0")


def _alarmas():
    bloques = MONITOREO.split('resource "aws_cloudwatch_metric_alarm"')[1:]
    return [bloque.split('resource "')[0] for bloque in bloques]


def _valor(bloque, nombre):
    encontrado = re.search(rf"^\s*{nombre}\s*=\s*(.+)$", bloque, re.MULTILINE)
    return encontrado.group(1).strip() if encontrado else None


class MonitoreoTests(unittest.TestCase):
    """Una alarma que apunta a una métrica inexistente nunca se dispara y el CI no lo nota."""

    def test_declara_exactamente_dos_alarmas(self):
        self.assertEqual(len(_alarmas()), 2)

    def test_namespace_y_dimension_coinciden_con_metricas(self):
        dimension = re.search(r'monitoreo_servicio\s*=\s*\{\s*Service\s*=\s*"([^"]+)"\s*\}', MONITOREO)
        self.assertIsNotNone(dimension, "no se encontró la dimensión Service de las alarmas")
        self.assertEqual(dimension.group(1), metricas.SERVICIO)
        for alarma in _alarmas():
            self.assertEqual(_valor(alarma, "namespace"), f'"{metricas.NAMESPACE}"')

    def test_las_alarmas_apuntan_a_metricas_emitidas(self):
        emitidas = {f'"{nombre}"' for nombre in metricas.UNIDADES}
        for alarma in _alarmas():
            self.assertIn(_valor(alarma, "metric_name"), emitidas)

    def test_cada_alarma_puede_disparar(self):
        for alarma in _alarmas():
            estadisticos = [clave for clave in ("statistic", "extended_statistic") if _valor(alarma, clave)]
            self.assertEqual(len(estadisticos), 1, "se requiere exactamente una de statistic/extended_statistic")
            self.assertGreaterEqual(int(_valor(alarma, "evaluation_periods")), 1)
            self.assertGreater(int(_valor(alarma, "threshold")), 0)
            self.assertIsNotNone(_valor(alarma, "period"))
            self.assertIsNotNone(_valor(alarma, "comparison_operator"))
            self.assertIn(_valor(alarma, "treat_missing_data").strip('"'),
                          {"notBreaching", "breaching", "missing", "ignore"})

    def test_los_recursos_de_monitoreo_se_pueden_desactivar(self):
        self.assertEqual(len(DESACTIVABLE.findall(MONITOREO)), 3)

    def test_el_dashboard_muestra_las_cinco_metricas(self):
        del_dashboard = {
            metrica for namespace, metrica, servicio in TRIPLE.findall(MONITOREO)
            if namespace == metricas.NAMESPACE and servicio == metricas.SERVICIO
        }
        self.assertEqual(del_dashboard, set(metricas.UNIDADES))


if __name__ == "__main__":
    unittest.main()
