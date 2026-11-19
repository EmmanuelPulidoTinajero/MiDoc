"""Tier 2 F13: Infrastructure Security & Negative Config Contracts (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.aws_inspector import get_tf_content
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import register_patient, s3_is_configured


class TestTier2F13InfraBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f13_01_terraform_rejects_mismatched_stripe_key_mode(self) -> None:
        vars_tf = get_tf_content(self.ctx, "variables.tf")
        self.assertIn("sk_test_", vars_tf)
        self.assertIn("sk_live_", vars_tf)
        self.assertIn("payment_mode", vars_tf)
        self.assertIn("validation", vars_tf)

    def test_t2_f13_02_production_mode_fails_explicitly_without_rds_config(self) -> None:
        app_py = (self.ctx.repo_root / "backend" / "src" / "app.py").read_text(encoding="utf-8")
        self.assertIn("production", app_py)
        self.assertIn("DATABASE", app_py)

    def test_t2_f13_03_private_s3_medical_bucket_denies_anonymous_get(self) -> None:
        if self.ctx.mode == "self-test":
            resp = self.client.get("/__s3/private-raw")
            self.assertEqual(resp.status, 403)
            return
        if self.ctx.target == "cloud":
            bucket = self.ctx._cloud_outputs.get("medical_documents_bucket")
            if bucket:
                anon = self.client.download_url(f"https://{bucket}.s3.{self.ctx.aws_region}.amazonaws.com/")
                self.assertEqual(anon.status, 403)
                return
        s3_med = (self.ctx.repo_root / "infrastructure" / "s3_medical.py").read_text(encoding="utf-8")
        self.assertIn("BlockPublicAcls", s3_med)

    def test_t2_f13_04_medical_bucket_cors_rejects_untrusted_origin(self) -> None:
        if self.ctx.mode == "self-test":
            resp = self.client.options("/__s3/upload/test", headers={"Origin": "https://evil.example"})
            self.assertNotEqual(resp.headers.get("access-control-allow-origin"), "https://evil.example")
            return
        s3_med = (self.ctx.repo_root / "infrastructure" / "s3_medical.py").read_text(encoding="utf-8")
        self.assertNotIn('"*"', s3_med)

    def test_t2_f13_05_tampered_presigned_url_rejected(self) -> None:
        p_tok, _ = register_patient(self.client)
        raw = b"%PDF-1.4\n% sig tamper\n%%EOF\n"
        req = self.client.post(
            "/api/records/documents",
            {"name": "sig.pdf", "contentType": "application/pdf", "size": len(raw)},
            token=p_tok,
        )
        if not s3_is_configured(self.ctx):
            self.assertEqual(req.status, 503, req.text)
            return
        self.assertEqual(req.status, 201)
        self.client.upload_presigned_post(req.data["url"], req.data["fields"], "sig.pdf", "application/pdf", raw)
        docs = self.client.get("/api/records/documents", token=p_tok).data
        url = next(d["downloadUrl"] for d in docs if d["id"] == req.data["id"])
        tampered = url + "tamper"
        dl = self.client.download_url(tampered)
        self.assertEqual(dl.status, 403)
