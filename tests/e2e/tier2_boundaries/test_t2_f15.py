"""Tier 2 F15: GitHub Actions Security & Parity Boundaries (5 tests)."""
from __future__ import annotations

import re
import unittest

from tests.e2e.harness.aws_inspector import get_workflow_text
from tests.e2e.harness.config import get_active_context


class TestTier2F15CicdBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()

    def test_t2_f15_01_ci_yml_does_not_mask_failures_with_continue_on_error(self) -> None:
        ci = get_workflow_text(self.ctx, "ci.yml") or ""
        self.assertNotIn("continue-on-error: true", ci)

    def test_t2_f15_02_cd_yml_does_not_run_on_pull_requests(self) -> None:
        cd = get_workflow_text(self.ctx, "cd.yml") or ""
        self.assertTrue(cd, "Missing cd.yml")
        self.assertNotIn("pull_request:", cd)
        self.assertIn("main", cd)

    def test_t2_f15_03_cd_yml_checks_aws_credentials_before_apply(self) -> None:
        cd = get_workflow_text(self.ctx, "cd.yml") or ""
        self.assertIn("get-caller-identity", cd)
        self.assertIn("terraform", cd)

    def test_t2_f15_04_no_plaintext_secrets_committed_in_workflows_or_tf(self) -> None:
        patterns = [r"sk_live_[A-Za-z0-9]{10,}", r"AKIA[0-9A-Z]{16}", r"whsec_[A-Za-z0-9]{16,}"]
        files = list((self.ctx.repo_root / ".github" / "workflows").glob("*.yml")) + list(
            (self.ctx.repo_root / "infrastructure").glob("*.tf")
        )
        for f in files:
            txt = f.read_text(encoding="utf-8", errors="replace")
            for pat in patterns:
                self.assertIsNone(re.search(pat, txt), f"Potential secret pattern {pat} in {f}")

    def test_t2_f15_05_frontend_test_runner_and_ci_node_parity(self) -> None:
        ci = get_workflow_text(self.ctx, "ci.yml") or ""
        self.assertIn("npm test", ci)
        pkg = (self.ctx.repo_root / "frontend" / "package.json").read_text(encoding="utf-8")
        self.assertIn('"test"', pkg)
