"""Tier 1 F06: Private S3 Clinical Documents (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_patient,
    s3_is_configured,
)


class TestTier1F06Documents(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()
        self.s3_ready = s3_is_configured(self.ctx)

    def _assert_local_s3_unconfigured(self, p_tok: str, name: str, ctype: str, raw: bytes) -> None:
        req = self.client.post(
            "/api/records/documents",
            {"name": name, "contentType": ctype, "size": len(raw)},
            token=p_tok,
        )
        self.assertEqual(req.status, 503, req.text)
        self.assertIn("almacenamiento", (req.error or "").lower())
        listed = self.client.get("/api/records/documents", token=p_tok)
        self.assertEqual(listed.status, 503, listed.text)

    def _upload_doc(self, p_tok: str, name: str, ctype: str, raw: bytes) -> dict:
        req = self.client.post(
            "/api/records/documents",
            {"name": name, "contentType": ctype, "size": len(raw)},
            token=p_tok,
        )
        self.assertEqual(req.status, 201, req.text)
        self.assertEqual(req.data.get("expiresIn"), 300)
        up = self.client.upload_presigned_post(req.data["url"], req.data["fields"], name, ctype, raw)
        self.assertIn(up.status, (200, 201, 204), up.text)
        return req.data

    def test_t1_f06_01_upload_clinical_pdf_and_verify_download_bytes(self) -> None:
        p_tok, _ = register_patient(self.client)
        pdf = b"%PDF-1.4\n% E2E lab report\n%%EOF\n"
        if not self.s3_ready:
            self._assert_local_s3_unconfigured(p_tok, "lab-result.pdf", "application/pdf", pdf)
            return
        up = self._upload_doc(p_tok, "lab-result.pdf", "application/pdf", pdf)
        docs = self.client.get("/api/records/documents", token=p_tok)
        self.assertEqual(docs.status, 200, docs.text)
        match = next(d for d in docs.data if d["id"] == up["id"])
        dl = self.client.download_url(match["downloadUrl"])
        self.assertEqual(dl.status, 200)
        self.assertEqual(dl.body_bytes, pdf)

    def test_t1_f06_02_upload_jpg_and_png_images(self) -> None:
        p_tok, _ = register_patient(self.client)
        jpg = b"\xff\xd8\xff\xe0E2E-JPG"
        png = b"\x89PNG\r\n\x1a\nE2E-PNG"
        if not self.s3_ready:
            self._assert_local_s3_unconfigured(p_tok, "placa.jpg", "image/jpeg", jpg)
            return
        j_up = self._upload_doc(p_tok, "placa.jpg", "image/jpeg", jpg)
        p_up = self._upload_doc(p_tok, "estudio.png", "image/png", png)
        docs = self.client.get("/api/records/documents", token=p_tok)
        ids = {d["id"]: d for d in docs.data}
        self.assertIn(j_up["id"], ids)
        self.assertIn(p_up["id"], ids)
        self.assertEqual(self.client.download_url(ids[j_up["id"]]["downloadUrl"]).body_bytes, jpg)
        self.assertEqual(self.client.download_url(ids[p_up["id"]]["downloadUrl"]).body_bytes, png)

    def test_t1_f06_03_upload_dicom_with_application_dicom_mime(self) -> None:
        p_tok, _ = register_patient(self.client)
        dcm = b"DICM-SYNTHETIC-E2E-PAYLOAD"
        if not self.s3_ready:
            self._assert_local_s3_unconfigured(p_tok, "rx-torax.dcm", "application/dicom", dcm)
            return
        up = self._upload_doc(p_tok, "rx-torax.dcm", "application/dicom", dcm)
        docs = self.client.get("/api/records/documents", token=p_tok)
        match = next(d for d in docs.data if d["id"] == up["id"])
        self.assertEqual(self.client.download_url(match["downloadUrl"]).body_bytes, dcm)

    def test_t1_f06_04_authorized_doctor_lists_and_downloads_patient_document(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        pdf = b"%PDF-1.4\n% Doc for doctor\n%%EOF\n"
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        if not self.s3_ready:
            self._assert_local_s3_unconfigured(p_tok, "eco.pdf", "application/pdf", pdf)
            doc_list = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok)
            self.assertEqual(doc_list.status, 503, doc_list.text)
            return
        up = self._upload_doc(p_tok, "eco.pdf", "application/pdf", pdf)
        docs = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertEqual(docs.status, 200, docs.text)
        match = next(d for d in docs.data if d["id"] == up["id"])
        self.assertEqual(self.client.download_url(match["downloadUrl"]).body_bytes, pdf)

    def test_t1_f06_05_patient_deletes_own_document(self) -> None:
        p_tok, _ = register_patient(self.client)
        pdf = b"%PDF-1.4\n%%EOF\n"
        if not self.s3_ready:
            self._assert_local_s3_unconfigured(p_tok, "borrar.pdf", "application/pdf", pdf)
            return
        up = self._upload_doc(p_tok, "borrar.pdf", "application/pdf", pdf)
        dele = self.client.delete(f"/api/records/documents/{up['id']}", token=p_tok)
        self.assertEqual(dele.status, 200, dele.text)
        self.assertTrue(dele.data.get("deleted"))
        docs = self.client.get("/api/records/documents", token=p_tok)
        self.assertFalse(any(d["id"] == up["id"] for d in docs.data))
