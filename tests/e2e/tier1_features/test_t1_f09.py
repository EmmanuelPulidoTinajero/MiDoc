"""Tier 1 F09: Provider Supplies & Medications Inventory CRUD (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import register_and_subscribe_doctor


class TestTier1F09Inventory(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f09_01_create_supply_item(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.post(
            "/api/doctor/inventory",
            {"name": "Guantes Nitrilo", "quantity": 50, "unit": "cajas"},
            token=d_tok,
        )
        self.assertEqual(resp.status, 201, resp.text)
        self.assertTrue(resp.data.get("id"))
        self.assertEqual(resp.data["quantity"], 50)

    def test_t1_f09_02_list_own_inventory_isolated(self) -> None:
        d1_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Inv 1")
        d2_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Inv 2")
        i1 = self.client.post("/api/doctor/inventory", {"name": "Gasas A", "quantity": 10, "unit": "paquetes"}, token=d1_tok).data
        i2 = self.client.post("/api/doctor/inventory", {"name": "Gasas B", "quantity": 20, "unit": "paquetes"}, token=d2_tok).data
        lst1 = self.client.get("/api/doctor/inventory", token=d1_tok)
        self.assertEqual(lst1.status, 200)
        ids = {x["id"] for x in lst1.data}
        self.assertIn(i1["id"], ids)
        self.assertNotIn(i2["id"], ids)

    def test_t1_f09_03_case_insensitive_upsert_updates_quantity(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/doctor/inventory", {"name": "Guantes Nitrilo", "quantity": 50, "unit": "cajas"}, token=d_tok)
        up = self.client.post("/api/doctor/inventory", {"name": "guantes nitrilo", "quantity": 25, "unit": "cajas"}, token=d_tok)
        self.assertIn(up.status, (200, 201), up.text)
        lst = self.client.get("/api/doctor/inventory", token=d_tok)
        matches = [x for x in lst.data if x["name"].lower() == "guantes nitrilo"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["quantity"], 25)

    def test_t1_f09_04_zero_quantity_allowed(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/doctor/inventory", {"name": "Alcohol 70%", "quantity": 5, "unit": "litros"}, token=d_tok)
        up = self.client.post("/api/doctor/inventory", {"name": "Alcohol 70%", "quantity": 0, "unit": "litros"}, token=d_tok)
        self.assertIn(up.status, (200, 201), up.text)
        self.assertEqual(up.data["quantity"], 0)

    def test_t1_f09_05_delete_own_inventory_item(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        created = self.client.post("/api/doctor/inventory", {"name": "Cubrebocas", "quantity": 100, "unit": "piezas"}, token=d_tok).data
        dele = self.client.delete(f"/api/doctor/inventory/{created['id']}", token=d_tok)
        self.assertEqual(dele.status, 200, dele.text)
        lst = self.client.get("/api/doctor/inventory", token=d_tok)
        self.assertFalse(any(x["id"] == created["id"] for x in lst.data))
