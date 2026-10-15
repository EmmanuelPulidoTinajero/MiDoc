import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app import DB, handle


class AppTests(unittest.TestCase):
    def test_health(self):
        response = handle("GET", "/health")
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["status"], "ok")

    def test_patient_can_book(self):
        login = json.loads(handle("POST", "/api/auth/login", body={"email": "paciente@midoc.local", "password": "paciente-demo"})["body"])
        response = handle("POST", "/api/appointments", {"authorization": f"Bearer {login['token']}"}, {"doctorId": "d-1", "dateTime": "2026-10-20T10:00:00Z"})
        self.assertEqual(response["statusCode"], 201)

    def test_records_require_authentication(self):
        self.assertEqual(handle("GET", "/api/records")["statusCode"], 401)

    def test_consent_allows_doctor_record_access(self):
        patient = json.loads(handle("POST", "/api/auth/login", body={"email": "paciente@midoc.local", "password": "paciente-demo"})["body"])
        patient_headers = {"authorization": f"Bearer {patient['token']}"}
        handle("POST", "/api/consents", patient_headers, {"doctorId": "d-1", "granted": True})
        doctor = json.loads(handle("POST", "/api/auth/login", body={"email": "doctor@midoc.local", "password": "doctor-demo"})["body"])
        response = handle("GET", "/api/records?patientId=u-patient-1", {"authorization": f"Bearer {doctor['token']}"})
        self.assertEqual(response["statusCode"], 200)
        DB["consents"].clear()


if __name__ == "__main__":
    unittest.main()
