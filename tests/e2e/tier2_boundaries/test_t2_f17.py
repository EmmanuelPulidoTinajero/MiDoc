"""Tier 2 F17: Scope Guard, Security Warnings & Teardown Governance Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.aws_inspector import get_doc_text
from tests.e2e.harness.config import get_active_context


class TestTier2F17GovernanceBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()

    def test_t2_f17_01_zero_out_of_scope_ai_webrtc_cognito_claims_in_docs(self) -> None:
        eval_doc = get_doc_text(self.ctx, "docs/EVALUACION-INTEGRAL.md")
        self.assertIsNotNone(eval_doc, "Missing docs/EVALUACION-INTEGRAL.md")
        for forbidden in ("WebRTC implementado", "AWS Cognito activo", "OCR con Bedrock"):
            self.assertNotIn(forbidden, eval_doc)

    def test_t2_f17_02_cierre_and_deployment_docs_document_teardown_boundaries(self) -> None:
        cierre = get_doc_text(self.ctx, "docs/CIERRE-AWS.md") or ""
        dep = (self.ctx.repo_root / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
        self.assertIn("destroy", (cierre + dep).lower())

    def test_t2_f17_03_pagos_stripe_warns_against_committing_live_keys(self) -> None:
        doc = get_doc_text(self.ctx, "docs/PAGOS-STRIPE.md") or ""
        self.assertIn("sk_live_", doc)
        self.assertIn("Secrets Manager", doc)

    def test_t2_f17_04_no_fase2_simulated_card_4242_in_active_api_docs(self) -> None:
        api_md = get_doc_text(self.ctx, "docs/API.md") or ""
        self.assertNotIn("/api/subscriptions/pay", api_md)
        self.assertNotIn("4242424242424242", api_md)

    def test_t2_f17_05_teardown_verification_script_and_tf_destroy_safe(self) -> None:
        vt = (self.ctx.repo_root / "infrastructure" / "verify_teardown.py").read_text(encoding="utf-8")
        self.assertIn("terraformManagedResources", vt)
        self.assertIn("PASS", vt)
