"""Tier 1 F13: Terraform AWS Infra Contracts (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.aws_inspector import (
    check_terraform_fmt_and_validate,
    fetch_frontend_config,
    get_tf_content,
    run_aws_json,
)
from tests.e2e.harness.config import get_active_context


class TestTier1F13Infrastructure(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()

    def test_t1_f13_01_terraform_fmt_and_validate(self) -> None:
        ok, msg = check_terraform_fmt_and_validate(self.ctx)
        self.assertTrue(ok, msg)

    def test_t1_f13_02_terraform_stripe_variables_and_secrets_layout(self) -> None:
        vars_tf = get_tf_content(self.ctx, "variables.tf")
        main_tf = get_tf_content(self.ctx, "main.tf")
        self.assertIn("payment_mode", vars_tf)
        self.assertIn("stripe_secret_key", vars_tf)
        self.assertIn("sk_test_", vars_tf)
        self.assertIn("sk_live_", vars_tf)
        self.assertIn("recovery_window_in_days = 0", main_tf)
        self.assertIn("stripe", main_tf.lower())

    def test_t1_f13_03_private_s3_medical_bucket_encryption_and_cors(self) -> None:
        if self.ctx.target == "cloud":
            bucket = self.ctx._cloud_outputs.get("medical_documents_bucket")
            if bucket:
                pab = run_aws_json(self.ctx, "s3api", "get-public-access-block", "--bucket", bucket)
                cfg = pab.get("PublicAccessBlockConfiguration", {})
                self.assertTrue(cfg.get("BlockPublicAcls"))
                self.assertTrue(cfg.get("BlockPublicPolicy"))
                enc = run_aws_json(self.ctx, "s3api", "get-bucket-encryption", "--bucket", bucket)
                self.assertTrue(enc.get("ServerSideEncryptionConfiguration"))
                cors = run_aws_json(self.ctx, "s3api", "get-bucket-cors", "--bucket", bucket)
                self.assertTrue(cors.get("CORSRules"))
                return
        s3_med = (self.ctx.repo_root / "infrastructure" / "s3_medical.py").read_text(encoding="utf-8")
        self.assertIn("AES256", s3_med)
        self.assertIn("BlockPublicAcls", s3_med)
        self.assertIn("CORS", s3_med.upper())

    def test_t1_f13_04_frontend_https_config_json_contract(self) -> None:
        cfg = fetch_frontend_config(self.ctx)
        self.assertIn("apiUrl", cfg)
        self.assertTrue(str(cfg["apiUrl"]).startswith("http"))
        self.assertIn(cfg.get("paymentMode"), ("test", "live"))

    def test_t1_f13_05_verify_teardown_dynamic_discovery_contract(self) -> None:
        vt = (self.ctx.repo_root / "infrastructure" / "verify_teardown.py").read_text(encoding="utf-8")
        self.assertIn("LabRole", vt)
        self.assertIn("get-caller-identity", vt)
        self.assertIn("PASS", vt)
        if not self.ctx.use_self_test_fixtures:
            self.assertNotIn("vpce-0837c4d5a8bee3a0c", vt, "Stale hardcoded VPC endpoint IDs must be replaced")
