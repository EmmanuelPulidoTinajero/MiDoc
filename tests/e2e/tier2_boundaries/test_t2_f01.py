"""Tier 2 F01: Auth Boundaries, Rate Limit, Role Escalation & Non-Seed Guard (5 tests)."""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import time
import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import register_patient, strong_password, unique_email
from tests.e2e.harness.http_client import HttpClient


def _make_expired_jwt() -> str:
    h = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({"sub": "u-1", "exp": 1000}).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.invalidsig"


class TestTier2F01AuthBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f01_01_unauthenticated_and_malformed_jwt_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/me").status, 401)
        self.assertEqual(self.client.get("/api/me", token="invalid.jwt.token").status, 401)
        self.assertEqual(self.client.get("/api/me", token=_make_expired_jwt()).status, 401)

    def test_t2_f01_02_duplicate_email_and_wrong_password(self) -> None:
        email = unique_email("dup")
        pw = strong_password()
        register_patient(self.client, email=email, password=pw)
        dup = self.client.post(
            "/api/auth/register",
            {"email": email.upper(), "password": pw, "role": "PACIENTE", "name": "Dup User"},
        )
        self.assertIn(dup.status, (400, 409), dup.text)
        bad_pw = self.client.post("/api/auth/login", {"email": email, "password": "WrongPassword99!"})
        self.assertEqual(bad_pw.status, 401)

    def test_t2_f01_03_login_brute_force_rate_limiting(self) -> None:
        email = unique_email("ratelimit")
        register_patient(self.client, email=email)
        statuses: list[int] = []
        for _ in range(12):
            resp = self.client.post("/api/auth/login", {"email": email, "password": "WrongPassword99!"})
            statuses.append(resp.status)
        self.assertTrue(
            any(s in (423, 429) for s in statuses),
            f"Expected rate-limit 429/423 after repeated failures, got {statuses}",
        )

    def test_t2_f01_04_put_me_rejects_wrong_current_password_and_role_escalation(self) -> None:
        p_tok, _ = register_patient(self.client)
        bad_pw = self.client.put(
            "/api/me",
            {"currentPassword": "WrongCurrent1!", "newPassword": "NewValidPass2026!"},
            token=p_tok,
        )
        self.assertIn(bad_pw.status, (400, 401))
        esc = self.client.put("/api/me", {"role": "DOCTOR"}, token=p_tok)
        self.assertIn(esc.status, (200, 400, 403), esc.text)
        if esc.status == 200:
            self.assertEqual(esc.data.get("role"), "PACIENTE")
        me = self.client.get("/api/me", token=p_tok)
        self.assertEqual(me.data["role"], "PACIENTE")

    def test_t2_f01_05_production_non_seed_guard(self) -> None:
        if self.ctx.mode == "self-test":
            from tests.e2e.harness.self_test_server import SelfTestServer

            srv = SelfTestServer(
                stripe_base_url=self.ctx.stripe_mock.base_url if self.ctx.stripe_mock else "http://127.0.0.1:1",
                stripe_secret_key="sk_test_0",
                stripe_webhook_secret="whsec_0",
                allow_demo_seed=False,
            ).start()
            try:
                resp = HttpClient(srv.base_url).post(
                    "/api/auth/login", {"email": "doctor@midoc.local", "password": "doctor-demo"}
                )
                self.assertEqual(resp.status, 401)
            finally:
                srv.stop()
            return

        if self.ctx.target == "cloud":
            resp = self.client.post("/api/auth/login", {"email": "doctor@midoc.local", "password": "doctor-demo"})
            self.assertEqual(resp.status, 401, "Demo account must NOT exist in production cloud")
            return

        # Live local mode: spawn isolated local.py with ALLOW_DEMO_SEED=false
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])
        env = os.environ.copy()
        env.update({"PORT": str(port), "NODE_ENV": "test", "ALLOW_DEMO_SEED": "false"})
        local_py = self.ctx.repo_root / "backend" / "src" / "local.py"
        proc = subprocess.Popen(
            [sys.executable, str(local_py)],
            cwd=str(self.ctx.repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        try:
            c = HttpClient(f"http://127.0.0.1:{port}", timeout=2.0)
            for _ in range(30):
                try:
                    if c.get("/health").status == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            resp = c.post("/api/auth/login", {"email": "doctor@midoc.local", "password": "doctor-demo"})
            self.assertEqual(resp.status, 401)
        finally:
            proc.terminate()
            proc.wait(timeout=3.0)
