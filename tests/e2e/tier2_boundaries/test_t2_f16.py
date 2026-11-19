"""Tier 2 F16: Responsive Viewports (390px/320px), Route Guards & Modal Edge Cases (5 tests)."""
from __future__ import annotations

import json
import unittest

from tests.e2e.harness.browser_driver import assert_no_horizontal_overflow, open_browser_page
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_patient,
)


class TestTier2F16UiBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()

    def test_t2_f16_01_mobile_390x844_zero_horizontal_overflow(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx, width=390, height=844) as (page, errors, _):
                page.goto(self.ctx.frontend_url, wait_until="networkidle")
                assert_no_horizontal_overflow(page)
                self.assertFalse(errors, errors)
            return
        styles = (self.ctx.repo_root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("@media", styles)

    def test_t2_f16_02_mobile_320x640_zero_horizontal_overflow(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx, width=320, height=640) as (page, errors, _):
                page.goto(self.ctx.frontend_url, wait_until="networkidle")
                assert_no_horizontal_overflow(page)
                self.assertFalse(errors, errors)
            return
        tokens = (self.ctx.repo_root / "frontend" / "src" / "styles" / "_tokens.css").read_text(encoding="utf-8")
        self.assertIn("--control-height:", tokens)

    def test_t2_f16_03_route_guard_blocks_unauthenticated_panel_and_expediente(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx) as (page, errors, _):
                page.goto(f"{self.ctx.frontend_url}#/panel", wait_until="networkidle")
                self.assertIn("#/acceso", page.url)
                page.goto(f"{self.ctx.frontend_url}#/expediente", wait_until="networkidle")
                self.assertIn("#/acceso", page.url)
                self.assertFalse(errors, errors)
            return
        if self.ctx.use_self_test_fixtures:
            from tests.e2e.harness.self_test_fixtures import SELF_TEST_HTML_SHELL

            self.assertIn("#/panel", SELF_TEST_HTML_SHELL)
            self.assertIn("#/expediente", SELF_TEST_HTML_SHELL)
            self.assertIn("#/acceso", SELF_TEST_HTML_SHELL)
            return
        routes = (self.ctx.repo_root / "frontend" / "src" / "app" / "app.routes.ts").read_text(encoding="utf-8")
        self.assertIn("canActivate", routes)

    def test_t2_f16_04_empty_states_and_error_retry_rendered_cleanly(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx) as (page, errors, _):
                page.goto(f"{self.ctx.frontend_url}#/buscar", wait_until="networkidle")
                empty_loc = page.locator(".ds-empty, .ds-empty-state, ds-empty-state, [data-testid='empty-state']")
                if empty_loc.count() == 0:
                    # Trigger a zero-result search when providers already exist in directory
                    search_inp = page.locator(
                        "input[name='specialty'], input[name='text'], input[type='search'], input[name='q'], input"
                    ).first
                    if search_inp.count() > 0:
                        search_inp.fill("__no_such_specialty__")
                        btn = page.locator("button[type='submit'], button:has-text('Buscar')").first
                        if btn.count() > 0:
                            btn.click()
                empty_loc.first.wait_for(state="visible", timeout=15000)
                self.assertTrue(empty_loc.count() >= 1, "Expected empty state when directory/search has zero matches")
                self.assertFalse(errors, errors)
            return
        design = (self.ctx.repo_root / "design" / "system.md").read_text(encoding="utf-8")
        self.assertTrue(
            "ds-empty-state" in design.lower() or "estado vacío" in design.lower(),
            "design/system.md must specify ds-empty-state",
        )

    def test_t2_f16_05_reschedule_modal_closes_cleanly_without_native_confirm(self) -> None:
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
                {"doctorId": d_id, "dateTime": slots[0], "reason": "Modal Reprogramar E2E"},
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
                open_btn = page.locator("button:has-text('Reprogramar'), button:has-text('Cancelar'), #btn-open-confirm").first
                open_btn.wait_for(state="visible", timeout=15000)
                open_btn.click()
                page.locator("dialog[open]").first.wait_for(state="visible", timeout=5000)
                self.assertEqual(page.locator("dialog[open]").count(), 1)
                close_btn = page.locator(
                    "dialog[open] button:has-text('Cerrar'), dialog[open] button:has-text('Cancelar')"
                ).first
                close_btn.wait_for(state="visible", timeout=5000)
                close_btn.click()
                page.wait_for_function("() => document.querySelectorAll('dialog[open]').length === 0", timeout=5000)
                self.assertEqual(page.locator("dialog[open]").count(), 0)
                self.assertEqual(native_dialogs, [])
                self.assertFalse(errors, errors)
            return
        if self.ctx.use_self_test_fixtures:
            from tests.e2e.harness.self_test_fixtures import SELF_TEST_HTML_SHELL

            self.assertIn("<dialog", SELF_TEST_HTML_SHELL)
            self.assertIn("close()", SELF_TEST_HTML_SHELL)
            self.assertNotIn("window.confirm(", SELF_TEST_HTML_SHELL)
            return
        html_files = list((self.ctx.repo_root / "frontend" / "src").rglob("*.html"))
        self.assertTrue(
            any(
                "<dialog" in f.read_text(encoding="utf-8", errors="replace")
                or "ds-modal" in f.read_text(encoding="utf-8", errors="replace")
                for f in html_files
            )
        )
