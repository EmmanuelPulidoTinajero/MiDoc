"""Pruebas de consultas SQL parametrizadas y transacciones en RepoPostgres."""
import sys
import unittest
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import flujos  # noqa: E402
import metricas  # noqa: E402
import reglas  # noqa: E402


class RepoPostgresSqlTests(unittest.TestCase):
    def _repo_con_cursor(self, side_effects=None):
        app = MagicMock()
        conexion = app._database_connection.return_value
        cursor = conexion.cursor.return_value.__enter__.return_value
        cursor.description = True
        if side_effects is not None:
            cursor.fetchall.side_effect = side_effects
            cursor.fetchone.side_effect = side_effects
        repo = flujos.RepoPostgres(app)
        return repo, app, conexion, cursor

    def test_activar_suscripcion_stripe_usa_advisory_lock_y_actualiza_pendiente(self):
        sub_row = (
            "sub-1", "doc-1", "PENDIENTE", Decimal("20.00"), date(2026, 10, 19), date(2026, 10, 19),
            None, None, "cs_test_123", "cs_test_123", None, "test", None,
        )
        sub_activa = (
            "sub-1", "doc-1", "ACTIVA", Decimal("20.00"), date(2026, 10, 19), date(2026, 11, 17),
            "VISA", "4242", "cs_test_123", "cs_test_123", "pi_123", "test", datetime(2026, 10, 19, tzinfo=timezone.utc),
        )
        repo, _, conexion, cursor = self._repo_con_cursor([
            [sub_row],     # suscripcion_por_sesion (existente PENDIENTE)
            [],            # suscripciones(doc-1)
            [sub_activa],  # suscripcion_por_sesion final
        ])
        with repo.atomic("stripe-webhook"):
            pago, activada = repo.activar_suscripcion_stripe(
                "doc-1", "cs_test_123", "pi_123", Decimal("20.00"), "VISA", "4242", "test",
            )
        self.assertTrue(activada)
        self.assertEqual(pago["status"], "ACTIVA")
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("pg_advisory_xact_lock(hashtext(%s))" in s for s in sqls))
        self.assertTrue(any("UPDATE suscripcion SET estado = 'ACTIVA'" in s for s in sqls))
        conexion.commit.assert_called_once()

    def test_actualizar_documento_receta_y_leer_receta(self):
        row = (
            "rx-1", "pac-1", "doc-1", "Diagnóstico", "Tratamiento",
            datetime(2026, 10, 19, 10, 0, tzinfo=reglas.ZONA), "Dra. Ana", "General",
            "recetas/rx-1.pdf", "con-1", "Paciente Demo",
        )
        repo, _, _, cursor = self._repo_con_cursor([[row]])
        with repo.atomic("doc-user"):
            repo.actualizar_documento_receta("rx-1", "recetas/rx-1.pdf")
            rec = repo.receta("rx-1")
        self.assertEqual(rec["documentKey"], "recetas/rx-1.pdf")
        self.assertEqual(rec["consultationId"], "con-1")
        self.assertEqual(rec["patientName"], "Paciente Demo")
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("UPDATE receta SET documento_url = %s WHERE id = %s" in s for s in sqls))

    def test_actualizar_perfil_actualiza_usuario_y_perfil_doctor(self):
        user_row = ("u-1", "doc@midoc.mx", "DOCTOR", "Dr. Nuevo", "3311223344", "doc-1", "hash")
        repo, _, _, cursor = self._repo_con_cursor([[user_row]])
        with repo.atomic("u-1"):
            res = repo.actualizar_perfil(
                "u-1",
                "doc-1",
                "Dr. Nuevo",
                "3311223344",
                "newhash",
                {
                    "name": "Dr. Nuevo",
                    "specialty": "Pediatría",
                    "location": "Av. 1",
                    "city": "GDL",
                    "description": "Bio nueva",
                    "price": Decimal("800.00"),
                    "durationMin": 30,
                },
            )
        self.assertEqual(res["name"], "Dr. Nuevo")
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("UPDATE usuario SET nombre = COALESCE(%s, nombre)" in s for s in sqls))
        self.assertTrue(any("UPDATE perfil_doctor SET nombre_completo" in s for s in sqls))

    def test_accesos_expediente_postgres_y_fallback_dynamodb(self):
        # Caso 1: PostgreSQL devuelve bitácora directamente
        pg_rows = [("acc-1", "u-doc-1", "Dra. Ana", "DOCTOR", "Familiar", datetime(2026, 10, 19, tzinfo=timezone.utc))]
        repo, _, _, _ = self._repo_con_cursor([[pg_rows[0]]])
        with repo.atomic("u-pac-1"):
            items = repo.accesos_expediente("u-pac-1")
        self.assertEqual(items[0]["actorName"], "Dra. Ana")

        # Caso 2: PostgreSQL vacío, DynamoDB falla -> devuelve [] y emite DynamoAuditErrors
        repo2, _, _, _ = self._repo_con_cursor([[]])
        with patch.object(flujos.servicios_aws, "listar_accesos", side_effect=RuntimeError("ddb down")), \
                patch.object(metricas, "registrar_metrica") as met_mock:
            with repo2.atomic("u-pac-1"):
                items2 = repo2.accesos_expediente("u-pac-1")
        self.assertEqual(items2, [])
        met_mock.assert_called_once_with("DynamoAuditErrors", 1)

    def test_ver_expediente_y_generar_recordatorios_son_transaccionales(self):
        app = MagicMock()
        app._database_ready.return_value = True
        conexion = app._database_connection.return_value
        cursor = conexion.cursor.return_value.__enter__.return_value
        cursor.description = True
        cursor.fetchall.return_value = []

        res = flujos.generar_recordatorios(app)
        self.assertEqual(res, {"processedUsers": 0, "status": "ok"})
        conexion.commit.assert_called_once()
        self.assertTrue(any("job:generar_recordatorios" in str(call.args) for call in cursor.execute.call_args_list))

        app2 = MagicMock()
        app2._database_ready.return_value = True
        con2 = app2._database_connection.return_value
        cur2 = con2.cursor.return_value.__enter__.return_value
        cur2.description = True
        cur2.fetchall.side_effect = [
            [("u-pac-1", "pac@midoc.mx", "PACIENTE", "Pac", None, None, "h")],
            [],
            [],
        ]
        app2._response.return_value = {"statusCode": 200, "body": "{}"}
        flujos.ver_expediente(app2, {"sub": "u-pac-1", "role": "PACIENTE"}, {})
        con2.commit.assert_called_once()

    def test_buscar_doctores_lote_sql(self):
        doc_row = ("doc-1", "u-1", "Dra. Ana", "Familiar", "GDL", "GDL", "Bio", Decimal("600.00"), 30, "DOCTOR")
        promo_row = ("doc-1", "p-1", "Promo", "Desc", 10, date(2026, 10, 1), date(2026, 10, 30), True)
        sched_row = ("doc-1", 1, time(9, 0), time(12, 0))
        app = MagicMock()
        app._database_ready.return_value = True
        app._query.side_effect = [[doc_row], [promo_row], [sched_row], []]
        app._response.side_effect = lambda status, body: {"statusCode": status, "body": body}
        resp = flujos.buscar_doctores(app, {"sort": "availability"})
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(resp["body"]["data"][0]["promotionSummary"]["maxDiscountPercent"], 10)
        self.assertEqual(app._query.call_count, 4)

    def test_idempotencia_por_usuario_y_clave_y_fallo_login_atomico(self):
        repo, _, conexion, cursor = self._repo_con_cursor([[("hash-1", 201, '{"data":{"id":"a-1"}}')]])
        with repo.atomic("u-1"):
            prev = repo.obtener_idempotencia("u-1", "POST /api/messages", "idem-1")
            repo.guardar_idempotencia("u-1", "POST /api/appointments", "idem-1", "hash-1", 201, "{}")
            repo.registrar_fallo_login("clave-1", datetime(2026, 10, 19, tzinfo=timezone.utc), 5, 300, 300)
        self.assertEqual(prev["statusCode"], 201)
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        sel_idem = next(s for s in sqls if "FROM clave_idempotencia" in s)
        self.assertIn("WHERE usuario_id = %s AND clave = %s", sel_idem)
        self.assertNotIn("ruta = %s", sel_idem)
        ins_idem = next(s for s in sqls if "INSERT INTO clave_idempotencia" in s)
        self.assertIn("ON CONFLICT (usuario_id, clave) DO NOTHING", ins_idem)
        ins_login = next(s for s in sqls if "INSERT INTO intento_login" in s)
        self.assertIn("ON CONFLICT (clave) DO UPDATE", ins_login)
        conexion.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
