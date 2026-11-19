"""Tier 2 F09: Inventory Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
)


class TestTier2F09InventoryBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f09_01_unsubscribed_doctor_and_paciente_blocked_from_inventory(self) -> None:
        p_tok, _ = register_patient(self.client)
        unsub_tok, _, _ = register_doctor(self.client)
        self.assertEqual(self.client.get("/api/doctor/inventory", token=p_tok).status, 403)
        self.assertEqual(self.client.get("/api/doctor/inventory", token=unsub_tok).status, 402)
        self.assertEqual(
            self.client.post("/api/doctor/inventory", {"name": "X", "quantity": 1, "unit": "pz"}, token=unsub_tok).status,
            402,
        )

    def test_t2_f09_02_negative_inventory_quantity_rejected(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.post("/api/doctor/inventory", {"name": "Vendas", "quantity": -5, "unit": "rollos"}, token=d_tok)
        self.assertEqual(resp.status, 400)

    def test_t2_f09_03_empty_or_oversized_inventory_name_rejected(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        self.assertEqual(self.client.post("/api/doctor/inventory", {"name": "", "quantity": 1, "unit": "pz"}, token=d_tok).status, 400)
        self.assertEqual(
            self.client.post("/api/doctor/inventory", {"name": "X" * 200, "quantity": 1, "unit": "pz"}, token=d_tok).status,
            400,
        )

    def test_t2_f09_04_cross_doctor_inventory_deletion_blocked(self) -> None:
        d1_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Uno")
        d2_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Dos")
        item = self.client.post("/api/doctor/inventory", {"name": "Estetoscopio", "quantity": 2, "unit": "pz"}, token=d1_tok).data
        resp = self.client.delete(f"/api/doctor/inventory/{item['id']}", token=d2_tok)
        self.assertIn(resp.status, (403, 404))

    def test_t2_f09_05_deleting_nonexistent_inventory_uuid_returns_404(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.delete("/api/doctor/inventory/00000000-0000-0000-0000-999999999999", token=d_tok)
        self.assertEqual(resp.status, 404)
