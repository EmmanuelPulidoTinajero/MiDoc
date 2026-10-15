"""Pruebas de la ampliación de los 3 flujos (modo memoria, sin AWS).

La hora se fija en lunes 19 de octubre de 2026, 08:00 (Ciudad de México).
"""
import copy
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app import DB, handle  # noqa: E402

import reglas  # noqa: E402  (src/ queda en sys.path al importar app)

AHORA = datetime(2026, 10, 19, 8, 0, tzinfo=reglas.ZONA)  # lunes
LUNES = "2026-10-19"
MARTES = "2026-10-20"
DB_ORIGINAL = copy.deepcopy(DB)
TARJETA = {"cardHolder": "Dr Prueba", "cardNumber": "4242 4242 4242 4242", "expMonth": 12, "expYear": 2028, "cvv": "123"}



class Base(unittest.TestCase):
    def setUp(self):
        DB.clear()
        DB.update(copy.deepcopy(DB_ORIGINAL))
        ahora_original = reglas.ahora
        reglas.ahora = lambda: AHORA
        self.addCleanup(setattr, reglas, "ahora", ahora_original)

    def api(self, method, path, body=None, token=None, esperado=None):
        headers = {"authorization": f"Bearer {token}"} if token else {}
        respuesta = handle(method, path, headers, body)
        cuerpo = json.loads(respuesta["body"])
        if esperado is not None:
            self.assertEqual(respuesta["statusCode"], esperado, cuerpo)
        return respuesta["statusCode"], cuerpo

    def login(self, email, password):
        return self.api("POST", "/api/auth/login", {"email": email, "password": password}, esperado=200)[1]["token"]

    def paciente_demo(self):
        return self.login("paciente@midoc.local", "paciente-demo")

    def doctor_demo(self):
        return self.login("doctor@midoc.local", "doctor-demo")

    def registrar(self, email, rol="PACIENTE", **extra):
        datos = {"email": email, "password": "Segura123", "role": rol, "name": "Usuario Prueba", **extra}
        return self.api("POST", "/api/auth/register", datos, esperado=201)[1]

    def registrar_doctor(self, email="nuevo@doc.mx", rol="DOCTOR"):
        return self.registrar(email, rol, specialty="Pediatría", location="Av. Vallarta 100", city="Zapopan",
                              price=500, durationMin=30)

    def agendar(self, token, fecha_hora, doctor="d-1", esperado=201):
        return self.api("POST", "/api/appointments", {"doctorId": doctor, "dateTime": fecha_hora}, token, esperado)[1]


class Registro(Base):
    def test_registro_de_paciente_y_doctor(self):
        paciente = self.registrar("ana@correo.mx")
        self.assertTrue(paciente["token"])
        self.assertNotIn("password_hash", paciente["user"])
        doctor = self.registrar_doctor()
        self.assertTrue(doctor["user"]["doctorId"])
        _, yo = self.api("GET", "/api/me", token=doctor["token"], esperado=200)
        self.assertEqual(yo["data"]["doctor"]["specialty"], "Pediatría")
        self.assertIsNone(yo["data"]["subscription"])  # nunca ha pagado
        # La cuenta nueva puede iniciar sesión con el login original
        self.login("ana@correo.mx", "Segura123")

    def test_validaciones_del_registro(self):
        self.registrar("ana@correo.mx")
        self.api("POST", "/api/auth/register", {"email": "ANA@correo.mx", "password": "Segura123", "role": "PACIENTE",
                                                "name": "Otra"}, esperado=409)
        self.api("POST", "/api/auth/register", {"email": "x@correo.mx", "password": "corta", "role": "PACIENTE",
                                                "name": "X"}, esperado=400)
        self.api("POST", "/api/auth/register", {"email": "x@correo.mx", "password": "Segura123", "role": "ADMIN",
                                                "name": "X"}, esperado=400)
        _, cuerpo = self.api("POST", "/api/auth/register", {"email": "d@correo.mx", "password": "Segura123",
                                                            "role": "DOCTOR", "name": "Doc"}, esperado=400)
        self.assertIn("specialty", cuerpo["error"])


class Flujo1BusquedaYAgenda(Base):
    def test_buscar_ver_perfil_disponibilidad_y_agendar(self):
        token = self.paciente_demo()
        _, doctores = self.api("GET", "/api/doctors?specialty=familiar&location=guadalajara", esperado=200)
        self.assertEqual([d["id"] for d in doctores["data"]], ["d-1"])
        self.assertEqual(self.api("GET", "/api/doctors?location=monterrey")[1]["data"], [])

        _, perfil = self.api("GET", "/api/doctors/d-1", esperado=200)
        self.assertEqual(len(perfil["data"]["schedule"]), 10)

        _, disponibilidad = self.api("GET", f"/api/doctors/d-1/availability?date={MARTES}", esperado=200)
        slots = disponibilidad["data"]["slots"]
        self.assertEqual(slots[0], "2026-10-20T09:00:00-06:00")

        cita = self.agendar(token, slots[0])["data"]
        self.assertEqual((cita["status"], cita["doctorName"]), ("PENDIENTE", "Dra. Ana López"))
        libres = self.api("GET", f"/api/doctors/d-1/availability?date={MARTES}")[1]["data"]["slots"]
        self.assertNotIn(slots[0], libres)
        # La agenda del doctor muestra la cita con el nombre del paciente
        agenda = self.api("GET", "/api/appointments", token=self.doctor_demo(), esperado=200)[1]["data"]
        self.assertEqual(agenda[0]["patientName"], "Paciente Demo")

    def test_no_se_agenda_ocupado_fuera_de_horario_ni_en_el_pasado(self):
        token = self.paciente_demo()
        otro = self.registrar("otro@correo.mx")["token"]
        self.agendar(token, f"{MARTES}T10:00:00-06:00")
        self.agendar(otro, f"{MARTES}T16:00:00Z", esperado=409)        # = 10:00 en CDMX, ya ocupado
        self.agendar(otro, f"{MARTES}T10:15:00-06:00", esperado=409)   # no cae en un bloque de 30 min
        self.agendar(otro, f"{MARTES}T21:00:00-06:00", esperado=409)   # fuera del horario
        self.agendar(otro, "2026-10-18T10:00:00-06:00", esperado=400)  # en el pasado
        self.agendar(otro, "mañana", esperado=400)

    def test_doctor_sin_suscripcion_no_aparece_ni_recibe_citas(self):
        nuevo = self.registrar_doctor()
        doctor_id = nuevo["user"]["doctorId"]
        self.api("PUT", "/api/doctor/schedule", {"blocks": [{"day": 2, "start": "09:00", "end": "12:00"}]},
                 nuevo["token"], esperado=200)
        self.assertEqual(self.api("GET", "/api/doctors?specialty=pedia")[1]["data"], [])
        self.api("GET", f"/api/doctors/{doctor_id}", esperado=404)
        self.agendar(self.paciente_demo(), f"{MARTES}T09:00:00-06:00", doctor=doctor_id, esperado=404)

        self.api("POST", "/api/subscriptions/pay", TARJETA, nuevo["token"], esperado=201)
        self.assertEqual(len(self.api("GET", "/api/doctors?q=zapopan")[1]["data"]), 1)
        self.agendar(self.paciente_demo(), f"{MARTES}T09:00:00-06:00", doctor=doctor_id)

    def test_una_cita_ajena_no_se_ve(self):
        cita = self.agendar(self.paciente_demo(), f"{MARTES}T11:00:00-06:00")["data"]
        ajeno = self.registrar("ajeno@correo.mx")["token"]
        self.api("GET", f"/api/appointments/{cita['id']}", token=ajeno, esperado=404)
        self.api("GET", f"/api/appointments/{cita['id']}", token=self.doctor_demo(), esperado=200)

    def test_horario_invalido(self):
        token = self.doctor_demo()
        encimados = {"blocks": [{"day": 1, "start": "09:00", "end": "12:00"}, {"day": 1, "start": "11:00", "end": "13:00"}]}
        self.api("PUT", "/api/doctor/schedule", encimados, token, esperado=400)
        self.api("PUT", "/api/doctor/schedule", {"blocks": [{"day": 8, "start": "09:00", "end": "10:00"}]}, token, esperado=400)
        self.api("PUT", "/api/doctor/schedule", {"blocks": [{"day": 1, "start": "12:00", "end": "09:00"}]}, token, esperado=400)


class Flujo2ExpedienteYConsentimiento(Base):
    EXPEDIENTE = {"birthDate": "1990-05-14", "sex": "femenino", "bloodType": "o+", "allergies": ["Penicilina"],
                  "chronicConditions": ["Asma"], "medications": ["Salbutamol"], "notes": "Madre con diabetes"}

    def test_paciente_crea_y_actualiza_su_expediente(self):
        token = self.paciente_demo()
        _, guardado = self.api("PUT", "/api/records", self.EXPEDIENTE, token, esperado=200)
        self.assertEqual((guardado["data"]["bloodType"], guardado["data"]["sex"]), ("O+", "FEMENINO"))
        _, leido = self.api("GET", "/api/records", token=token, esperado=200)
        self.assertEqual(leido["data"]["allergies"], ["Penicilina"])        # campo original
        self.assertEqual(leido["data"]["patient_id"], "u-patient-1")        # campo original
        self.assertEqual(leido["data"]["chronicConditions"], ["Asma"])
        self.api("PUT", "/api/records", {"bloodType": "Z+"}, token, esperado=400)
        self.api("PUT", "/api/records", {"birthDate": "2030-01-01"}, token, esperado=400)
        self.api("PUT", "/api/records", {"allergies": "Penicilina"}, token, esperado=400)
        self.api("PUT", "/api/records", self.EXPEDIENTE, self.doctor_demo(), esperado=403)

    def test_otorgar_y_revocar_acceso(self):
        paciente, doctor = self.paciente_demo(), self.doctor_demo()
        self.api("PUT", "/api/records", self.EXPEDIENTE, paciente, esperado=200)
        ruta = "/api/records?patientId=u-patient-1"
        self.api("GET", ruta, token=doctor, esperado=403)
        self.assertEqual(self.api("GET", "/api/doctor/patients", token=doctor)[1]["data"], [])

        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": True}, paciente, esperado=200)
        _, visto = self.api("GET", ruta, token=doctor, esperado=200)
        self.assertEqual(visto["data"]["allergies"], ["Penicilina"])
        self.assertEqual(len(DB["access_log"]), 1)  # bitácora de accesos
        self.assertEqual([p["name"] for p in self.api("GET", "/api/doctor/patients", token=doctor)[1]["data"]],
                         ["Paciente Demo"])

        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": False}, paciente, esperado=200)
        self.api("GET", ruta, token=doctor, esperado=403)
        _, lista = self.api("GET", "/api/consents", token=paciente, esperado=200)
        self.assertEqual((lista["data"][0]["doctorName"], lista["data"][0]["granted"]), ("Dra. Ana López", False))
        self.api("POST", "/api/consents", {"doctorId": "d-999", "granted": True}, paciente, esperado=404)


class Flujo3SuscripcionYConsulta(Base):
    def preparar_cita(self, fecha_hora=f"{LUNES}T09:00:00-06:00", consentimiento=True):
        paciente, doctor = self.paciente_demo(), self.doctor_demo()
        if consentimiento:
            self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": True}, paciente, esperado=200)
        cita = self.agendar(paciente, fecha_hora)["data"]
        return paciente, doctor, cita

    def consulta(self, cita, token, esperado=201, **extra):
        datos = {"patientId": "u-patient-1", "appointmentId": cita["id"], "diagnosis": "Hipertensión grado 1",
                 "treatment": "Losartán 50 mg cada 24 h", **extra}
        return self.api("POST", "/api/consultations", datos, token, esperado)

    def test_pago_de_suscripcion(self):
        nuevo = self.registrar_doctor()
        token = nuevo["token"]
        self.api("GET", "/api/doctor/patients", token=token, esperado=402)
        self.api("POST", "/api/subscriptions/pay", {**TARJETA, "cardNumber": reglas.TARJETA_RECHAZADA}, token, esperado=402)
        self.api("POST", "/api/subscriptions/pay", {**TARJETA, "cardNumber": "1234567812345678"}, token, esperado=400)
        _, pago = self.api("POST", "/api/subscriptions/pay", TARJETA, token, esperado=201)
        self.assertEqual((pago["data"]["cardLast4"], pago["data"]["start"], pago["data"]["end"]),
                         ("4242", LUNES, "2026-11-17"))
        _, segundo = self.api("POST", "/api/subscriptions/pay", TARJETA, token, esperado=201)
        self.assertEqual(segundo["data"]["start"], "2026-11-18")  # pago adelantado: se encadena
        _, suscripcion = self.api("GET", "/api/subscriptions", token=token, esperado=200)
        self.assertTrue(suscripcion["data"][0]["active"])
        self.api("GET", "/api/doctor/patients", token=token, esperado=200)
        # Comportamiento original: un paciente recibe lista vacía
        self.assertEqual(self.api("GET", "/api/subscriptions", token=self.paciente_demo())[1]["data"], [])

    def test_consulta_completa_la_cita_y_aparece_en_el_historial(self):
        paciente, doctor, cita = self.preparar_cita()
        _, registro = self.consulta(cita, doctor, notes="Control en 4 semanas")
        receta_id = registro["data"]["prescriptionId"]

        self.assertEqual(self.api("GET", f"/api/appointments/{cita['id']}", token=paciente)[1]["data"]["status"],
                         "COMPLETADA")
        historial = self.api("GET", "/api/records", token=paciente)[1]["data"]["consultations"]
        self.assertEqual((historial[0]["prescriptionId"], historial[0]["diagnosis"]), (receta_id, "Hipertensión grado 1"))
        self.assertEqual(historial[0]["notes"], "Control en 4 semanas")
        self.consulta(cita, doctor, esperado=409)  # no se registra dos veces

    def test_reglas_de_la_consulta(self):
        paciente, doctor, cita = self.preparar_cita(consentimiento=False)
        self.consulta(cita, doctor, esperado=403)                       # sin consentimiento
        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": True}, paciente, esperado=200)
        self.consulta(cita, doctor, esperado=400, treatment="")         # falta tratamiento
        futura = self.agendar(paciente, f"{MARTES}T09:00:00-06:00")["data"]
        self.consulta(futura, doctor, esperado=409)                     # cita futura
        otro = self.registrar_doctor()["token"]
        self.api("POST", "/api/subscriptions/pay", TARJETA, otro, esperado=201)
        self.consulta(cita, otro, esperado=404)                         # la cita es de otro doctor
        self.consulta(cita, paciente, esperado=403)                     # solo doctores



class Errores(Base):
    def test_cuerpo_que_no_es_objeto(self):
        self.assertEqual(handle("POST", "/api/auth/login", {}, ["no", "objeto"])["statusCode"], 400)

    def test_cors_incluye_put(self):
        metodos = handle("OPTIONS", "/api/records")["headers"]["access-control-allow-methods"]
        self.assertIn("PUT", metodos)

    def test_ruta_inexistente(self):
        self.api("GET", "/api/no-existe", token=self.paciente_demo(), esperado=404)


if __name__ == "__main__":
    unittest.main()
