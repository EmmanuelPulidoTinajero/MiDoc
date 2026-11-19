"""Pruebas para generación pura de PDF 1.4 de recetas y almacenamiento S3."""
import copy
import json
import os
import re
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app  # noqa: E402
import flujos  # noqa: E402
import pdf_receta  # noqa: E402
import reglas  # noqa: E402
import servicios_aws  # noqa: E402

DB_ORIGINAL = copy.deepcopy(app.DB)
AHORA = datetime(2026, 10, 19, 8, 0, tzinfo=reglas.ZONA)


class PdfRecetaTests(unittest.TestCase):
    def test_genera_pdf_14_con_xref_valido_y_acentos_winansi(self):
        pdf = pdf_receta.generar_pdf_receta(
            receta_id="rx-12345",
            consulta_id="con-67890",
            fecha_emision="19/10/2026 10:00 UTC-6",
            doctor_nombre="Dra. Ana López (Cédula 12345)",
            especialidad="Medicina familiar",
            paciente_nombre="José Ñoño",
            diagnostico="Diagnóstico: faringitis aguda (leve) \\ control",
            tratamiento="Tomar paracetamol 500 mg cada 8 horas por 5 días.\nHidratación abundante.",
            notas="Revisar temperatura cada 12 horas.",
            ubicacion="Guadalajara, Jal.",
        )
        self.assertTrue(pdf.startswith(b"%PDF-1.4\n"))
        self.assertTrue(pdf.endswith(b"%%EOF\n"))
        self.assertIn(b"/Type /Catalog", pdf)
        self.assertIn(b"/Type /Pages", pdf)
        self.assertIn(b"/Encoding /WinAnsiEncoding", pdf)
        # Escapado correcto de paréntesis y barra invertida
        self.assertIn(b"\\(leve\\)", pdf)
        self.assertIn(b"\\\\", pdf)
        # Caracteres en WinAnsi cp1252
        self.assertIn("Diagnóstico".encode("cp1252"), pdf)
        self.assertIn("Dra. Ana López".encode("cp1252"), pdf)

        # Verifica startxref y cada offset en la tabla xref
        m = re.search(rb"startxref\n(\d+)\n%%EOF\n$", pdf)
        self.assertIsNotNone(m)
        xref_pos = int(m.group(1))
        self.assertTrue(pdf[xref_pos:].startswith(b"xref\n"))
        entradas = re.findall(rb"^(\d{10}) 00000 n $", pdf[xref_pos:], flags=re.MULTILINE)
        self.assertGreaterEqual(len(entradas), 6)
        for obj_num, offset_bytes in enumerate(entradas, start=1):
            offset = int(offset_bytes)
            self.assertTrue(pdf[offset:].startswith(f"{obj_num} 0 obj\n".encode("ascii")))

    def test_paginacion_multipagina_en_tratamiento_largo(self):
        largo = "\n".join(f"Indicación clínica número {i}: continuar esquema por 7 días." for i in range(1, 90))
        pdf = pdf_receta.generar_pdf_receta(
            receta_id="rx-multi",
            consulta_id="con-multi",
            fecha_emision="19/10/2026 10:00 UTC-6",
            doctor_nombre="Dra. Ana López",
            especialidad="Medicina familiar",
            paciente_nombre="Paciente Demo",
            diagnostico="Control integral",
            tratamiento=largo,
        )
        m_count = re.search(rb"/Count (\d+)", pdf)
        self.assertIsNotNone(m_count)
        self.assertGreaterEqual(int(m_count.group(1)), 2)
        self.assertIn(b"\\(cont.\\)", pdf)

    def test_metadatos_largos_se_envuelven_sin_recortarse(self):
        pdf = pdf_receta.generar_pdf_receta(
            receta_id="rx-wrap",
            consulta_id="con-wrap",
            fecha_emision="19/10/2026 10:00 UTC-6",
            doctor_nombre="Dr. Alejandro Maximiliano Fernández de la Garza y Villalobos",
            especialidad="Medicina Interna y Cardiología Preventiva",
            paciente_nombre="Paciente Demo",
            diagnostico="Control",
            tratamiento="Reposo",
            ubicacion="Av. Paseo de la Reforma 1234 Piso 15 Consultorio 1502 Col. Juárez Cuauhtémoc CDMX",
        )
        self.assertTrue(pdf.startswith(b"%PDF-1.4\n"))
        self.assertTrue(pdf.endswith(b"%%EOF\n"))
        self.assertIn(b"Cuauht", pdf)


class RecetaS3IntegracionTests(unittest.TestCase):
    def setUp(self):
        app.DB.clear()
        app.DB.update(copy.deepcopy(DB_ORIGINAL))
        flujos.reset_rate_limits(app.DB)
        ahora_orig = reglas.ahora
        reglas.ahora = lambda: AHORA
        self.addCleanup(setattr, reglas, "ahora", ahora_orig)

    def test_subir_y_presignar_receta_s3(self):
        s3_mock = MagicMock()
        s3_mock.generate_presigned_url.return_value = "https://s3.example.com/recetas/rx-1.pdf?sig=abc"
        boto3_mock = MagicMock()
        boto3_mock.client.return_value = s3_mock

        with patch.dict(os.environ, {"MEDICAL_DOCUMENTS_BUCKET": "midoc-docs"}, clear=True), \
                patch.dict(sys.modules, {"boto3": boto3_mock}):
            key = servicios_aws.subir_receta_pdf("rx-1", b"%PDF-1.4\n%%EOF\n")
            self.assertEqual(key, "recetas/rx-1.pdf")
            s3_mock.put_object.assert_called_once_with(
                Bucket="midoc-docs",
                Key="recetas/rx-1.pdf",
                Body=b"%PDF-1.4\n%%EOF\n",
                ContentType="application/pdf",
                ServerSideEncryption="AES256",
            )
            url = servicios_aws.url_descarga_receta(key, "rx-1")
            self.assertEqual(url, "https://s3.example.com/recetas/rx-1.pdf?sig=abc")
            s3_mock.generate_presigned_url.assert_called_once()
            self.assertEqual(s3_mock.generate_presigned_url.call_args.kwargs["ExpiresIn"], 300)

    def test_fallo_s3_emite_metrica_y_revierte_consulta(self):
        s3_mock = MagicMock()
        s3_mock.put_object.side_effect = RuntimeError("S3 down")
        boto3_mock = MagicMock()
        boto3_mock.client.return_value = s3_mock

        p_tok = json.loads(app.handle("POST", "/api/auth/login", body={"email": "paciente@midoc.local", "password": "paciente-demo"})["body"])["token"]
        d_tok = json.loads(app.handle("POST", "/api/auth/login", body={"email": "doctor@midoc.local", "password": "doctor-demo"})["body"])["token"]
        app.handle("POST", "/api/consents", {"authorization": f"Bearer {p_tok}"}, {"doctorId": "d-1", "granted": True})

        cita_resp = app.handle(
            "POST",
            "/api/appointments",
            {"authorization": f"Bearer {p_tok}"},
            {"doctorId": "d-1", "dateTime": "2026-10-19T09:00:00-06:00"},
        )
        self.assertEqual(cita_resp["statusCode"], 201, cita_resp["body"])
        cita = json.loads(cita_resp["body"])["data"]

        reglas.ahora = lambda: AHORA.replace(hour=10)
        snapshot = copy.deepcopy(app.DB)
        with patch.dict(os.environ, {"DOCUMENTS_BUCKET": "midoc-docs", "METRICS_ENABLED": "true"}, clear=False), \
                patch.dict(sys.modules, {"boto3": boto3_mock}), \
                patch("builtins.print") as print_mock:
            res = app.handle(
                "POST",
                "/api/consultations",
                {"authorization": f"Bearer {d_tok}"},
                {"patientId": "u-patient-1", "appointmentId": cita["id"], "diagnosis": "Gripe", "treatment": "Reposo"},
            )
            self.assertEqual(res["statusCode"], 503)
            self.assertEqual(app.DB, snapshot)
            self.assertTrue(any("DocumentOpsErrors" in str(c) for c in print_mock.call_args_list))

        s3_mock.put_object.side_effect = None
        s3_mock.generate_presigned_url.return_value = "https://s3.example.com/presigned-rx"
        with patch.dict(os.environ, {"MEDICAL_DOCUMENTS_BUCKET": "midoc-docs"}, clear=False), \
                patch.dict(sys.modules, {"boto3": boto3_mock}):
            ok = app.handle(
                "POST",
                "/api/consultations",
                {"authorization": f"Bearer {d_tok}"},
                {"patientId": "u-patient-1", "appointmentId": cita["id"], "diagnosis": "Gripe", "treatment": "Reposo"},
            )
            self.assertEqual(ok["statusCode"], 201)
            cdata = json.loads(ok["body"])["data"]
            self.assertTrue(cdata["hasPdf"])
            self.assertTrue(cdata["documentKey"].startswith("recetas/"))
            self.assertEqual(cdata["downloadUrl"], "https://s3.example.com/presigned-rx")

            rx = app.handle("GET", f"/api/prescriptions/{cdata['prescriptionId']}", {"authorization": f"Bearer {p_tok}"})
            self.assertEqual(rx["statusCode"], 200)
            rx_data = json.loads(rx["body"])["data"]
            self.assertTrue(rx_data["hasPdf"])
            self.assertEqual(rx_data["downloadUrl"], "https://s3.example.com/presigned-rx")


if __name__ == "__main__":
    unittest.main()
