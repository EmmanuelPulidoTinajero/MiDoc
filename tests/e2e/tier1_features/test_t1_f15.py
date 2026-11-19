"""Tier 1 F15: GitHub Actions CI & CD Workflow Contracts (5 tests)."""
from __future__ import annotations

import re
import unittest

from tests.e2e.harness.aws_inspector import get_workflow_text
from tests.e2e.harness.config import get_active_context


class TestTier1F15Cicd(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()

    def test_t1_f15_01_ci_yml_covers_backend_terraform_and_frontend(self) -> None:
        ci = get_workflow_text(self.ctx, "ci.yml")
        self.assertIsNotNone(ci, "Missing .github/workflows/ci.yml")
        assert ci is not None
        self.assertIn("unittest", ci)
        self.assertIn("terraform fmt -check", ci)
        self.assertIn("terraform validate", ci)
        self.assertIn("npm run build", ci)
        self.assertIn("npm test", ci)

    def test_t1_f15_02_cd_yml_triggers_on_main_and_workflow_dispatch(self) -> None:
        cd = get_workflow_text(self.ctx, "cd.yml")
        self.assertIsNotNone(cd, "Missing .github/workflows/cd.yml")
        assert cd is not None
        self.assertIn("main", cd)
        self.assertIn("workflow_dispatch", cd)
        self.assertIn("publish_frontend.py", cd)

    def test_t1_f15_03_workflows_have_no_hardcoded_secrets_and_check_sts(self) -> None:
        ci = get_workflow_text(self.ctx, "ci.yml") or ""
        cd = get_workflow_text(self.ctx, "cd.yml") or ""
        combined = ci + "\n" + cd
        self.assertIsNone(re.search(r"sk_live_[A-Za-z0-9]{10,}", combined))
        self.assertIsNone(re.search(r"AKIA[0-9A-Z]{16}", combined))
        self.assertIn("get-caller-identity", cd)

    def test_t1_f15_04_ci_runs_frontend_tests_on_node_24(self) -> None:
        ci = get_workflow_text(self.ctx, "ci.yml") or ""
        self.assertIn("node-version: 24", ci)
        self.assertIn("npm ci", ci)
        self.assertIn("npm test", ci)

    def test_t1_f15_05_workflow_yaml_structural_syntax(self) -> None:
        for wf in ("ci.yml", "cd.yml"):
            text = get_workflow_text(self.ctx, wf)
            self.assertIsNotNone(text, f"Missing {wf}")
            assert text is not None
            self.assertIn("on:", text)
            self.assertIn("jobs:", text)
            self.assertNotIn("\t", text, f"Tabs found in YAML workflow {wf}")
