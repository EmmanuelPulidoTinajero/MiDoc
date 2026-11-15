import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import app


class AuditoriaTests(unittest.TestCase):
    """La auditoría en DynamoDB es complementaria: PostgreSQL guarda la bitácora transaccional."""

    def test_un_fallo_de_dynamodb_no_rompe_la_lectura_autorizada(self):
        fallo = RuntimeError("tabla ausente")
        with mock.patch.object(app.servicios_aws, "registrar_acceso", side_effect=fallo):
            app._audit_record_access("u-patient-1", "u-doctor-1")

    def test_la_auditoria_exitosa_registra_el_acceso_una_vez(self):
        with mock.patch.object(app.servicios_aws, "registrar_acceso") as registrar:
            app._audit_record_access("u-patient-1", "u-doctor-1")
        registrar.assert_called_once_with("u-patient-1", "u-doctor-1")


if __name__ == "__main__":
    unittest.main()
