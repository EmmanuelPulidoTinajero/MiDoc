"""Pruebas de la ampliación de los 3 flujos (modo memoria, sin AWS).

La hora se fija en lunes 19 de octubre de 2026, 08:00 (Ciudad de México).
"""
import copy
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app import DB, handle  # noqa: E402

import flujos  # noqa: E402
import pagos_stripe  # noqa: E402
import reglas  # noqa: E402

AHORA = datetime(2026, 10, 19, 8, 0, tzinfo=reglas.ZONA)  # lunes
LUNES = "2026-10-19"
MARTES = "2026-10-20"
DB_ORIGINAL = copy.deepcopy(DB)


class Base(unittest.TestCase):
    def setUp(self):
        DB.clear()
        DB.update(copy.deepcopy(DB_ORIGINAL))
        flujos.reset_rate_limits(DB)
        pagos_stripe.limpiar_cache()
        ahora_original = reglas.ahora
        reglas.ahora = lambda: AHORA
        self.addCleanup(setattr, reglas, "ahora", ahora_original)

    def api(self, method, path, body=None, token=None, esperado=None, headers=None):
        req_headers = dict(headers or {})
        if token:
            req_headers["authorization"] = f"Bearer {token}"
        respuesta = handle(method, path, req_headers, body)
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

    def registrar_doctor(self, email="nuevo@doc.mx", rol="DOCTOR", **extra):
        datos = {
            "specialty": "Pediatría",
            "location": "Av. Vallarta 100",
            "city": "Zapopan",
            "price": 500,
            "durationMin": 30,
            **extra,
        }
        return self.registrar(email, rol, **datos)

    def agendar(self, token, fecha_hora, doctor="d-1", esperado=201, headers=None):
        return self.api("POST", "/api/appointments", {"doctorId": doctor, "dateTime": fecha_hora}, token, esperado, headers=headers)[1]

    def activar_suscripcion_stripe(self, token, doctor_id, session_id="cs_test_demo_123456"):
        env = {"PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_test_dummy_12345"}
        checkout_resp = {"id": session_id, "url": f"https://checkout.stripe.com/c/pay/{session_id}"}
        confirm_resp = {
            "id": session_id,
            "payment_status": "paid",
            "status": "complete",
            "amount_total": 2000,
            "currency": "usd",
            "livemode": False,
            "client_reference_id": doctor_id,
            "metadata": {"doctorId": doctor_id},
            "payment_intent": {
                "id": "pi_test_12345",
                "payment_method": {"card": {"brand": "visa", "last4": "4242"}},
            },
        }
        with patch.dict(os.environ, env, clear=False), \
                patch.object(pagos_stripe, "_stripe_request", side_effect=[checkout_resp, confirm_resp]):
            self.api("POST", "/api/subscriptions/checkout", {}, token, esperado=201)
            return self.api("POST", "/api/subscriptions/confirm", {"sessionId": session_id}, token, esperado=200)[1]


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


class CuentaYSeguridad(Base):
    def test_put_me_actualiza_perfil_y_contrasena(self):
        paciente = self.registrar("paciente.edit@correo.mx")
        _, actualizado = self.api(
            "PUT",
            "/api/me",
            {"name": "Ana Actualizada", "phone": "3312345678"},
            paciente["token"],
            esperado=200,
        )
        self.assertEqual(actualizado["data"]["name"], "Ana Actualizada")
        self.assertEqual(actualizado["data"]["phone"], "3312345678")

        doctor = self.registrar_doctor("doc.edit@correo.mx")
        _, doc_upd = self.api(
            "PUT",
            "/api/me",
            {
                "nombreCompleto": "Dr. Carlos Ruiz",
                "especialidad": "Cardiología",
                "ubicacion": "Av. México 200",
                "ciudad": "Guadalajara",
                "precioConsulta": 950,
                "duracionCitaMin": 45,
                "biografia": "Especialista en prevención cardiovascular.",
            },
            doctor["token"],
            esperado=200,
        )
        self.assertEqual(doc_upd["data"]["doctor"]["name"], "Dr. Carlos Ruiz")
        self.assertEqual(doc_upd["data"]["doctor"]["specialty"], "Cardiología")
        self.assertEqual(doc_upd["data"]["doctor"]["price"], 950.0)
        self.assertEqual(doc_upd["data"]["doctor"]["durationMin"], 45)
        self.assertEqual(doc_upd["data"]["doctor"]["biografia"], "Especialista en prevención cardiovascular.")

        # Cambio de contraseña
        self.api(
            "PUT",
            "/api/me",
            {"currentPassword": "Incorrecta1", "newPassword": "Nueva999"},
            paciente["token"],
            esperado=400,
        )
        self.api(
            "PUT",
            "/api/me",
            {"currentPassword": "Segura123", "newPassword": "corta"},
            paciente["token"],
            esperado=400,
        )
        self.api(
            "PUT",
            "/api/me",
            {"currentPassword": "Segura123", "newPassword": "NuevaSegura123"},
            paciente["token"],
            esperado=200,
        )
        self.login("paciente.edit@correo.mx", "NuevaSegura123")

    def test_auth_refresh_emite_nuevo_token(self):
        token = self.paciente_demo()
        _, ref = self.api("POST", "/api/auth/refresh", {}, token, esperado=200)
        self.assertTrue(ref["token"])
        self.assertEqual(ref["user"]["email"], "paciente@midoc.local")
        self.api("POST", "/api/auth/refresh", {}, token="invalido", esperado=401)

    def test_login_rate_limiting_bloquea_tras_intentos_fallidos(self):
        for _ in range(flujos.MAX_LOGIN_INTENTOS):
            self.api("POST", "/api/auth/login", {"email": "paciente@midoc.local", "password": "mal"}, esperado=401)
        self.api("POST", "/api/auth/login", {"email": "paciente@midoc.local", "password": "mal"}, esperado=429)
        # Incluso la contraseña correcta queda bloqueada durante la ventana
        self.api("POST", "/api/auth/login", {"email": "paciente@midoc.local", "password": "paciente-demo"}, esperado=429)
        flujos.reset_rate_limits(DB)
        self.paciente_demo()

    def test_login_rate_limiting_no_se_evade_con_xff_izquierdo_falsificado(self):
        real_ip_headers = {"X-Forwarded-For": "203.0.113.10"}
        for _ in range(flujos.MAX_LOGIN_INTENTOS):
            self.api(
                "POST",
                "/api/auth/login",
                {"email": "paciente@midoc.local", "password": "mal"},
                headers=real_ip_headers,
                esperado=401,
            )
        self.api(
            "POST",
            "/api/auth/login",
            {"email": "paciente@midoc.local", "password": "mal"},
            headers=real_ip_headers,
            esperado=429,
        )
        # El atacante antepone una IP falsa en X-Forwarded-For; el proxy agrega la IP real a la derecha
        self.api(
            "POST",
            "/api/auth/login",
            {"email": "paciente@midoc.local", "password": "mal"},
            headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.10"},
            esperado=429,
        )
        # Una IP real diferente no está bloqueada
        self.api(
            "POST",
            "/api/auth/login",
            {"email": "paciente@midoc.local", "password": "mal"},
            headers={"X-Forwarded-For": "10.9.9.9"},
            esperado=401,
        )


class Flujo1BusquedaYAgenda(Base):
    def test_buscar_ver_perfil_disponibilidad_y_agendar(self):
        token = self.paciente_demo()
        _, doctores = self.api("GET", "/api/doctors?specialty=familiar&location=guadalajara", esperado=200)
        self.assertEqual([d["id"] for d in doctores["data"]], ["d-1"])
        self.assertIn("nextAvailableSlot", doctores["data"][0])
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

    def test_buscar_doctores_ordenamiento_y_promocion(self):
        doc_caro = self.registrar_doctor("caro@doc.mx", name="Dr. Benito", price=900)
        self.activar_suscripcion_stripe(doc_caro["token"], doc_caro["user"]["doctorId"], "cs_test_caro_123456")
        doc_barato = self.registrar_doctor("barato@doc.mx", name="Dr. Carlos", price=300)
        self.activar_suscripcion_stripe(doc_barato["token"], doc_barato["user"]["doctorId"], "cs_test_barato_1234")
        # Horario temprano para doc_barato (lunes 19 a las 09:00)
        self.api(
            "PUT",
            "/api/doctor/schedule",
            {"blocks": [{"day": 1, "start": "09:00", "end": "10:00"}]},
            doc_barato["token"],
            esperado=200,
        )
        self.api(
            "POST",
            "/api/doctor/promotions",
            {"title": "20% dto", "discountPercent": 20, "start": LUNES, "end": MARTES},
            doc_caro["token"],
            esperado=201,
        )
        asc = [d["price"] for d in self.api("GET", "/api/doctors?sort=price_asc", esperado=200)[1]["data"]]
        self.assertEqual(asc, [300.0, 600.0, 900.0])
        desc = [d["price"] for d in self.api("GET", "/api/doctors?sort=price_desc", esperado=200)[1]["data"]]
        self.assertEqual(desc, [900.0, 600.0, 300.0])
        disp = self.api("GET", "/api/doctors?sort=availability", esperado=200)[1]["data"]
        caro_item = next(d for d in disp if d["id"] == doc_caro["user"]["doctorId"])
        self.assertIsNone(caro_item["nextAvailableSlot"])
        self.assertEqual(caro_item["promotionSummary"]["discountedPrice"], 720.0)
        self.assertEqual(disp[-1]["id"], doc_caro["user"]["doctorId"])
        self.api("GET", "/api/doctors?sort=invalido", esperado=400)

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

        self.activar_suscripcion_stripe(nuevo["token"], doctor_id)
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

    def test_paciente_cancela_y_doctor_confirma_citas(self):
        paciente, doctor = self.paciente_demo(), self.doctor_demo()
        cita_cancelada = self.agendar(paciente, f"{LUNES}T09:00:00-06:00")["data"]
        self.api("PUT", f"/api/appointments/{cita_cancelada['id']}/status", {"status": "CONFIRMADA"},
                 paciente, esperado=403)
        _, cancelada = self.api("PUT", f"/api/appointments/{cita_cancelada['id']}/status",
                                {"status": "CANCELADA"}, paciente, esperado=200)
        self.assertEqual(cancelada["data"]["status"], "CANCELADA")
        cita_confirmada = self.agendar(paciente, f"{LUNES}T09:00:00-06:00")["data"]
        _, confirmada = self.api("PUT", f"/api/appointments/{cita_confirmada['id']}/status",
                                {"status": "CONFIRMADA"}, doctor, esperado=200)
        self.assertEqual(confirmada["data"]["status"], "CONFIRMADA")
        self.api("PUT", f"/api/appointments/{cita_confirmada['id']}/status", {"status": "CANCELADA"},
                 self.registrar("ajeno@correo.mx")["token"], esperado=404)

    def test_reprogramar_cita_valida_horario_y_avisa_a_ambas_partes(self):
        paciente, doctor = self.paciente_demo(), self.doctor_demo()
        primera = self.agendar(paciente, f"{LUNES}T09:00:00-06:00")["data"]
        segunda = self.agendar(self.registrar("otro-paciente@correo.mx")["token"],
                               f"{LUNES}T10:00:00-06:00")["data"]
        ruta = f"/api/appointments/{primera['id']}/reschedule"
        self.api("PUT", ruta, {"dateTime": f"{LUNES}T10:00:00-06:00"}, paciente, esperado=409)
        _, actualizada = self.api("PUT", ruta, {"dateTime": f"{LUNES}T11:00:00-06:00"}, paciente, esperado=200)
        self.assertEqual(actualizada["data"]["dateTime"], f"{LUNES}T11:00:00-06:00")
        avisos_doctor = self.api("GET", "/api/notifications", token=doctor)[1]["data"]
        avisos_paciente = self.api("GET", "/api/notifications", token=paciente)[1]["data"]
        self.assertTrue(any(n["type"] == "CITA_REPROGRAMADA" for n in avisos_doctor))
        self.assertTrue(any(n["type"] == "CITA_SOLICITADA" for n in avisos_paciente))
        notificacion = avisos_paciente[0]
        self.api("PUT", f"/api/notifications/{notificacion['id']}/read", {}, paciente, esperado=200)
        self.api("PUT", f"/api/notifications/{notificacion['id']}/read", {}, doctor, esperado=404)
        self.api("GET", f"/api/appointments/{segunda['id']}", token=paciente, esperado=404)

    def test_mensajes_se_limitan_a_pacientes_y_doctores_con_relacion(self):
        paciente, doctor = self.paciente_demo(), self.doctor_demo()
        cita = self.agendar(paciente, f"{LUNES}T09:00:00-06:00")["data"]
        doctor_id = "u-doctor-1"
        _, enviado = self.api("POST", "/api/messages", {"recipientId": doctor_id, "content": "Confirmo mi asistencia."},
                              paciente, esperado=201)
        self.assertEqual(enviado["data"]["content"], "Confirmo mi asistencia.")
        inbox = self.api("GET", "/api/messages", token=doctor, esperado=200)[1]["data"]
        self.assertEqual((inbox[0]["userId"], inbox[0]["unread"]), ("u-patient-1", 1))
        conversacion = self.api("GET", f"/api/messages/{cita['patientId']}", token=doctor, esperado=200)[1]["data"]
        self.assertEqual(conversacion[0]["id"], enviado["data"]["id"])
        self.assertTrue(conversacion[0]["read"])
        self.api("GET", f"/api/messages/{doctor_id}", token=self.registrar("ajeno@correo.mx")["token"], esperado=404)
        self.assertTrue(any(n["type"] == "MENSAJE_NUEVO" for n in
                            self.api("GET", "/api/notifications", token=doctor)[1]["data"]))

    def test_idempotency_key_en_citas_y_mensajes(self):
        paciente = self.paciente_demo()
        headers = {"Idempotency-Key": "cita-unica-1"}
        primera = self.agendar(paciente, f"{LUNES}T09:00:00-06:00", headers=headers)["data"]
        segunda = self.agendar(paciente, f"{LUNES}T09:00:00-06:00", headers=headers)["data"]
        self.assertEqual(primera["id"], segunda["id"])
        self.assertEqual(len(DB["appointments"]), 1)
        # Misma clave con distinto payload -> 409
        self.agendar(paciente, f"{LUNES}T10:00:00-06:00", esperado=409, headers=headers)
        # Misma clave en otra ruta del mismo usuario -> 409 (no ejecuta segunda mutación)
        self.api(
            "POST",
            "/api/messages",
            {"recipientId": "u-doctor-1", "content": "Hola"},
            paciente,
            409,
            headers=headers,
        )
        self.assertEqual(len(DB["messages"]), 0)

        h_msg = {"Idempotency-Key": "msg-unico-1"}
        m1 = self.api("POST", "/api/messages", {"recipientId": "u-doctor-1", "content": "Hola"}, paciente, 201, headers=h_msg)[1]["data"]
        m2 = self.api("POST", "/api/messages", {"recipientId": "u-doctor-1", "content": "Hola"}, paciente, 201, headers=h_msg)[1]["data"]
        self.assertEqual(m1["id"], m2["id"])
        self.assertEqual(len(DB["messages"]), 1)

    def test_notificaciones_generan_recordatorio_y_vencimiento_una_vez(self):
        paciente, doctor = self.paciente_demo(), self.doctor_demo()
        citas = self.agendar(paciente, f"{LUNES}T09:00:00-06:00")["data"]
        # Simula una próxima cita dentro de 24 horas y vencimiento próximo.
        DB["appointments"][0]["dateTime"] = (AHORA + timedelta(hours=2)).isoformat()
        DB["subscriptions"][0]["end"] = AHORA.date() + timedelta(days=4)
        self.api("GET", "/api/notifications", token=doctor)
        segundo = self.api("GET", "/api/notifications", token=doctor)[1]["data"]
        tipos = [n["type"] for n in segundo]
        self.assertEqual(tipos.count("RECORDATORIO_CITA"), 1)
        self.assertEqual(tipos.count("VENCIMIENTO_SUSCRIPCION"), 1)
        self.assertEqual(citas["status"], "PENDIENTE")

    def test_doctor_administra_inventario_y_promociones_publicas(self):
        doctor = self.doctor_demo()
        _, item = self.api("POST", "/api/doctor/inventory", {"name": "Guantes", "quantity": 12, "unit": "cajas"},
                           doctor, esperado=201)
        _, actualizado = self.api("POST", "/api/doctor/inventory", {"name": "Guantes", "quantity": 8, "unit": "cajas"},
                                  doctor, esperado=201)
        self.assertEqual(actualizado["data"]["quantity"], 8)
        self.assertEqual(len(self.api("GET", "/api/doctor/inventory", token=doctor)[1]["data"]), 1)
        self.api("DELETE", f"/api/doctor/inventory/{item['data']['id']}", token=doctor, esperado=200)
        promocion = {"title": "Chequeo preventivo", "description": "Consulta inicial", "discountPercent": 15,
                     "start": AHORA.date().isoformat(), "end": (AHORA.date() + timedelta(days=7)).isoformat()}
        _, creada = self.api("POST", "/api/doctor/promotions", promocion, doctor, esperado=201)
        listado = self.api("GET", "/api/doctors?q=Ana", esperado=200)[1]["data"]
        self.assertEqual(listado[0]["promotions"][0]["id"], creada["data"]["id"])
        self.assertEqual(listado[0]["promotionSummary"]["maxDiscountPercent"], 15)
        self.api("DELETE", f"/api/doctor/promotions/{creada['data']['id']}", token=doctor, esperado=200)


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

    def test_otorgar_y_revocar_acceso_bitacora_y_notificacion(self):
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

        # Bitácora visible para el paciente y bloqueada para el doctor
        _, bitacora = self.api("GET", "/api/records/access-log", token=paciente, esperado=200)
        self.assertEqual(len(bitacora["data"]), 1)
        self.assertEqual(bitacora["data"][0]["actorName"], "Dra. Ana López")
        self.api("GET", "/api/records/access-log", token=doctor, esperado=403)

        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": False}, paciente, esperado=200)
        self.api("GET", ruta, token=doctor, esperado=403)
        _, lista = self.api("GET", "/api/consents", token=paciente, esperado=200)
        self.assertEqual((lista["data"][0]["doctorName"], lista["data"][0]["granted"]), ("Dra. Ana López", False))
        self.api("POST", "/api/consents", {"doctorId": "d-999", "granted": True}, paciente, esperado=404)

        avisos = self.api("GET", "/api/notifications", token=doctor, esperado=200)[1]["data"]
        self.assertTrue(any(n["type"] == "CONSENTIMIENTO_OTORGADO" for n in avisos))
        self.assertTrue(any(n["type"] == "CONSENTIMIENTO_REVOCADO" for n in avisos))


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

    def test_pago_de_suscripcion_stripe(self):
        nuevo = self.registrar_doctor()
        token = nuevo["token"]
        doctor_id = nuevo["user"]["doctorId"]
        self.api("GET", "/api/doctor/patients", token=token, esperado=402)
        # Endpoint simulado retirado
        self.api("POST", "/api/subscriptions/pay", {}, token, esperado=410)

        env = {"PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_test_dummy_12345"}
        with patch.dict(os.environ, env, clear=False), patch.object(
            pagos_stripe,
            "_stripe_request",
            side_effect=[
                {"id": "cs_test_0001_abcdef", "url": "https://checkout.stripe.com/c/pay/cs_test_0001_abcdef"},
                {
                    "id": "cs_test_0001_abcdef",
                    "payment_status": "unpaid",
                    "status": "open",
                    "livemode": False,
                    "metadata": {"doctorId": doctor_id},
                },
                {
                    "id": "cs_test_0001_abcdef",
                    "payment_status": "paid",
                    "status": "complete",
                    "amount_total": 2000,
                    "livemode": False,
                    "metadata": {"doctorId": doctor_id},
                    "payment_intent": {
                        "id": "pi_test_0001",
                        "payment_method": {"card": {"brand": "visa", "last4": "4242"}},
                    },
                },
                {"id": "cs_test_0002_abcdef", "url": "https://checkout.stripe.com/c/pay/cs_test_0002_abcdef"},
                {
                    "id": "cs_test_0002_abcdef",
                    "payment_status": "paid",
                    "status": "complete",
                    "amount_total": 2000,
                    "livemode": False,
                    "metadata": {"doctorId": doctor_id},
                    "payment_intent": {
                        "id": "pi_test_0002",
                        "payment_method": {"card": {"brand": "mastercard", "last4": "4444"}},
                    },
                },
            ],
        ):
            _, ck = self.api("POST", "/api/subscriptions/checkout", {}, token, esperado=201)
            self.assertEqual((ck["data"]["mode"], ck["data"]["amountUsd"]), ("test", 20.0))
            self.api("POST", "/api/subscriptions/confirm", {"sessionId": "cs_test_0001_abcdef"}, token, esperado=402)
            _, conf1 = self.api("POST", "/api/subscriptions/confirm", {"sessionId": "cs_test_0001_abcdef"}, token, esperado=200)
            self.assertEqual((conf1["data"]["payment"]["cardLast4"], conf1["data"]["subscription"]["start"], conf1["data"]["subscription"]["end"]),
                             ("4242", LUNES, "2026-11-17"))
            # Confirmar dos veces la misma sesión es idempotente (no encadena otros 30 días)
            _, conf1_rep = self.api("POST", "/api/subscriptions/confirm", {"sessionId": "cs_test_0001_abcdef"}, token, esperado=200)
            self.assertEqual(conf1_rep["data"]["subscription"]["end"], "2026-11-17")

            # Segunda sesión pagada por adelantado sí encadena 30 días adicionales
            self.api("POST", "/api/subscriptions/checkout", {}, token, esperado=201)
            _, conf2 = self.api("POST", "/api/subscriptions/confirm", {"sessionId": "cs_test_0002_abcdef"}, token, esperado=200)
            self.assertEqual(conf2["data"]["subscription"]["start"], LUNES)
            self.assertEqual(conf2["data"]["subscription"]["end"], "2026-12-17")
            self.assertEqual(conf2["data"]["payment"]["start"], "2026-11-18")

            _, suscripcion = self.api("GET", "/api/subscriptions", token=token, esperado=200)
            self.assertTrue(suscripcion["data"]["subscription"]["active"])
            self.assertEqual(suscripcion["data"]["paymentMode"], "test")
            self.assertEqual(len(suscripcion["data"]["history"]), 2)

        self.api("GET", "/api/doctor/patients", token=token, esperado=200)
        self.api("GET", "/api/subscriptions", token=self.paciente_demo(), esperado=403)

    def test_consulta_completa_la_cita_y_aparece_en_el_historial(self):
        paciente, doctor, cita = self.preparar_cita()
        reglas.ahora = lambda: AHORA.replace(hour=10)
        _, registro = self.consulta(cita, doctor, notes="Control en 4 semanas")
        receta_id = registro["data"]["prescriptionId"]
        self.assertIn(receta_id, DB["prescription_pdfs"])
        self.assertTrue(DB["prescription_pdfs"][receta_id].startswith(b"%PDF-1.4"))

        self.assertEqual(self.api("GET", f"/api/appointments/{cita['id']}", token=paciente)[1]["data"]["status"],
                         "COMPLETADA")
        historial = self.api("GET", "/api/records", token=paciente)[1]["data"]["consultations"]
        self.assertEqual((historial[0]["prescriptionId"], historial[0]["diagnosis"]), (receta_id, "Hipertensión grado 1"))
        self.assertEqual(historial[0]["notes"], "Control en 4 semanas")
        receta = self.api("GET", f"/api/prescriptions/{receta_id}", token=paciente, esperado=200)[1]["data"]
        self.assertEqual((receta["diagnosis"], receta["treatment"]),
                         ("Hipertensión grado 1", "Losartán 50 mg cada 24 h"))
        self.assertFalse(receta["hasPdf"])
        self.api("GET", f"/api/prescriptions/{receta_id}", token=self.registrar("ajeno@correo.mx")["token"],
                 esperado=404)
        self.consulta(cita, doctor, esperado=409)  # no se registra dos veces

    def test_reglas_de_la_consulta(self):
        paciente, doctor, cita = self.preparar_cita(consentimiento=False)
        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": True}, paciente, esperado=200)
        self.consulta(cita, doctor, esperado=409)                       # la cita todavía no comienza
        reglas.ahora = lambda: AHORA.replace(hour=10)
        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": False}, paciente, esperado=200)
        self.consulta(cita, doctor, esperado=403)                       # sin consentimiento
        self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": True}, paciente, esperado=200)
        self.consulta(cita, doctor, esperado=400, treatment="")         # falta tratamiento
        futura = self.agendar(paciente, f"{MARTES}T09:00:00-06:00")["data"]
        self.consulta(futura, doctor, esperado=409)                     # cita futura
        otro_reg = self.registrar_doctor("otro@doc.mx")
        self.activar_suscripcion_stripe(otro_reg["token"], otro_reg["user"]["doctorId"], "cs_test_otro_123456")
        self.consulta(cita, otro_reg["token"], esperado=404)            # la cita es de otro doctor
        self.consulta(cita, paciente, esperado=403)                     # solo doctores


class Transacciones(Base):
    def test_recordatorios_programados_sin_peticion_de_notificaciones(self):
        paciente = self.paciente_demo()
        self.agendar(paciente, f"{LUNES}T09:00:00-06:00")
        app = sys.modules[handle.__module__]
        flujos.generar_recordatorios(app)
        recordatorios = [n for n in DB["notifications"] if n["type"] == "RECORDATORIO_CITA"]
        self.assertEqual(len(recordatorios), 2)
        flujos.generar_recordatorios(app)
        self.assertEqual(len([n for n in DB["notifications"] if n["type"] == "RECORDATORIO_CITA"]), 2)

    def test_cita_y_notificaciones_se_revierten_si_falla_el_aviso(self):
        token = self.paciente_demo()
        flujos.RepoMemoria(sys.modules[handle.__module__])
        anterior = copy.deepcopy(DB)
        with patch.object(flujos.RepoMemoria, "notificar", side_effect=RuntimeError("fallo simulado")):
            self.agendar(token, f"{MARTES}T09:00:00-06:00", esperado=500)
        self.assertEqual(DB, anterior)
        self.agendar(token, f"{MARTES}T09:00:00-06:00", esperado=201)

    def test_consentimiento_y_notificacion_se_revierten_juntos(self):
        paciente = self.paciente_demo()
        flujos.RepoMemoria(sys.modules[handle.__module__])
        anterior = copy.deepcopy(DB)
        with patch.object(flujos.RepoMemoria, "notificar", side_effect=RuntimeError("fallo simulado")):
            self.api("POST", "/api/consents", {"doctorId": "d-1", "granted": True}, paciente, esperado=500)
        self.assertEqual(DB, anterior)

    def test_mensaje_y_notificacion_se_revierten_juntos(self):
        paciente = self.paciente_demo()
        self.agendar(paciente, f"{MARTES}T09:00:00-06:00")
        anterior = copy.deepcopy(DB)
        with patch.object(flujos.RepoMemoria, "notificar", side_effect=RuntimeError("fallo simulado")):
            self.api("POST", "/api/messages", {"recipientId": "u-doctor-1", "content": "Prueba"},
                     paciente, esperado=500)
        self.assertEqual(DB, anterior)

    def test_postgres_reutiliza_conexion_y_confirma_una_sola_vez(self):
        app = MagicMock()
        conexion = app._database_connection.return_value
        repo = flujos.RepoPostgres(app)
        with repo.atomic("paciente"):
            repo.q("SELECT 1")
            repo._transaccion(lambda cur: cur.execute("SELECT 2") or True)
            conexion.commit.assert_not_called()
        app._database_connection.assert_called_once()
        app._query.assert_not_called()
        conexion.commit.assert_called_once()
        conexion.close.assert_called_once()
        conexion.rollback.assert_not_called()

    def test_postgres_revierte_si_falla_notificacion(self):
        app = MagicMock()
        conexion = app._database_connection.return_value
        repo = flujos.RepoPostgres(app)
        with self.assertRaises(RuntimeError):
            with repo.atomic("paciente"):
                repo.q("SELECT 1")
                raise RuntimeError("fallo simulado")
        conexion.rollback.assert_called_once()
        conexion.commit.assert_not_called()
        conexion.close.assert_called_once()


class Errores(Base):
    def test_cuerpo_que_no_es_objeto(self):
        self.assertEqual(handle("POST", "/api/auth/login", {}, ["no", "objeto"])["statusCode"], 400)

    def test_cors_incluye_put_patch_y_idempotency(self):
        headers = handle("OPTIONS", "/api/records")["headers"]
        metodos = headers["access-control-allow-methods"]
        self.assertIn("PUT", metodos)
        self.assertIn("PATCH", metodos)
        self.assertIn("DELETE", metodos)
        self.assertIn("idempotency-key", headers["access-control-allow-headers"])

    def test_documentos_se_validan_y_requieren_s3_configurado(self):
        paciente = self.paciente_demo()
        _, error = self.api("POST", "/api/records/documents", {
            "name": "archivo.exe", "contentType": "application/pdf", "size": 120
        }, paciente, esperado=400)
        self.assertIn("PDF, JPG", error["error"])
        self.api("POST", "/api/records/documents", {
            "name": "estudio.dcm", "contentType": "text/plain", "size": 120
        }, paciente, esperado=400)
        self.api("POST", "/api/records/documents", {
            "name": "estudio.pdf", "contentType": "application/pdf", "size": 120
        }, paciente, esperado=503)

    def test_documentos_dicom_acepta_dicom_octet_stream_y_vacio(self):
        paciente = self.paciente_demo()
        s3_mock = MagicMock()
        s3_mock.generate_presigned_post.side_effect = lambda **kw: {
            "url": "https://s3.example.com/bucket",
            "fields": kw["Fields"],
        }
        boto3_mock = MagicMock()
        boto3_mock.client.return_value = s3_mock

        with patch.dict(os.environ, {"MEDICAL_DOCUMENTS_BUCKET": "midoc-docs"}, clear=False), \
                patch.dict(sys.modules, {"boto3": boto3_mock}):
            for ct, esperado_ct in (
                ("application/dicom", "application/dicom"),
                ("application/octet-stream", "application/octet-stream"),
                ("", "application/dicom"),
            ):
                with self.subTest(contentType=ct):
                    _, res = self.api(
                        "POST",
                        "/api/records/documents",
                        {"name": "radiografia.dcm", "contentType": ct, "size": 2048},
                        paciente,
                        esperado=201,
                    )
                    self.assertEqual(res["data"]["fields"]["Content-Type"], esperado_ct)
            self.api(
                "POST",
                "/api/records/documents",
                {"name": "radiografia.dcm", "contentType": "text/plain", "size": 2048},
                paciente,
                esperado=400,
            )
            self.api(
                "POST",
                "/api/records/documents",
                {"name": "script.exe", "contentType": "application/octet-stream", "size": 2048},
                paciente,
                esperado=400,
            )

    def test_ruta_inexistente(self):
        self.api("GET", "/api/no-existe", token=self.paciente_demo(), esperado=404)


if __name__ == "__main__":
    unittest.main()
