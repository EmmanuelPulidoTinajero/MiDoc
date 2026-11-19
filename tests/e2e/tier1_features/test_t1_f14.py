"""Tier 1 F14: CloudWatch Observability Contracts (5 tests)."""
from __future__ import annotations

import json
import unittest

from tests.e2e.harness.aws_inspector import (
    collect_emf_telemetry,
    get_tf_content,
    run_aws_json,
    wait_for_cloudwatch_metrics,
)
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_patient,
)


class TestTier1F14Observability(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f14_01_cloudwatch_emf_metrics_contract(self) -> None:
        p_tok, _ = register_patient(self.client)
        if self.ctx.mode == "self-test":
            metrics = collect_emf_telemetry(self.ctx)
            self.assertTrue(metrics)
            sample = metrics[-1]
            cw = sample["_aws"]["CloudWatchMetrics"][0]
            self.assertEqual(cw["Namespace"], "MiDoc")
            self.assertEqual(sample["Service"], "midoc-api")
            return
        if self.ctx.target == "cloud":
            # Actively emit LoginFailures & AppointmentsCreated before polling CloudWatch EMF
            self.client.post("/api/auth/login", {"email": "missing-f14@example.invalid", "password": "BadPassword1"})
            _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
            slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
            self.assertEqual(
                self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p_tok).status,
                201,
            )
            names = wait_for_cloudwatch_metrics(
                self.ctx, ("RequestLatencyMs", "AppointmentsCreated", "LoginFailures"), timeout_s=90.0
            )
            for req in ("RequestLatencyMs", "AppointmentsCreated", "LoginFailures"):
                self.assertIn(req, names, f"Missing CloudWatch metric {req} after polling; found={sorted(names)}")
            return
        metricas_py = (self.ctx.repo_root / "backend" / "src" / "metricas.py").read_text(encoding="utf-8")
        for m in ("RequestLatencyMs", "ServerErrors", "AppointmentsCreated", "ConsultationsRegistered", "LoginFailures"):
            self.assertIn(m, metricas_py)

    def test_t1_f14_02_cloudwatch_explicit_log_groups_retention_14_days(self) -> None:
        if self.ctx.target == "cloud":
            lgs = run_aws_json(
                self.ctx, "logs", "describe-log-groups", "--log-group-name-prefix", f"/aws/lambda/{self.ctx.project_name}"
            )
            groups = lgs.get("logGroups", [])
            self.assertTrue(groups, "No Lambda CloudWatch log groups found")
            self.assertTrue(any(g.get("retentionInDays") == 14 for g in groups))
            return
        tf_all = get_tf_content(self.ctx, "monitoring.tf") + "\n" + get_tf_content(self.ctx, "lambda.tf")
        self.assertIn("aws_cloudwatch_log_group", tf_all)
        self.assertIn("retention_in_days = 14", tf_all)

    def test_t1_f14_03_cloudwatch_alarms_and_sns_topic(self) -> None:
        if self.ctx.target == "cloud":
            alarms = run_aws_json(self.ctx, "cloudwatch", "describe-alarms", "--alarm-name-prefix", self.ctx.project_name)
            names = {a["AlarmName"] for a in alarms.get("MetricAlarms", [])}
            self.assertIn(f"{self.ctx.project_name}-api-errores-5xx", names)
            self.assertIn(f"{self.ctx.project_name}-api-latencia-p95", names)
            return
        mon = get_tf_content(self.ctx, "monitoring.tf")
        self.assertIn("api-errores-5xx", mon)
        self.assertIn("api-latencia-p95", mon)
        self.assertIn("aws_sns_topic", mon)

    def test_t1_f14_04_cloudwatch_dashboard_and_logs_insights(self) -> None:
        if self.ctx.target == "cloud":
            dash = run_aws_json(
                self.ctx, "cloudwatch", "get-dashboard", "--dashboard-name", f"{self.ctx.project_name}-estado"
            )
            body = json.loads(dash["DashboardBody"])
            self.assertTrue(body.get("widgets"))
            return
        mon = get_tf_content(self.ctx, "monitoring.tf")
        self.assertIn("estado", mon)
        self.assertIn("aws_cloudwatch_dashboard", mon)
        self.assertIn("aws_cloudwatch_query_definition", mon)

    def test_t1_f14_05_structured_json_logging_no_secret_leakage(self) -> None:
        tok, user = register_patient(self.client)
        self.client.get("/api/me", token=tok)
        if self.ctx.mode == "self-test":
            logs = self.client.get("/__selftest/metrics").json_data.get("logs", [])
            self.assertTrue(logs)
            serialized = json.dumps(logs)
            self.assertNotIn(user["password"], serialized)
            self.assertNotIn(tok, serialized)
            last = logs[-1]
            for k in ("method", "path", "status", "latencyMs"):
                self.assertIn(k, last)
            return
        app_py = (self.ctx.repo_root / "backend" / "src" / "app.py").read_text(encoding="utf-8")
        self.assertIn("json.dumps", app_py)
