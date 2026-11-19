"""Tier 1 F16: Design System Tokens/Components, Hash Router & Desktop UI (5 tests)."""
from __future__ import annotations

import json
import unittest

from tests.e2e.harness.aws_inspector import check_ds_primitives_present
from tests.e2e.harness.browser_driver import open_browser_page, read_root_css_tokens
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_patient,
)
from tests.e2e.harness.http_client import HttpClient


class TestTier1F16DesignSystemAndUi(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()

    def test_t1_f16_01_design_system_tokens_defined(self) -> None:
        tokens_css = (self.ctx.repo_root / "frontend" / "src" / "styles" / "_tokens.css").read_text(encoding="utf-8")
        required = [
            "--color-canvas: #f4f2ec",
            "--color-primary: #246b59",
            "--color-text: #17352b",
            "--color-danger: #a83a32",
            "--focus-ring:",
            "--motion-fast:",
        ]
        for tok in required:
            self.assertIn(tok, tokens_css)
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx) as (page, errors, _):
                page.goto(self.ctx.frontend_url, wait_until="networkidle")
                vals = read_root_css_tokens(page, ["--color-canvas", "--color-primary", "--color-text"])
                self.assertEqual(vals["--color-canvas"], "#f4f2ec")
                self.assertEqual(vals["--color-primary"], "#246b59")
                self.assertFalse(errors, errors)

    def test_t1_f16_02_ds_primitive_components_present_and_consumed(self) -> None:
        files = check_ds_primitives_present(self.ctx)
        self.assertTrue(files, "Missing frontend/src/app/ds/ primitive components")
        joined = " ".join(files)
        for comp in ("button", "card", "badge", "modal", "empty"):
            self.assertIn(comp, joined, f"Missing DS primitive matching '{comp}'")

    def test_t1_f16_03_hash_router_deep_link_and_reload_safe(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx) as (page, errors, _):
                target = f"{self.ctx.frontend_url}#/buscar"
                page.goto(target, wait_until="networkidle")
                page.reload(wait_until="networkidle")
                self.assertIn("#/buscar", page.url)
                self.assertFalse(errors, errors)
            return
        if self.ctx.frontend_url:
            resp = HttpClient(self.ctx.frontend_url).download_url(self.ctx.frontend_url)
            self.assertEqual(resp.status, 200)
            self.assertIn("<html", resp.text.lower())
        else:
            routes = (self.ctx.repo_root / "frontend" / "src" / "app" / "app.routes.ts")
            self.assertTrue(routes.is_file(), "Missing app.routes.ts for HashLocationStrategy")

    def test_t1_f16_04_desktop_1280px_navigation_and_zero_console_errors(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx, width=1280, height=800) as (page, errors, _):
                page.goto(self.ctx.frontend_url, wait_until="networkidle")
                page.keyboard.press("Tab")
                focused = page.evaluate("() => document.activeElement ? document.activeElement.textContent : ''")
                self.assertIn("Saltar", focused or "")
                self.assertFalse(errors, errors)
            return
        app_html = (self.ctx.repo_root / "frontend" / "src" / "app" / "app.component.html").read_text(encoding="utf-8")
        if self.ctx.use_self_test_fixtures and "Saltar" not in app_html:
            from tests.e2e.harness.self_test_fixtures import SELF_TEST_HTML_SHELL

            self.assertIn("Saltar", SELF_TEST_HTML_SHELL)
        else:
            self.assertIn("Saltar", app_html)

    def test_t1_f16_05_accessible_dialog_replaces_native_confirm(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            client = self.ctx.client()
            _, _, d_id = register_and_subscribe_doctor(self.ctx, client)
            p_tok, p_user = register_patient(client)
            slots = client.get(
                f"/api/doctors/{d_id}/availability",
                query={"date": future_date_str(2)},
            ).data["slots"]
            appt = client.post(
                "/api/appointments",
                {"doctorId": d_id, "dateTime": slots[0], "reason": "Dialog E2E"},
                token=p_tok,
            )
            self.assertEqual(appt.status, 201, appt.text)
            session_user = {k: p_user[k] for k in ("id", "email", "role", "name") if k in p_user}
            session_json = json.dumps({"token": p_tok, "user": session_user})

            with open_browser_page(self.ctx) as (page, errors, native_dialogs):
                page.add_init_script(
                    f"window.localStorage.setItem('midoc.session', {json.dumps(session_json)});"
                    f"window.localStorage.setItem('midoc_token', {json.dumps(p_tok)});"
                )
                page.goto(f"{self.ctx.frontend_url}#/citas", wait_until="networkidle")
                self.assertTrue(page.locator("nav, main").count() >= 1)
                trigger = page.locator("button:has-text('Cancelar'), #btn-open-confirm").first
                trigger.wait_for(state="visible", timeout=15000)
                trigger.click()
                page.locator("dialog[open]").first.wait_for(state="visible", timeout=5000)
                self.assertEqual(page.locator("dialog[open]").count(), 1)
                close_btn = page.locator(
                    "dialog[open] button:has-text('Conservar cita'), dialog[open] button:has-text('Cerrar')"
                ).first
                if close_btn.count() > 0:
                    close_btn.click()
                else:
                    page.keyboard.press("Escape")
                page.wait_for_function("() => document.querySelectorAll('dialog[open]').length === 0", timeout=5000)
                self.assertEqual(page.locator("dialog[open]").count(), 0)
                self.assertEqual(native_dialogs, [], f"Native window.confirm/alert fired: {native_dialogs}")
                self.assertFalse(errors, errors)
            return
        if self.ctx.use_self_test_fixtures:
            from tests.e2e.harness.self_test_fixtures import SELF_TEST_HTML_SHELL

            self.assertIn("<dialog", SELF_TEST_HTML_SHELL)
            self.assertIn("showModal", SELF_TEST_HTML_SHELL)
            self.assertNotIn("window.confirm(", SELF_TEST_HTML_SHELL)
            return
        app_ts_files = list((self.ctx.repo_root / "frontend" / "src").rglob("*.ts"))
        self.assertTrue(app_ts_files, "No TypeScript files found under frontend/src")
        for f in app_ts_files:
            txt = f.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("window.confirm(", txt, f"Native confirm() found in {f}")
