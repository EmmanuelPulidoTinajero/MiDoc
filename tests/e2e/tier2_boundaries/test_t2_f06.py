"""Tier 2 F06: S3 Clinical Document Validation & Security Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_patient,
    s3_is_configured,
)


class TestTier2F06DocumentBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f06_01_reject_oversized_and_zero_byte_documents(self) -> None:
        p_tok, _ = register_patient(self.client)
        over = self.client.post(
            "/api/records/documents",
            {"name": "huge.pdf", "contentType": "application/pdf", "size": 10 * 1024 * 1024 + 1},
            token=p_tok,
        )
        zero = self.client.post(
            "/api/records/documents",
            {"name": "empty.pdf", "contentType": "application/pdf", "size": 0},
            token=p_tok,
        )
        self.assertIn(over.status, (400, 413), over.text)
        self.assertIn(zero.status, (400, 413), zero.text)

    def test_t2_f06_02_reject_disallowed_mime_and_executable_extensions(self) -> None:
        p_tok, _ = register_patient(self.client)
        exe = self.client.post(
            "/api/records/documents",
            {"name": "malware.exe", "contentType": "application/x-msdownload", "size": 1024},
            token=p_tok,
        )
        svg = self.client.post(
            "/api/records/documents",
            {"name": "script.svg", "contentType": "image/svg+xml", "size": 1024},
            token=p_tok,
        )
        self.assertIn(exe.status, (400, 415))
        self.assertIn(svg.status, (400, 415))

    def test_t2_f06_03_cross_patient_document_delete_and_list_forbidden(self) -> None:
        p1_tok, p1 = register_patient(self.client)
        p2_tok, _ = register_patient(self.client)
        raw = b"%PDF-1.4\n%%EOF\n"
        req = self.client.post(
            "/api/records/documents",
            {"name": "privado.pdf", "contentType": "application/pdf", "size": len(raw)},
            token=p1_tok,
        )
        if not s3_is_configured(self.ctx):
            self.assertEqual(req.status, 503, req.text)
            del_other = self.client.delete(
                "/api/records/documents/00000000-0000-0000-0000-999999999999", token=p2_tok
            )
            self.assertIn(del_other.status, (403, 404, 503))
            return
        self.assertEqual(req.status, 201)
        self.client.upload_presigned_post(req.data["url"], req.data["fields"], "privado.pdf", "application/pdf", raw)
        del_other = self.client.delete(f"/api/records/documents/{req.data['id']}", token=p2_tok)
        self.assertIn(del_other.status, (403, 404))
        list_other = self.client.get("/api/records/documents", query={"patientId": p1["id"]}, token=p2_tok)
        # For a patient querying with ?patientId=other, backend either ignores query (returning own empty list) or returns 403
        if list_other.status == 200:
            self.assertFalse(any(d["id"] == req.data["id"] for d in list_other.data))
        else:
            self.assertIn(list_other.status, (403, 404))

    def test_t2_f06_04_doctor_without_consent_blocked_from_documents(self) -> None:
        _, p_user = register_patient(self.client)
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertEqual(resp.status, 403)

    def test_t2_f06_05_deleted_document_returns_404_on_second_delete_and_download(self) -> None:
        p_tok, _ = register_patient(self.client)
        raw = b"%PDF-1.4\n% delete check\n%%EOF\n"
        req = self.client.post(
            "/api/records/documents",
            {"name": "temp.pdf", "contentType": "application/pdf", "size": len(raw)},
            token=p_tok,
        )
        if not s3_is_configured(self.ctx):
            self.assertEqual(req.status, 503, req.text)
            return
        self.assertEqual(req.status, 201)
        self.client.upload_presigned_post(req.data["url"], req.data["fields"], "temp.pdf", "application/pdf", raw)
        docs = self.client.get("/api/records/documents", token=p_tok).data
        dl_url = next(d["downloadUrl"] for d in docs if d["id"] == req.data["id"])
        self.assertEqual(self.client.delete(f"/api/records/documents/{req.data['id']}", token=p_tok).status, 200)
        self.assertEqual(self.client.delete(f"/api/records/documents/{req.data['id']}", token=p_tok).status, 404)
        self.assertIn(self.client.download_url(dl_url).status, (403, 404))
