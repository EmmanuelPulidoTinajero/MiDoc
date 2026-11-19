"""Tier 1 F01: Auth, Roles, PUT /api/me & Token Refresh (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_doctor,
    register_patient,
    strong_password,
    unique_email,
)


class TestTier1F01Auth(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f01_01_register_patient_free_account(self) -> None:
        email = unique_email("t1f01-pat")
        resp = self.client.post(
            "/api/auth/register",
            {
                "email": email,
                "password": strong_password(),
                "role": "PACIENTE",
                "name": "Ana Paciente",
                "phone": "5511223344",
            },
        )
        self.assertEqual(resp.status, 201, resp.text)
        self.assertTrue(resp.json_data.get("token"))
        user = resp.json_data.get("user") or {}
        self.assertTrue(user.get("id"))
        self.assertEqual(user.get("role"), "PACIENTE")
        self.assertEqual(user.get("email"), email)

    def test_t1_f01_02_register_doctor_and_clinica_accounts(self) -> None:
        d_tok, d_user, d_id = register_doctor(self.client, role="DOCTOR", name="Dr. Uno", price=450)
        c_tok, c_user, c_id = register_doctor(self.client, role="CLINICA", name="Clínica Dos", price=700)
        self.assertTrue(d_tok and d_id)
        self.assertTrue(c_tok and c_id)
        self.assertEqual(d_user["role"], "DOCTOR")
        self.assertEqual(c_user["role"], "CLINICA")
        self.assertNotEqual(d_id, c_id)

    def test_t1_f01_03_login_email_normalization_and_me(self) -> None:
        raw_email = unique_email("MixCase")
        pw = strong_password()
        register_patient(self.client, email=raw_email, password=pw, name="Norm User")
        login = self.client.post(
            "/api/auth/login",
            {"email": f"  {raw_email.upper()}  ", "password": pw},
        )
        self.assertEqual(login.status, 200, login.text)
        token = login.json_data.get("token")
        self.assertTrue(token)
        me = self.client.get("/api/me", token=token)
        self.assertEqual(me.status, 200, me.text)
        self.assertEqual(me.data.get("role"), "PACIENTE")
        self.assertEqual(me.data.get("name"), "Norm User")

    def test_t1_f01_04_update_profile_and_password_put_me(self) -> None:
        p_tok, p_user = register_patient(self.client, name="Original Pat")
        old_pw = p_user["password"]
        new_pw = "NewStrongPass2026!7"
        upd_p = self.client.put(
            "/api/me",
            {"name": "Updated Pat", "phone": "5599887766", "currentPassword": old_pw, "newPassword": new_pw},
            token=p_tok,
        )
        self.assertEqual(upd_p.status, 200, upd_p.text)
        self.assertEqual(upd_p.data["name"], "Updated Pat")

        relogin = self.client.post("/api/auth/login", {"email": p_user["email"], "password": new_pw})
        self.assertEqual(relogin.status, 200, relogin.text)

        d_tok, _, _ = register_doctor(self.client, specialty="Pediatría", price=500)
        upd_d = self.client.put(
            "/api/me",
            {"specialty": "Dermatología", "price": 650, "city": "Guadalajara"},
            token=d_tok,
        )
        self.assertEqual(upd_d.status, 200, upd_d.text)
        me_d = self.client.get("/api/me", token=d_tok)
        self.assertEqual(me_d.status, 200)
        self.assertEqual(me_d.data["doctor"]["specialty"], "Dermatología")
        self.assertEqual(float(me_d.data["doctor"]["price"]), 650.0)

    def test_t1_f01_05_refresh_jwt_session(self) -> None:
        tok, _ = register_patient(self.client)
        ref = self.client.post("/api/auth/refresh", {}, token=tok)
        self.assertEqual(ref.status, 200, ref.text)
        fresh = ref.json_data.get("token")
        self.assertTrue(isinstance(fresh, str) and len(fresh) > 20)
        me = self.client.get("/api/me", token=fresh)
        self.assertEqual(me.status, 200, me.text)
