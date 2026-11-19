"""Ampliación de los 3 flujos end-to-end prometidos en la fase 1.

Sigue el diseño de app.py: cada operación funciona en dos modos
  * memoria (local y pruebas): usa el diccionario app.DB con datos de demo,
  * PostgreSQL (AWS): usa app._query / app._database_connection.
RepoMemoria y RepoPostgres exponen las mismas operaciones; los handlers de
abajo no saben en qué modo están.

app.py pasa su propio módulo como `app` para evitar importaciones circulares.
"""
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from functools import wraps
from threading import RLock

import metricas
import pagos_stripe
import pdf_receta
import reglas
import servicios_aws
from reglas import ErrorApi, ZONA

HORARIO_DEMO = [
    {"dia_semana": dia, "hora_inicio": time(9, 0), "hora_fin": time(14, 0)} for dia in range(1, 6)
] + [
    {"dia_semana": dia, "hora_inicio": time(16, 0), "hora_fin": time(19, 0)} for dia in range(1, 6)
]

MAX_LOGIN_INTENTOS = 5
VENTANA_LOGIN_SEG = 300
BLOQUEO_LOGIN_SEG = 300

_repositorio_actual = ContextVar("midoc_repositorio", default=None)
_bloqueo_memoria = RLock()
_intentos_login_memoria: dict[str, dict] = {}


def reset_rate_limits(db: dict | None = None) -> None:
    """Reinicia contadores de intentos de login en memoria (útil entre pruebas)."""
    with _bloqueo_memoria:
        _intentos_login_memoria.clear()
        if isinstance(db, dict):
            db.pop("login_attempts", None)


def transaccional(funcion):
    """La operación de negocio y sus notificaciones se confirman juntas."""
    @wraps(funcion)
    def ejecutar(app, *args, **kwargs):
        # Las lecturas y las operaciones de objetos S3 no participan en una
        # transacción PostgreSQL; los objetos tienen su propio ciclo de vida.
        if funcion.__name__ == "atender_autenticado" and len(args) >= 3 and (
            args[1] == "GET" or str(args[2]).startswith("/api/records/documents")
        ):
            return funcion(app, *args, **kwargs)
        usuario = args[0] if args and isinstance(args[0], dict) and "sub" in args[0] else None
        actor_id = usuario["sub"] if usuario else f"job:{funcion.__name__}"
        repo = repositorio(app)
        token = _repositorio_actual.set(repo)
        try:
            with repo.atomic(actor_id):
                return funcion(app, *args, **kwargs)
        finally:
            _repositorio_actual.reset(token)
    return ejecutar


# ===========================================================================
# Repositorio en memoria (modo local de demostración)
# ===========================================================================

class RepoMemoria:
    usa_uuid = False

    def __init__(self, app):
        self.db = app.DB
        self._preparar()

    @contextmanager
    def atomic(self, actor_id):
        with _bloqueo_memoria:
            anterior = deepcopy(self.db)
            try:
                yield
            except Exception:
                self.db.clear()
                self.db.update(anterior)
                raise

    def _preparar(self):
        """Completa los datos de demo de app.DB con los campos nuevos (idempotente)."""
        db = self.db
        nombres = {"u-patient-1": "Paciente Demo", "u-doctor-1": "Dra. Ana López"}
        for usuario in db["users"]:
            usuario.setdefault("name", nombres.get(usuario["id"], usuario["email"]))
            usuario.setdefault("phone", None)
        for doctor in db["doctors"]:
            doctor.setdefault("city", doctor["location"])
            doctor.setdefault("description", "Atención de primer contacto para toda la familia.")
            doctor.setdefault("durationMin", 30)
        db.setdefault("schedules", {})
        if any(d["id"] == "d-1" for d in db["doctors"]):
            db["schedules"].setdefault("d-1", [dict(b) for b in HORARIO_DEMO])
        for suscripcion in db["subscriptions"]:
            suscripcion.setdefault("id", f"sub-{uuid.uuid4().hex[:8]}")
            suscripcion.setdefault("start", reglas.hoy())
            suscripcion.setdefault("end", reglas.hoy() + timedelta(days=reglas.DIAS_SUSCRIPCION - 1))
            suscripcion.setdefault("paymentMode", "test")
            suscripcion.setdefault("paidAt", None)
        db.setdefault("access_log", [])
        db.setdefault("inventory", [])
        db.setdefault("promotions", [])
        db.setdefault("notifications", [])
        db.setdefault("messages", [])
        db.setdefault("idempotency", {})
        db.setdefault("login_attempts", {})
        db.setdefault("prescription_pdfs", {})

    # -- usuarios y seguridad -----------------------------------------------
    def _usuario(self, usuario):
        doctor = next((d for d in self.db["doctors"] if d["user_id"] == usuario["id"]), None)
        return {
            "id": usuario["id"],
            "email": usuario["email"],
            "role": usuario["role"],
            "name": usuario.get("name"),
            "phone": usuario.get("phone"),
            "doctorId": doctor["id"] if doctor else None,
            "password_hash": usuario["password_hash"],
        }

    def usuario_por_email(self, email):
        usuario = next((u for u in self.db["users"] if u["email"] == email), None)
        return self._usuario(usuario) if usuario else None

    def usuario(self, usuario_id):
        usuario = next((u for u in self.db["users"] if u["id"] == usuario_id), None)
        return self._usuario(usuario) if usuario else None

    def crear_usuario(self, email, password_hash, rol, nombre, telefono, perfil):
        if self.usuario_por_email(email):
            raise ErrorApi(409, "Ya existe una cuenta con ese correo")
        usuario = {
            "id": f"u-{uuid.uuid4().hex[:8]}",
            "email": email,
            "role": rol,
            "password_hash": password_hash,
            "name": nombre,
            "phone": telefono,
        }
        self.db["users"].append(usuario)
        if perfil:
            doctor_id = f"d-{uuid.uuid4().hex[:8]}"
            self.db["doctors"].append({"id": doctor_id, "user_id": usuario["id"], **perfil})
            self.db["schedules"][doctor_id] = []
        return self.usuario(usuario["id"])

    def actualizar_perfil(self, usuario_id, doctor_id, nombre, telefono, password_hash, doctor_datos):
        usuario = next((u for u in self.db["users"] if u["id"] == usuario_id), None)
        if not usuario:
            return None
        if nombre is not None:
            usuario["name"] = nombre
        usuario["phone"] = telefono
        if password_hash is not None:
            usuario["password_hash"] = password_hash
        if doctor_id and doctor_datos:
            doctor = next((d for d in self.db["doctors"] if d["id"] == doctor_id), None)
            if doctor:
                doctor.update(doctor_datos)
        return self.usuario(usuario_id)

    def login_bloqueado(self, clave, ahora_utc):
        registro = self.db["login_attempts"].get(clave)
        if not registro:
            return False
        bloqueado_hasta = registro.get("bloqueado_hasta")
        return bool(bloqueado_hasta and bloqueado_hasta > ahora_utc)

    def registrar_fallo_login(self, clave, ahora_utc, max_intentos, ventana_seg, bloqueo_seg):
        registro = self.db["login_attempts"].get(clave)
        if not registro or (ahora_utc - registro["ventana_inicio"]).total_seconds() > ventana_seg:
            registro = {"intentos": 1, "ventana_inicio": ahora_utc, "bloqueado_hasta": None}
        else:
            registro["intentos"] += 1
        if registro["intentos"] >= max_intentos:
            registro["bloqueado_hasta"] = ahora_utc + timedelta(seconds=bloqueo_seg)
        self.db["login_attempts"][clave] = registro

    def limpiar_fallos_login(self, clave):
        self.db["login_attempts"].pop(clave, None)

    def obtener_idempotencia(self, usuario_id, ruta, clave):
        return self.db["idempotency"].get(f"{usuario_id}|{clave}")

    def guardar_idempotencia(self, usuario_id, ruta, clave, request_hash, status_code, respuesta_json):
        self.db["idempotency"][f"{usuario_id}|{clave}"] = {
            "route": ruta,
            "requestHash": request_hash,
            "statusCode": status_code,
            "responseJson": respuesta_json,
        }

    # -- doctores -----------------------------------------------------------
    def _doctor(self, doctor):
        usuario = next((u for u in self.db["users"] if u["id"] == doctor["user_id"]), {})
        return {
            "id": doctor["id"],
            "userId": doctor["user_id"],
            "name": doctor["name"],
            "specialty": doctor["specialty"],
            "location": doctor["location"],
            "city": doctor.get("city"),
            "description": doctor.get("description"),
            "biografia": doctor.get("description"),
            "price": float(doctor["price"]),
            "durationMin": doctor.get("durationMin", 30),
            "type": usuario.get("role", "DOCTOR"),
        }

    def doctor(self, doctor_id):
        doctor = next((d for d in self.db["doctors"] if d["id"] == doctor_id), None)
        return self._doctor(doctor) if doctor else None

    def user_id_de_doctor(self, doctor_id):
        doctor = next((d for d in self.db["doctors"] if d["id"] == doctor_id), None)
        return doctor["user_id"] if doctor else None

    def doctor_id_de_usuario(self, usuario_id):
        doctor = next((d for d in self.db["doctors"] if d["user_id"] == usuario_id), None)
        return doctor["id"] if doctor else None

    def buscar_doctores(self, especialidad, ubicacion, texto, referencia):
        def contiene(valor, buscado):
            return not buscado or buscado.lower() in (valor or "").lower()

        resultado = []
        for doctor in self.db["doctors"]:
            publico = self._doctor(doctor)
            if not reglas.suscripcion_vigente(
                reglas.resumen_suscripcion(self.suscripciones(doctor["id"]), referencia),
                referencia,
            ):
                continue
            if not contiene(publico["specialty"], especialidad):
                continue
            if ubicacion and not (contiene(publico["location"], ubicacion) or contiene(publico["city"], ubicacion)):
                continue
            if texto and not any(
                contiene(publico[c], texto)
                for c in ("name", "specialty", "description", "location", "city")
            ):
                continue
            resultado.append(publico)
        return sorted(resultado, key=lambda d: d["name"])

    def horario(self, doctor_id):
        bloques = self.db["schedules"].get(doctor_id, [])
        return [dict(b) for b in sorted(bloques, key=lambda b: (b["dia_semana"], b["hora_inicio"]))]

    def horarios_lote(self, doctor_ids):
        return {doc_id: self.horario(doc_id) for doc_id in doctor_ids}

    def promociones(self, doctor_id, referencia=None, solo_activas=False):
        referencia = referencia or reglas.hoy()
        return [
            dict(p)
            for p in self.db["promotions"]
            if p["doctorId"] == doctor_id
            and (not solo_activas or p["active"] and p["start"] <= referencia <= p["end"])
        ]

    def promociones_lote(self, doctor_ids, referencia):
        return {doc_id: self.promociones(doc_id, referencia, solo_activas=True) for doc_id in doctor_ids}

    def inventario(self, doctor_id):
        return [dict(item) for item in self.db["inventory"] if item["doctorId"] == doctor_id]

    def guardar_insumo(self, doctor_id, item):
        existente = next(
            (i for i in self.db["inventory"] if i["doctorId"] == doctor_id and i["name"].casefold() == item["name"].casefold()),
            None,
        )
        if existente:
            existente.update(item)
            return dict(existente)
        resultado = {"id": f"inv-{uuid.uuid4().hex[:8]}", "doctorId": doctor_id, **item}
        self.db["inventory"].append(resultado)
        return dict(resultado)

    def eliminar_insumo(self, doctor_id, item_id):
        antes = len(self.db["inventory"])
        self.db["inventory"] = [
            i for i in self.db["inventory"]
            if not (i["doctorId"] == doctor_id and i["id"] == item_id)
        ]
        return len(self.db["inventory"]) < antes

    def guardar_promocion(self, doctor_id, promo):
        resultado = {"id": f"promo-{uuid.uuid4().hex[:8]}", "doctorId": doctor_id, **promo, "active": True}
        self.db["promotions"].append(resultado)
        return dict(resultado)

    def eliminar_promocion(self, doctor_id, promo_id):
        antes = len(self.db["promotions"])
        self.db["promotions"] = [
            p for p in self.db["promotions"]
            if not (p["doctorId"] == doctor_id and p["id"] == promo_id)
        ]
        return len(self.db["promotions"]) < antes

    def notificar(self, user_id, kind, title, message, reference=None):
        notification = {
            "id": f"n-{uuid.uuid4().hex[:8]}",
            "type": kind,
            "title": title,
            "message": message,
            "reference": reference,
            "createdAt": reglas.ahora().isoformat(),
            "read": False,
        }
        self.db["notifications"].append({"userId": user_id, **notification})
        return notification

    def notificaciones(self, user_id):
        return [dict(n) for n in reversed(self.db["notifications"]) if n["userId"] == user_id]

    def marcar_notificacion(self, user_id, notification_id):
        item = next(
            (n for n in self.db["notifications"] if n["userId"] == user_id and n["id"] == notification_id),
            None,
        )
        if item:
            item["read"] = True
        return dict(item) if item else None

    def puede_mensajear(self, user_a, user_b):
        profile = next((d for d in self.db["doctors"] if d["user_id"] in (user_a, user_b)), None)
        patient_id = user_b if profile and profile["user_id"] == user_a else user_a
        doctor_user_id = profile["user_id"] if profile else None
        if not profile or patient_id == doctor_user_id:
            return False
        consent = any(
            c["patientId"] == patient_id and c["doctorId"] == profile["id"] and c["granted"]
            for c in self.db["consents"]
        )
        appointment = any(
            c["patientId"] == patient_id and c["doctorId"] == profile["id"]
            for c in self.db["appointments"]
        )
        return consent or appointment

    def mensajes(self, user_id, other_id):
        result = []
        for message in self.db["messages"]:
            if {message["senderId"], message["recipientId"]} == {user_id, other_id}:
                message["read"] = message["recipientId"] == user_id and bool(message.get("readAt"))
                result.append(dict(message))
        result.sort(key=lambda item: item["createdAt"])
        for message in result:
            if message["recipientId"] == user_id:
                stored = next(m for m in self.db["messages"] if m["id"] == message["id"])
                stored["readAt"] = reglas.ahora().isoformat()
                message["read"] = True
        return result

    def conversaciones(self, user_id):
        others = {
            m["recipientId"] if m["senderId"] == user_id else m["senderId"]
            for m in self.db["messages"]
            if user_id in (m["senderId"], m["recipientId"])
        }
        result = []
        for other_id in others:
            usuario = self.usuario(other_id) or {}
            mensajes = [
                m for m in self.db["messages"]
                if {m["senderId"], m["recipientId"]} == {user_id, other_id}
            ]
            ultimo = max(mensajes, key=lambda item: item["createdAt"])
            result.append({
                "userId": other_id,
                "name": usuario.get("name") or usuario.get("email"),
                "lastMessage": ultimo["content"],
                "updatedAt": ultimo["createdAt"],
                "unread": sum(1 for m in mensajes if m["recipientId"] == user_id and not m.get("readAt")),
            })
        return sorted(result, key=lambda item: item["updatedAt"], reverse=True)

    def enviar_mensaje(self, sender_id, recipient_id, content):
        message = {
            "id": f"msg-{uuid.uuid4().hex[:8]}",
            "senderId": sender_id,
            "recipientId": recipient_id,
            "content": content,
            "createdAt": reglas.ahora().isoformat(),
            "read": False,
        }
        self.db["messages"].append(message)
        return dict(message)

    def reemplazar_horario(self, doctor_id, bloques):
        self.db["schedules"][doctor_id] = [dict(b) for b in bloques]

    def ocupados(self, doctor_id, dia, excluir_id=None):
        return [
            self._fecha(c["dateTime"])
            for c in self.db["appointments"]
            if c["doctorId"] == doctor_id
            and c["id"] != excluir_id
            and c["status"] != "CANCELADA"
            and self._fecha(c["dateTime"]).date() == dia
        ]

    def ocupados_rango_lote(self, doctor_ids, inicio, fin):
        resultado = {doc_id: [] for doc_id in doctor_ids}
        doc_set = set(doctor_ids)
        for c in self.db["appointments"]:
            if c["doctorId"] in doc_set and c["status"] != "CANCELADA":
                dt = self._fecha(c["dateTime"])
                if inicio <= dt < fin:
                    resultado[c["doctorId"]].append(dt)
        return resultado

    # -- citas --------------------------------------------------------------
    @staticmethod
    def _fecha(valor):
        return reglas.fecha_hora(valor, "dateTime")

    def _cita(self, cita):
        doctor = next((d for d in self.db["doctors"] if d["id"] == cita["doctorId"]), {})
        paciente = next((u for u in self.db["users"] if u["id"] == cita["patientId"]), {})
        receta = next((r for r in self.db["prescriptions"] if r.get("appointmentId") == cita["id"]), None)
        return {
            **cita,
            "dateTime": self._fecha(cita["dateTime"]).isoformat(),
            "reason": cita.get("reason"),
            "patientName": paciente.get("name"),
            "doctorName": doctor.get("name"),
            "specialty": doctor.get("specialty"),
            "location": doctor.get("location"),
            "prescriptionId": receta["id"] if receta else None,
        }

    def crear_cita(self, paciente_id, doctor_id, fecha_hora, motivo):
        if fecha_hora in self.ocupados(doctor_id, fecha_hora.date()):
            raise ErrorApi(409, "Ese horario acaba de ser ocupado, elige otro")
        cita = {
            "id": f"a-{len(self.db['appointments']) + 1}",
            "patientId": paciente_id,
            "doctorId": doctor_id,
            "dateTime": fecha_hora.isoformat(),
            "status": "PENDIENTE",
            "reason": motivo,
        }
        self.db["appointments"].append(cita)
        return self._cita(cita)

    def cita(self, cita_id):
        cita = next((c for c in self.db["appointments"] if c["id"] == cita_id), None)
        return self._cita(cita) if cita else None

    def citas_de(self, usuario_id, doctor_id):
        citas = [
            self._cita(c)
            for c in self.db["appointments"]
            if c["patientId"] == usuario_id or (doctor_id and c["doctorId"] == doctor_id)
        ]
        return sorted(citas, key=lambda c: c["dateTime"])

    def cambiar_estado_cita(self, cita_id, estado_actual, estado_nuevo):
        cita = next((c for c in self.db["appointments"] if c["id"] == cita_id), None)
        if not cita or cita["status"] != estado_actual:
            return False
        cita["status"] = estado_nuevo
        return True

    def reprogramar_cita(self, cita_id, fecha_hora):
        cita = next((c for c in self.db["appointments"] if c["id"] == cita_id), None)
        if not cita:
            return False
        cita["dateTime"] = fecha_hora.isoformat()
        return True

    def receta(self, receta_id):
        receta = next((r for r in self.db["prescriptions"] if r["id"] == receta_id), None)
        if not receta:
            return None
        cita = self.cita(receta["appointmentId"]) or {}
        doctor = self.doctor(receta["doctorId"]) or {}
        paciente = self.usuario(receta["patientId"]) or {}
        return {
            **receta,
            "dateTime": cita.get("dateTime"),
            "doctorName": doctor.get("name"),
            "specialty": doctor.get("specialty"),
            "patientName": paciente.get("name"),
            "documentKey": receta.get("documentKey"),
        }

    # -- expediente ---------------------------------------------------------
    def expediente(self, paciente_id):
        registro = next((r for r in self.db["records"] if r["patient_id"] == paciente_id), None)
        if registro is None:
            return None
        return {
            "patient_id": paciente_id,
            "allergies": registro.get("allergies", []),
            "notes": registro.get("notes", ""),
            "birthDate": registro.get("birthDate"),
            "sex": registro.get("sex"),
            "bloodType": registro.get("bloodType"),
            "chronicConditions": registro.get("chronicConditions", []),
            "medications": registro.get("medications", []),
            "updatedAt": registro.get("updatedAt"),
        }

    def guardar_expediente(self, paciente_id, campos):
        self.db["records"] = [r for r in self.db["records"] if r["patient_id"] != paciente_id]
        self.db["records"].append({"patient_id": paciente_id, **campos, "updatedAt": reglas.ahora()})

    def registrar_acceso(self, paciente_id, actor_id):
        self.db["access_log"].append({"patientId": paciente_id, "actorId": actor_id, "at": reglas.ahora()})

    def accesos_expediente(self, paciente_id):
        resultado = []
        for idx, item in enumerate(reversed(self.db["access_log"])):
            if item["patientId"] != paciente_id:
                continue
            actor = self.usuario(item["actorId"]) or {}
            doctor = self.doctor(actor["doctorId"]) if actor.get("doctorId") else None
            resultado.append({
                "id": f"acc-{idx + 1}",
                "actorId": item["actorId"],
                "actorName": (doctor or {}).get("name") or actor.get("name") or actor.get("email") or "Profesional",
                "actorRole": actor.get("role", "DOCTOR"),
                "specialty": (doctor or {}).get("specialty"),
                "event": "LECTURA_EXPEDIENTE",
                "accessedAt": item["at"],
            })
        return sorted(resultado, key=lambda x: x["accessedAt"], reverse=True)

    def historial(self, paciente_id):
        historial = []
        for receta in self.db["prescriptions"]:
            if receta.get("patientId") != paciente_id:
                continue
            cita = self.cita(receta["appointmentId"]) or {}
            historial.append({
                "prescriptionId": receta["id"],
                "appointmentId": receta["appointmentId"],
                "dateTime": cita.get("dateTime"),
                "doctorId": receta["doctorId"],
                "doctorName": cita.get("doctorName"),
                "specialty": cita.get("specialty"),
                "diagnosis": receta["diagnosis"],
                "treatment": receta["treatment"],
                "notes": receta.get("notes"),
                "createdAt": receta.get("createdAt"),
            })
        return sorted(historial, key=lambda h: h["dateTime"] or "", reverse=True)

    # -- consentimientos ----------------------------------------------------
    def consentimientos(self, paciente_id):
        resultado = []
        for consentimiento in self.db["consents"]:
            if consentimiento["patientId"] == paciente_id:
                doctor = self.doctor(consentimiento["doctorId"]) or {}
                resultado.append({
                    "doctorId": consentimiento["doctorId"],
                    "doctorName": doctor.get("name"),
                    "specialty": doctor.get("specialty"),
                    "granted": consentimiento["granted"],
                    "updatedAt": consentimiento["updatedAt"],
                })
        return resultado

    def guardar_consentimiento(self, paciente_id, doctor_id, granted):
        consent = {
            "patientId": paciente_id,
            "doctorId": doctor_id,
            "granted": granted,
            "updatedAt": reglas.ahora(),
        }
        self.db["consents"] = [
            c for c in self.db["consents"]
            if not (c["patientId"] == paciente_id and c["doctorId"] == doctor_id)
        ]
        self.db["consents"].append(consent)
        return dict(consent)

    def tiene_consentimiento(self, paciente_id, doctor_id):
        return any(
            c["patientId"] == paciente_id and c["doctorId"] == doctor_id and c["granted"]
            for c in self.db["consents"]
        )

    def pacientes_de(self, doctor_id):
        resultado = []
        for consentimiento in self.db["consents"]:
            if consentimiento["doctorId"] == doctor_id and consentimiento["granted"]:
                paciente = self.usuario(consentimiento["patientId"]) or {}
                resultado.append({
                    "patientId": consentimiento["patientId"],
                    "name": paciente.get("name"),
                    "email": paciente.get("email"),
                    "accessSince": consentimiento["updatedAt"],
                })
        return resultado

    # -- suscripciones ------------------------------------------------------
    def _formato_suscripcion(self, s):
        return {
            "id": s.get("id"),
            "doctorId": s["doctor_id"],
            "status": s["status"],
            "amount": float(s["amount"]),
            "start": s.get("start"),
            "end": s.get("end"),
            "cardBrand": s.get("cardBrand"),
            "cardLast4": s.get("cardLast4"),
            "paymentRef": s.get("paymentRef"),
            "stripeSessionId": s.get("stripeSessionId"),
            "stripePaymentIntentId": s.get("stripePaymentIntentId"),
            "paymentMode": s.get("paymentMode") or "test",
            "paidAt": s.get("paidAt"),
        }

    def suscripciones(self, doctor_id):
        items = [self._formato_suscripcion(s) for s in self.db["subscriptions"] if s["doctor_id"] == doctor_id]
        return list(reversed(items))

    def suscripcion_por_sesion(self, session_id):
        item = next((s for s in self.db["subscriptions"] if s.get("stripeSessionId") == session_id), None)
        return self._formato_suscripcion(item) if item else None

    def registrar_checkout_pendiente(self, doctor_id, monto, session_id, modo_pago, fecha_ref):
        existente = next((s for s in self.db["subscriptions"] if s.get("stripeSessionId") == session_id), None)
        if existente:
            return self._formato_suscripcion(existente)
        nuevo = {
            "id": f"sub-{uuid.uuid4().hex[:8]}",
            "doctor_id": doctor_id,
            "status": "PENDIENTE",
            "amount": float(monto),
            "start": fecha_ref,
            "end": fecha_ref,
            "paymentRef": session_id,
            "stripeSessionId": session_id,
            "stripePaymentIntentId": None,
            "cardBrand": None,
            "cardLast4": None,
            "paymentMode": modo_pago,
            "paidAt": None,
        }
        self.db["subscriptions"].append(nuevo)
        return self._formato_suscripcion(nuevo)

    def activar_suscripcion_stripe(
        self,
        doctor_id,
        session_id,
        payment_intent_id,
        monto,
        marca,
        ultimos4,
        modo_pago,
    ):
        existente = next((s for s in self.db["subscriptions"] if s.get("stripeSessionId") == session_id), None)
        if existente:
            if existente["doctor_id"] != doctor_id:
                raise ErrorApi(403, "La sesión de pago no corresponde a este profesional")
            if existente["status"] == "ACTIVA":
                return self._formato_suscripcion(existente), False
        inicio, fin = reglas.periodo_nueva_suscripcion(
            reglas.resumen_suscripcion(self.suscripciones(doctor_id), reglas.hoy()),
            reglas.hoy(),
        )
        ahora_pago = reglas.ahora()
        if existente:
            existente.update({
                "status": "ACTIVA",
                "amount": float(monto),
                "start": inicio,
                "end": fin,
                "paymentRef": session_id,
                "stripePaymentIntentId": payment_intent_id,
                "cardBrand": marca,
                "cardLast4": ultimos4,
                "paymentMode": modo_pago,
                "paidAt": ahora_pago,
            })
            return self._formato_suscripcion(existente), True
        nuevo = {
            "id": f"sub-{uuid.uuid4().hex[:8]}",
            "doctor_id": doctor_id,
            "status": "ACTIVA",
            "amount": float(monto),
            "start": inicio,
            "end": fin,
            "paymentRef": session_id,
            "stripeSessionId": session_id,
            "stripePaymentIntentId": payment_intent_id,
            "cardBrand": marca,
            "cardLast4": ultimos4,
            "paymentMode": modo_pago,
            "paidAt": ahora_pago,
        }
        self.db["subscriptions"].append(nuevo)
        return self._formato_suscripcion(nuevo), True

    def marcar_checkout_expirado(self, session_id):
        for s in self.db["subscriptions"]:
            if s.get("stripeSessionId") == session_id and s.get("status") == "PENDIENTE":
                s["status"] = "INACTIVA"

    # -- consultas y recetas ------------------------------------------------
    def registrar_consulta(self, cita_id, paciente_id, doctor_id, diagnostico, tratamiento, notas, receta_id):
        cita = next(c for c in self.db["appointments"] if c["id"] == cita_id)
        if cita["status"] not in reglas.ESTADOS_CITA_ACTIVA:
            return None
        cita["status"] = "COMPLETADA"
        consulta_id = f"c-{uuid.uuid4().hex[:8]}"
        self.db["prescriptions"].append({
            "id": receta_id,
            "consultationId": consulta_id,
            "appointmentId": cita_id,
            "patientId": paciente_id,
            "doctorId": doctor_id,
            "diagnosis": diagnostico,
            "treatment": tratamiento,
            "notes": notas,
            "documentKey": None,
            "createdAt": reglas.ahora(),
        })
        return consulta_id

    def actualizar_documento_receta(self, receta_id, document_key):
        receta = next((r for r in self.db["prescriptions"] if r["id"] == receta_id), None)
        if receta:
            receta["documentKey"] = document_key


# ===========================================================================
# Repositorio PostgreSQL (AWS)
# ===========================================================================

_SELECT_DOCTOR = (
    "SELECT pd.id::text, pd.usuario_id::text, pd.nombre_completo, pd.especialidad, pd.ubicacion, pd.ciudad, "
    "COALESCE(pd.biografia, pd.descripcion), pd.precio_consulta, pd.duracion_cita_min, u.rol "
    "FROM perfil_doctor pd JOIN usuario u ON u.id = pd.usuario_id "
)
# Solo aparecen y reciben citas los doctores con la suscripción al corriente.
_SUSCRIPCION_VIGENTE = (
    "EXISTS (SELECT 1 FROM suscripcion s WHERE s.doctor_id = pd.id AND s.estado = 'ACTIVA' "
    "AND %s BETWEEN s.fecha_inicio AND s.fecha_fin)"
)
_SELECT_CITA = (
    "SELECT c.id::text, c.paciente_id::text, c.doctor_id::text, c.fecha_hora, c.estado, c.motivo, "
    "u.nombre, pd.nombre_completo, pd.especialidad, pd.ubicacion, r.id::text "
    "FROM cita c JOIN usuario u ON u.id = c.paciente_id JOIN perfil_doctor pd ON pd.id = c.doctor_id "
    "LEFT JOIN receta r ON r.cita_id = c.id "
)


def _like(texto):
    escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado.lower()}%"


class RepoPostgres:
    usa_uuid = True

    def __init__(self, app):
        self.app = app
        self.conexion = None

    @contextmanager
    def atomic(self, actor_id):
        conexion = self.app._database_connection()
        self.conexion = conexion
        try:
            with conexion.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (actor_id,))
            yield
            conexion.commit()
        except Exception:
            conexion.rollback()
            raise
        finally:
            self.conexion = None
            conexion.close()

    def q(self, sql, params=(), fetch=True):
        if self.conexion is None:
            return self.app._query(sql, params, fetch=fetch)
        with self.conexion.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if fetch and cursor.description else None

    def _uno(self, sql, params=()):
        filas = self.q(sql, params)
        return filas[0] if filas else None

    def _transaccion(self, funcion):
        """Ejecuta funcion(cursor) en una sola transacción; si regresa None hace rollback."""
        if self.conexion is not None:
            with self.conexion.cursor() as cursor:
                return funcion(cursor)
        conexion = self.app._database_connection()
        try:
            with conexion.cursor() as cursor:
                resultado = funcion(cursor)
            if resultado is None:
                conexion.rollback()
            else:
                conexion.commit()
            return resultado
        except Exception:
            conexion.rollback()
            raise
        finally:
            conexion.close()

    # -- usuarios y seguridad -----------------------------------------------
    _SELECT_USUARIO = (
        "SELECT u.id::text, u.email, u.rol, u.nombre, u.telefono, pd.id::text, u.password_hash "
        "FROM usuario u LEFT JOIN perfil_doctor pd ON pd.usuario_id = u.id "
    )

    @staticmethod
    def _usuario(fila):
        return {
            "id": fila[0],
            "email": fila[1],
            "role": fila[2],
            "name": fila[3],
            "phone": fila[4],
            "doctorId": fila[5],
            "password_hash": fila[6],
        }

    def usuario_por_email(self, email):
        fila = self._uno(self._SELECT_USUARIO + "WHERE u.email = %s", (email,))
        return self._usuario(fila) if fila else None

    def usuario(self, usuario_id):
        fila = self._uno(self._SELECT_USUARIO + "WHERE u.id = %s", (usuario_id,))
        return self._usuario(fila) if fila else None

    def crear_usuario(self, email, password_hash, rol, nombre, telefono, perfil):
        def crear(cursor):
            cursor.execute(
                "INSERT INTO usuario (email, password_hash, rol, nombre, telefono) VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id::text",
                (email, password_hash, rol, nombre, telefono),
            )
            usuario_id = cursor.fetchone()[0]
            if perfil:
                cursor.execute(
                    "INSERT INTO perfil_doctor (usuario_id, nombre_completo, especialidad, ubicacion, ciudad, "
                    "descripcion, biografia, precio_consulta, duracion_cita_min) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        usuario_id,
                        perfil["name"],
                        perfil["specialty"],
                        perfil["location"],
                        perfil["city"],
                        perfil["description"],
                        perfil["description"],
                        perfil["price"],
                        perfil["durationMin"],
                    ),
                )
            return usuario_id

        return self.usuario(self._transaccion(crear))

    def actualizar_perfil(self, usuario_id, doctor_id, nombre, telefono, password_hash, doctor_datos):
        if password_hash is not None:
            self.q(
                "UPDATE usuario SET nombre = COALESCE(%s, nombre), telefono = %s, password_hash = %s WHERE id = %s",
                (nombre, telefono, password_hash, usuario_id),
                fetch=False,
            )
        else:
            self.q(
                "UPDATE usuario SET nombre = COALESCE(%s, nombre), telefono = %s WHERE id = %s",
                (nombre, telefono, usuario_id),
                fetch=False,
            )
        if doctor_id and doctor_datos:
            self.q(
                "UPDATE perfil_doctor SET nombre_completo = %s, especialidad = %s, ubicacion = %s, "
                "ciudad = %s, descripcion = %s, biografia = %s, precio_consulta = %s, duracion_cita_min = %s "
                "WHERE id = %s",
                (
                    doctor_datos["name"],
                    doctor_datos["specialty"],
                    doctor_datos["location"],
                    doctor_datos["city"],
                    doctor_datos["description"],
                    doctor_datos["description"],
                    doctor_datos["price"],
                    doctor_datos["durationMin"],
                    doctor_id,
                ),
                fetch=False,
            )
        return self.usuario(usuario_id)

    def login_bloqueado(self, clave, ahora_utc):
        fila = self._uno(
            "SELECT bloqueado_hasta FROM intento_login WHERE clave = %s",
            (clave,),
        )
        return bool(fila and fila[0] and fila[0] > ahora_utc)

    def registrar_fallo_login(self, clave, ahora_utc, max_intentos, ventana_seg, bloqueo_seg):
        self.q(
            "INSERT INTO intento_login (clave, intentos, ventana_inicio, bloqueado_hasta) "
            "VALUES (%s, 1, %s, CASE WHEN %s <= 1 THEN %s + (%s * INTERVAL '1 second') ELSE NULL END) "
            "ON CONFLICT (clave) DO UPDATE SET "
            "intentos = CASE "
            "  WHEN EXTRACT(EPOCH FROM (EXCLUDED.ventana_inicio - intento_login.ventana_inicio)) > %s THEN 1 "
            "  ELSE intento_login.intentos + 1 "
            "END, "
            "ventana_inicio = CASE "
            "  WHEN EXTRACT(EPOCH FROM (EXCLUDED.ventana_inicio - intento_login.ventana_inicio)) > %s THEN EXCLUDED.ventana_inicio "
            "  ELSE intento_login.ventana_inicio "
            "END, "
            "bloqueado_hasta = CASE "
            "  WHEN (CASE WHEN EXTRACT(EPOCH FROM (EXCLUDED.ventana_inicio - intento_login.ventana_inicio)) > %s THEN 1 ELSE intento_login.intentos + 1 END) >= %s "
            "  THEN EXCLUDED.ventana_inicio + (%s * INTERVAL '1 second') "
            "  ELSE NULL "
            "END",
            (
                clave,
                ahora_utc,
                max_intentos,
                ahora_utc,
                bloqueo_seg,
                ventana_seg,
                ventana_seg,
                ventana_seg,
                max_intentos,
                bloqueo_seg,
            ),
            fetch=False,
        )

    def limpiar_fallos_login(self, clave):
        self.q("DELETE FROM intento_login WHERE clave = %s", (clave,), fetch=False)

    def obtener_idempotencia(self, usuario_id, ruta, clave):
        fila = self._uno(
            "SELECT request_hash, status_code, respuesta_json FROM clave_idempotencia "
            "WHERE usuario_id = %s AND clave = %s",
            (usuario_id, clave),
        )
        if not fila:
            return None
        return {"requestHash": fila[0], "statusCode": int(fila[1]), "responseJson": fila[2]}

    def guardar_idempotencia(self, usuario_id, ruta, clave, request_hash, status_code, respuesta_json):
        self.q(
            "INSERT INTO clave_idempotencia (clave, usuario_id, ruta, request_hash, status_code, respuesta_json) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (usuario_id, clave) DO NOTHING",
            (clave, usuario_id, ruta, request_hash, status_code, respuesta_json),
            fetch=False,
        )

    # -- doctores -----------------------------------------------------------
    @staticmethod
    def _doctor(fila):
        return {
            "id": fila[0],
            "userId": fila[1],
            "name": fila[2],
            "specialty": fila[3],
            "location": fila[4],
            "city": fila[5],
            "description": fila[6],
            "biografia": fila[6],
            "price": float(fila[7]),
            "durationMin": fila[8],
            "type": fila[9],
        }

    def doctor(self, doctor_id):
        fila = self._uno(_SELECT_DOCTOR + "WHERE pd.id = %s", (doctor_id,))
        return self._doctor(fila) if fila else None

    def user_id_de_doctor(self, doctor_id):
        fila = self._uno("SELECT usuario_id::text FROM perfil_doctor WHERE id = %s", (doctor_id,))
        return fila[0] if fila else None

    def doctor_id_de_usuario(self, usuario_id):
        fila = self._uno("SELECT id::text FROM perfil_doctor WHERE usuario_id = %s", (usuario_id,))
        return fila[0] if fila else None

    def buscar_doctores(self, especialidad, ubicacion, texto, referencia):
        condiciones, params = [_SUSCRIPCION_VIGENTE], [referencia]
        if especialidad:
            condiciones.append("lower(pd.especialidad) LIKE %s")
            params.append(_like(especialidad))
        if ubicacion:
            condiciones.append("(lower(pd.ubicacion) LIKE %s OR lower(coalesce(pd.ciudad, '')) LIKE %s)")
            params += [_like(ubicacion), _like(ubicacion)]
        if texto:
            condiciones.append(
                "(lower(pd.nombre_completo) LIKE %s OR lower(pd.especialidad) LIKE %s "
                "OR lower(coalesce(pd.biografia, pd.descripcion, '')) LIKE %s OR lower(pd.ubicacion) LIKE %s "
                "OR lower(coalesce(pd.ciudad, '')) LIKE %s)"
            )
            params += [_like(texto)] * 5
        filas = self.q(
            _SELECT_DOCTOR + "WHERE " + " AND ".join(condiciones) + " ORDER BY pd.nombre_completo",
            tuple(params),
        ) or []
        return [self._doctor(f) for f in filas]

    def horario(self, doctor_id):
        filas = self.q(
            "SELECT dia_semana, hora_inicio, hora_fin FROM disponibilidad WHERE doctor_id = %s "
            "ORDER BY dia_semana, hora_inicio",
            (doctor_id,),
        ) or []
        return [{"dia_semana": f[0], "hora_inicio": f[1], "hora_fin": f[2]} for f in filas]

    def horarios_lote(self, doctor_ids):
        resultado = {doc_id: [] for doc_id in doctor_ids}
        if not doctor_ids:
            return resultado
        filas = self.q(
            "SELECT doctor_id::text, dia_semana, hora_inicio, hora_fin FROM disponibilidad "
            "WHERE doctor_id = ANY(%s::uuid[]) ORDER BY doctor_id, dia_semana, hora_inicio",
            (doctor_ids,),
        ) or []
        for f in filas:
            resultado.setdefault(f[0], []).append({"dia_semana": f[1], "hora_inicio": f[2], "hora_fin": f[3]})
        return resultado

    def promociones(self, doctor_id, referencia=None, solo_activas=False):
        sql = (
            "SELECT id::text, titulo, descripcion, descuento_porcentaje, fecha_inicio, fecha_fin, activa "
            "FROM promocion WHERE doctor_id = %s"
        )
        params = [doctor_id]
        if solo_activas:
            sql += " AND activa AND fecha_inicio <= %s AND fecha_fin >= %s"
            params.extend([referencia or reglas.hoy()] * 2)
        sql += " ORDER BY fecha_inicio DESC"
        return [
            {
                "id": f[0],
                "title": f[1],
                "description": f[2],
                "discountPercent": f[3],
                "start": f[4],
                "end": f[5],
                "active": f[6],
            }
            for f in (self.q(sql, tuple(params)) or [])
        ]

    def promociones_lote(self, doctor_ids, referencia):
        resultado = {doc_id: [] for doc_id in doctor_ids}
        if not doctor_ids:
            return resultado
        filas = self.q(
            "SELECT doctor_id::text, id::text, titulo, descripcion, descuento_porcentaje, fecha_inicio, fecha_fin, activa "
            "FROM promocion WHERE doctor_id = ANY(%s::uuid[]) AND activa AND fecha_inicio <= %s AND fecha_fin >= %s "
            "ORDER BY fecha_inicio DESC",
            (doctor_ids, referencia, referencia),
        ) or []
        for f in filas:
            resultado.setdefault(f[0], []).append({
                "id": f[1],
                "title": f[2],
                "description": f[3],
                "discountPercent": f[4],
                "start": f[5],
                "end": f[6],
                "active": f[7],
            })
        return resultado

    def inventario(self, doctor_id):
        filas = self.q(
            "SELECT id::text, nombre, cantidad, unidad, actualizado_en FROM inventario_insumo "
            "WHERE doctor_id = %s ORDER BY nombre",
            (doctor_id,),
        ) or []
        return [{"id": f[0], "name": f[1], "quantity": float(f[2]), "unit": f[3], "updatedAt": f[4]} for f in filas]

    def guardar_insumo(self, doctor_id, item):
        fila = self._uno(
            "INSERT INTO inventario_insumo (doctor_id, nombre, cantidad, unidad) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (doctor_id, (lower(nombre))) DO UPDATE SET "
            "cantidad = EXCLUDED.cantidad, unidad = EXCLUDED.unidad, actualizado_en = now() "
            "RETURNING id::text, nombre, cantidad, unidad, actualizado_en",
            (doctor_id, item["name"], item["quantity"], item["unit"]),
        )
        return {"id": fila[0], "name": fila[1], "quantity": float(fila[2]), "unit": fila[3], "updatedAt": fila[4]}

    def eliminar_insumo(self, doctor_id, item_id):
        return self._uno(
            "DELETE FROM inventario_insumo WHERE doctor_id = %s AND id = %s RETURNING id",
            (doctor_id, item_id),
        ) is not None

    def guardar_promocion(self, doctor_id, promo):
        fila = self._uno(
            "INSERT INTO promocion (doctor_id, titulo, descripcion, descuento_porcentaje, fecha_inicio, fecha_fin) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id::text, titulo, descripcion, "
            "descuento_porcentaje, fecha_inicio, fecha_fin, activa",
            (doctor_id, promo["title"], promo["description"], promo["discountPercent"], promo["start"], promo["end"]),
        )
        return {
            "id": fila[0],
            "title": fila[1],
            "description": fila[2],
            "discountPercent": fila[3],
            "start": fila[4],
            "end": fila[5],
            "active": fila[6],
        }

    def eliminar_promocion(self, doctor_id, promo_id):
        return self._uno(
            "DELETE FROM promocion WHERE doctor_id = %s AND id = %s RETURNING id",
            (doctor_id, promo_id),
        ) is not None

    def notificar(self, user_id, kind, title, message, reference=None):
        fila = self._uno(
            "INSERT INTO notificacion (usuario_id, tipo, titulo, mensaje, referencia) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING "
            "RETURNING id::text, creada_en, leida_en",
            (user_id, kind, title, message, reference),
        )
        if not fila:
            return None
        return {
            "id": fila[0],
            "type": kind,
            "title": title,
            "message": message,
            "reference": reference,
            "createdAt": fila[1],
            "read": fila[2] is not None,
        }

    def notificaciones(self, user_id):
        filas = self.q(
            "SELECT id::text, tipo, titulo, mensaje, referencia, creada_en, leida_en FROM notificacion "
            "WHERE usuario_id = %s ORDER BY creada_en DESC LIMIT 100",
            (user_id,),
        ) or []
        return [
            {
                "id": f[0],
                "type": f[1],
                "title": f[2],
                "message": f[3],
                "reference": f[4],
                "createdAt": f[5],
                "read": f[6] is not None,
            }
            for f in filas
        ]

    def marcar_notificacion(self, user_id, notification_id):
        fila = self._uno(
            "UPDATE notificacion SET leida_en = COALESCE(leida_en, now()) "
            "WHERE usuario_id = %s AND id = %s RETURNING id::text, tipo, titulo, mensaje, "
            "referencia, creada_en, leida_en",
            (user_id, notification_id),
        )
        if not fila:
            return None
        return {
            "id": fila[0],
            "type": fila[1],
            "title": fila[2],
            "message": fila[3],
            "reference": fila[4],
            "createdAt": fila[5],
            "read": True,
        }

    def puede_mensajear(self, user_a, user_b):
        fila = self._uno(
            "SELECT EXISTS (SELECT 1 FROM perfil_doctor pd WHERE "
            "((pd.usuario_id = %s AND EXISTS (SELECT 1 FROM usuario p WHERE p.id = %s AND p.rol = 'PACIENTE')) "
            "OR (pd.usuario_id = %s AND EXISTS (SELECT 1 FROM usuario p WHERE p.id = %s AND p.rol = 'PACIENTE'))) "
            "AND (EXISTS (SELECT 1 FROM consentimiento_expediente ce WHERE ce.doctor_id = pd.id "
            "AND ce.paciente_id = CASE WHEN pd.usuario_id = %s THEN %s::uuid ELSE %s::uuid END AND ce.estado_acceso) "
            "OR EXISTS (SELECT 1 FROM cita c WHERE c.doctor_id = pd.id "
            "AND c.paciente_id = CASE WHEN pd.usuario_id = %s THEN %s::uuid ELSE %s::uuid END)))",
            (user_a, user_b, user_b, user_a, user_a, user_b, user_a, user_a, user_b, user_a),
        )
        return bool(fila and fila[0])

    def mensajes(self, user_id, other_id):
        self.q(
            "UPDATE mensaje_usuario SET leido_en = COALESCE(leido_en, now()) "
            "WHERE remitente_id = %s AND destinatario_id = %s AND leido_en IS NULL",
            (other_id, user_id),
            fetch=False,
        )
        filas = self.q(
            "SELECT id::text, remitente_id::text, destinatario_id::text, contenido, creado_en, leido_en "
            "FROM mensaje_usuario WHERE (remitente_id = %s AND destinatario_id = %s) "
            "OR (remitente_id = %s AND destinatario_id = %s) ORDER BY creado_en",
            (user_id, other_id, other_id, user_id),
        ) or []
        return [
            {
                "id": f[0],
                "senderId": f[1],
                "recipientId": f[2],
                "content": f[3],
                "createdAt": f[4],
                "read": f[2] == user_id and f[5] is not None,
            }
            for f in filas
        ]

    def conversaciones(self, user_id):
        filas = self.q(
            "SELECT id::text, remitente_id::text, destinatario_id::text, contenido, creado_en "
            "FROM mensaje_usuario WHERE remitente_id = %s OR destinatario_id = %s "
            "ORDER BY creado_en DESC LIMIT 500",
            (user_id, user_id),
        ) or []
        latest = {}
        for fila in filas:
            other_id = fila[2] if fila[1] == user_id else fila[1]
            if other_id not in latest:
                usuario = self.usuario(other_id) or {}
                count = self._uno(
                    "SELECT count(*) FROM mensaje_usuario WHERE remitente_id = %s "
                    "AND destinatario_id = %s AND leido_en IS NULL",
                    (other_id, user_id),
                )
                latest[other_id] = {
                    "userId": other_id,
                    "name": usuario.get("name") or usuario.get("email"),
                    "lastMessage": fila[3],
                    "updatedAt": fila[4],
                    "unread": int(count[0]),
                }
        return list(latest.values())

    def enviar_mensaje(self, sender_id, recipient_id, content):
        fila = self._uno(
            "INSERT INTO mensaje_usuario (remitente_id, destinatario_id, contenido) "
            "VALUES (%s, %s, %s) RETURNING id::text, creado_en",
            (sender_id, recipient_id, content),
        )
        return {
            "id": fila[0],
            "senderId": sender_id,
            "recipientId": recipient_id,
            "content": content,
            "createdAt": fila[1],
            "read": False,
        }

    def reemplazar_horario(self, doctor_id, bloques):
        def reemplazar(cursor):
            cursor.execute("DELETE FROM disponibilidad WHERE doctor_id = %s", (doctor_id,))
            for bloque in bloques:
                cursor.execute(
                    "INSERT INTO disponibilidad (doctor_id, dia_semana, hora_inicio, hora_fin) VALUES (%s, %s, %s, %s)",
                    (doctor_id, bloque["dia_semana"], bloque["hora_inicio"], bloque["hora_fin"]),
                )
            return True

        self._transaccion(reemplazar)

    def ocupados(self, doctor_id, dia, excluir_id=None):
        inicio = datetime.combine(dia, time(0, 0), tzinfo=ZONA)
        filas = self.q(
            "SELECT fecha_hora FROM cita WHERE doctor_id = %s AND estado <> 'CANCELADA' "
            "AND fecha_hora >= %s AND fecha_hora < %s AND (%s IS NULL OR id <> %s)",
            (doctor_id, inicio, inicio + timedelta(days=1), excluir_id, excluir_id),
        ) or []
        return [f[0] for f in filas]

    def ocupados_rango_lote(self, doctor_ids, inicio, fin):
        resultado = {doc_id: [] for doc_id in doctor_ids}
        if not doctor_ids:
            return resultado
        filas = self.q(
            "SELECT doctor_id::text, fecha_hora FROM cita WHERE doctor_id = ANY(%s::uuid[]) "
            "AND estado <> 'CANCELADA' AND fecha_hora >= %s AND fecha_hora < %s",
            (doctor_ids, inicio, fin),
        ) or []
        for f in filas:
            resultado.setdefault(f[0], []).append(f[1])
        return resultado

    # -- citas --------------------------------------------------------------
    @staticmethod
    def _cita(fila):
        return {
            "id": fila[0],
            "patientId": fila[1],
            "doctorId": fila[2],
            "dateTime": fila[3].astimezone(ZONA).isoformat(),
            "status": fila[4],
            "reason": fila[5],
            "patientName": fila[6],
            "doctorName": fila[7],
            "specialty": fila[8],
            "location": fila[9],
            "prescriptionId": fila[10],
        }

    def crear_cita(self, paciente_id, doctor_id, fecha_hora, motivo):
        try:
            fila = self._uno(
                "INSERT INTO cita (paciente_id, doctor_id, fecha_hora, motivo) VALUES (%s, %s, %s, %s) "
                "RETURNING id::text",
                (paciente_id, doctor_id, fecha_hora, motivo),
            )
        except Exception as error:
            # ux_cita_doctor_horario: otra petición ganó el horario al mismo tiempo.
            if getattr(error, "pgcode", None) == "23505":
                raise ErrorApi(409, "Ese horario acaba de ser ocupado, elige otro")
            raise
        return self.cita(fila[0])

    def cita(self, cita_id):
        fila = self._uno(_SELECT_CITA + "WHERE c.id = %s", (cita_id,))
        return self._cita(fila) if fila else None

    def citas_de(self, usuario_id, doctor_id):
        filas = self.q(
            _SELECT_CITA + "WHERE c.paciente_id = %s OR c.doctor_id = %s ORDER BY c.fecha_hora",
            (usuario_id, doctor_id),
        ) or []
        return [self._cita(f) for f in filas]

    # -- expediente ---------------------------------------------------------
    def expediente(self, paciente_id):
        fila = self._uno(
            "SELECT paciente_id::text, alergias, notas, fecha_nacimiento, sexo, tipo_sangre, padecimientos_cronicos, "
            "medicamentos_actuales, fecha_actualizacion FROM expediente WHERE paciente_id = %s",
            (paciente_id,),
        )
        if fila is None:
            return None
        return {
            "patient_id": fila[0],
            "allergies": fila[1] or [],
            "notes": fila[2] or "",
            "birthDate": fila[3],
            "sex": fila[4],
            "bloodType": fila[5],
            "chronicConditions": fila[6] or [],
            "medications": fila[7] or [],
            "updatedAt": fila[8],
        }

    def guardar_expediente(self, paciente_id, campos):
        self.q(
            "INSERT INTO expediente (paciente_id, alergias, notas, fecha_nacimiento, sexo, tipo_sangre, "
            "padecimientos_cronicos, medicamentos_actuales, fecha_actualizacion) "
            "VALUES (%s, %s::text[], %s, %s, %s, %s, %s::text[], %s::text[], now()) "
            "ON CONFLICT (paciente_id) DO UPDATE SET alergias = EXCLUDED.alergias, notas = EXCLUDED.notas, "
            "fecha_nacimiento = EXCLUDED.fecha_nacimiento, sexo = EXCLUDED.sexo, tipo_sangre = EXCLUDED.tipo_sangre, "
            "padecimientos_cronicos = EXCLUDED.padecimientos_cronicos, "
            "medicamentos_actuales = EXCLUDED.medicamentos_actuales, fecha_actualizacion = now()",
            (
                paciente_id,
                campos["allergies"],
                campos["notes"],
                campos["birthDate"],
                campos["sex"],
                campos["bloodType"],
                campos["chronicConditions"],
                campos["medications"],
            ),
            fetch=False,
        )

    def registrar_acceso(self, paciente_id, actor_id):
        self.q(
            "INSERT INTO bitacora_acceso_expediente (paciente_id, actor_id) VALUES (%s, %s)",
            (paciente_id, actor_id),
            fetch=False,
        )
        self.app._audit_record_access(paciente_id, actor_id)

    def accesos_expediente(self, paciente_id):
        filas = self.q(
            "SELECT b.id::text, b.actor_id::text, COALESCE(pd.nombre_completo, u.nombre, u.email), "
            "u.rol, pd.especialidad, b.consultado_en "
            "FROM bitacora_acceso_expediente b "
            "JOIN usuario u ON u.id = b.actor_id "
            "LEFT JOIN perfil_doctor pd ON pd.usuario_id = u.id "
            "WHERE b.paciente_id = %s ORDER BY b.consultado_en DESC LIMIT 100",
            (paciente_id,),
        ) or []
        if filas:
            return [
                {
                    "id": f[0],
                    "actorId": f[1],
                    "actorName": f[2],
                    "actorRole": f[3],
                    "specialty": f[4],
                    "event": "LECTURA_EXPEDIENTE",
                    "accessedAt": f[5],
                }
                for f in filas
            ]
        # Respaldo complementario en DynamoDB si PostgreSQL no devolvió filas; nunca bloquea.
        try:
            items = servicios_aws.listar_accesos(paciente_id)
        except Exception:
            metricas.registrar_metrica("DynamoAuditErrors", 1)
            return []
        resultado = []
        for idx, item in enumerate(items):
            actor_id = item.get("actorId")
            actor = self.usuario(actor_id) if actor_id else None
            doctor = self.doctor(actor["doctorId"]) if actor and actor.get("doctorId") else None
            resultado.append({
                "id": f"ddb-{idx + 1}",
                "actorId": actor_id,
                "actorName": (doctor or {}).get("name") or (actor or {}).get("name") or "Profesional",
                "actorRole": (actor or {}).get("role", "DOCTOR"),
                "specialty": (doctor or {}).get("specialty"),
                "event": item.get("event", "LECTURA_EXPEDIENTE"),
                "accessedAt": item.get("accessedAt"),
            })
        return resultado

    def historial(self, paciente_id):
        filas = self.q(
            "SELECT r.id::text, c.id::text, c.fecha_hora, pd.id::text, pd.nombre_completo, pd.especialidad, "
            "co.diagnostico, co.tratamiento, co.notas, co.creada_en "
            "FROM consulta co JOIN cita c ON c.id = co.cita_id JOIN perfil_doctor pd ON pd.id = co.doctor_id "
            "LEFT JOIN receta r ON r.cita_id = co.cita_id WHERE co.paciente_id = %s ORDER BY c.fecha_hora DESC",
            (paciente_id,),
        ) or []
        return [
            {
                "prescriptionId": f[0],
                "appointmentId": f[1],
                "dateTime": f[2].astimezone(ZONA).isoformat(),
                "doctorId": f[3],
                "doctorName": f[4],
                "specialty": f[5],
                "diagnosis": f[6],
                "treatment": f[7],
                "notes": f[8],
                "createdAt": f[9],
            }
            for f in filas
        ]

    # -- consentimientos ----------------------------------------------------
    def consentimientos(self, paciente_id):
        filas = self.q(
            "SELECT ce.doctor_id::text, pd.nombre_completo, pd.especialidad, ce.estado_acceso, ce.fecha_actualizacion "
            "FROM consentimiento_expediente ce JOIN perfil_doctor pd ON pd.id = ce.doctor_id "
            "WHERE ce.paciente_id = %s ORDER BY ce.fecha_actualizacion DESC",
            (paciente_id,),
        ) or []
        return [
            {"doctorId": f[0], "doctorName": f[1], "specialty": f[2], "granted": f[3], "updatedAt": f[4]}
            for f in filas
        ]

    def guardar_consentimiento(self, paciente_id, doctor_id, granted):
        fila = self._uno(
            "INSERT INTO consentimiento_expediente (paciente_id, doctor_id, estado_acceso) VALUES (%s, %s, %s) "
            "ON CONFLICT (paciente_id, doctor_id) DO UPDATE SET estado_acceso = EXCLUDED.estado_acceso, "
            "fecha_actualizacion = now() RETURNING estado_acceso, fecha_actualizacion",
            (paciente_id, doctor_id, granted),
        )
        return {
            "patientId": paciente_id,
            "doctorId": doctor_id,
            "granted": fila[0],
            "updatedAt": fila[1],
        }

    def tiene_consentimiento(self, paciente_id, doctor_id):
        fila = self._uno(
            "SELECT estado_acceso FROM consentimiento_expediente "
            "WHERE paciente_id = %s AND doctor_id = %s",
            (paciente_id, doctor_id),
        )
        return bool(fila and fila[0])

    def pacientes_de(self, doctor_id):
        filas = self.q(
            "SELECT u.id::text, u.nombre, u.email, ce.fecha_actualizacion FROM consentimiento_expediente ce "
            "JOIN usuario u ON u.id = ce.paciente_id WHERE ce.doctor_id = %s AND ce.estado_acceso ORDER BY u.nombre",
            (doctor_id,),
        ) or []
        return [{"patientId": f[0], "name": f[1], "email": f[2], "accessSince": f[3]} for f in filas]

    # -- suscripciones ------------------------------------------------------
    _SELECT_SUSCRIPCION = (
        "SELECT id::text, doctor_id::text, estado, monto, fecha_inicio, fecha_fin, "
        "tarjeta_marca, tarjeta_ultimos4, referencia_pago, stripe_session_id, "
        "stripe_payment_intent_id, COALESCE(modo_pago, 'test'), fecha_pago "
        "FROM suscripcion "
    )

    @staticmethod
    def _formato_suscripcion(f):
        return {
            "id": f[0],
            "doctorId": f[1],
            "status": f[2],
            "amount": float(f[3]),
            "start": f[4],
            "end": f[5],
            "cardBrand": f[6],
            "cardLast4": f[7],
            "paymentRef": f[8],
            "stripeSessionId": f[9],
            "stripePaymentIntentId": f[10],
            "paymentMode": f[11],
            "paidAt": f[12],
        }

    def suscripciones(self, doctor_id):
        filas = self.q(
            self._SELECT_SUSCRIPCION + "WHERE doctor_id = %s ORDER BY fecha_pago DESC NULLS LAST, fecha_fin DESC",
            (doctor_id,),
        ) or []
        return [self._formato_suscripcion(f) for f in filas]

    def suscripcion_por_sesion(self, session_id):
        fila = self._uno(self._SELECT_SUSCRIPCION + "WHERE stripe_session_id = %s", (session_id,))
        return self._formato_suscripcion(fila) if fila else None

    def registrar_checkout_pendiente(self, doctor_id, monto, session_id, modo_pago, fecha_ref):
        existente = self.suscripcion_por_sesion(session_id)
        if existente:
            return existente
        fila = self._uno(
            "INSERT INTO suscripcion (doctor_id, estado, monto, fecha_inicio, fecha_fin, "
            "referencia_pago, stripe_session_id, modo_pago) "
            "VALUES (%s, 'PENDIENTE', %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (stripe_session_id) WHERE stripe_session_id IS NOT NULL DO NOTHING "
            "RETURNING id::text",
            (doctor_id, monto, fecha_ref, fecha_ref, session_id, session_id, modo_pago),
        )
        return self.suscripcion_por_sesion(session_id) if fila or True else None

    def activar_suscripcion_stripe(
        self,
        doctor_id,
        session_id,
        payment_intent_id,
        monto,
        marca,
        ultimos4,
        modo_pago,
    ):
        # Serializa /confirm y /webhooks/stripe para que nunca activen 60 días por error.
        self.q("SELECT pg_advisory_xact_lock(hashtext(%s))", (doctor_id,), fetch=False)
        existente = self.suscripcion_por_sesion(session_id)
        if existente:
            if existente["doctorId"] != doctor_id:
                raise ErrorApi(403, "La sesión de pago no corresponde a este profesional")
            if existente["status"] == "ACTIVA":
                return existente, False
        inicio, fin = reglas.periodo_nueva_suscripcion(
            reglas.resumen_suscripcion(self.suscripciones(doctor_id), reglas.hoy()),
            reglas.hoy(),
        )
        if existente:
            self.q(
                "UPDATE suscripcion SET estado = 'ACTIVA', monto = %s, fecha_inicio = %s, fecha_fin = %s, "
                "referencia_pago = %s, stripe_payment_intent_id = %s, tarjeta_marca = %s, tarjeta_ultimos4 = %s, "
                "modo_pago = %s, fecha_pago = now() WHERE stripe_session_id = %s",
                (monto, inicio, fin, session_id, payment_intent_id, marca, ultimos4, modo_pago, session_id),
                fetch=False,
            )
        else:
            self.q(
                "INSERT INTO suscripcion (doctor_id, estado, monto, fecha_inicio, fecha_fin, referencia_pago, "
                "stripe_session_id, stripe_payment_intent_id, tarjeta_marca, tarjeta_ultimos4, modo_pago, fecha_pago) "
                "VALUES (%s, 'ACTIVA', %s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
                (doctor_id, monto, inicio, fin, session_id, session_id, payment_intent_id, marca, ultimos4, modo_pago),
                fetch=False,
            )
        return self.suscripcion_por_sesion(session_id), True

    def marcar_checkout_expirado(self, session_id):
        self.q(
            "UPDATE suscripcion SET estado = 'INACTIVA' WHERE stripe_session_id = %s AND estado = 'PENDIENTE'",
            (session_id,),
            fetch=False,
        )

    # -- consultas y recetas ------------------------------------------------
    def registrar_consulta(self, cita_id, paciente_id, doctor_id, diagnostico, tratamiento, notas, receta_id):
        """Cita COMPLETADA + consulta + receta en una sola transacción."""
        def registrar(cursor):
            cursor.execute(
                "UPDATE cita SET estado = 'COMPLETADA' WHERE id = %s AND estado IN ('PENDIENTE', 'CONFIRMADA') "
                "RETURNING id",
                (cita_id,),
            )
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                "INSERT INTO consulta (cita_id, paciente_id, doctor_id, diagnostico, tratamiento, notas) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id::text",
                (cita_id, paciente_id, doctor_id, diagnostico, tratamiento, notas),
            )
            consulta_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO receta (id, cita_id, consulta_id, diagnostico, tratamiento) "
                "VALUES (%s, %s, %s, %s, %s)",
                (receta_id, cita_id, consulta_id, diagnostico, tratamiento),
            )
            return consulta_id

        return self._transaccion(registrar)

    def actualizar_documento_receta(self, receta_id, document_key):
        self.q(
            "UPDATE receta SET documento_url = %s WHERE id = %s",
            (document_key, receta_id),
            fetch=False,
        )

    def cambiar_estado_cita(self, cita_id, estado_actual, estado_nuevo):
        return self._uno(
            "UPDATE cita SET estado = %s WHERE id = %s AND estado = %s RETURNING id::text",
            (estado_nuevo, cita_id, estado_actual),
        ) is not None

    def reprogramar_cita(self, cita_id, fecha_hora):
        try:
            return self._uno(
                "UPDATE cita SET fecha_hora = %s WHERE id = %s AND estado IN ('PENDIENTE', 'CONFIRMADA') "
                "RETURNING id",
                (fecha_hora, cita_id),
            ) is not None
        except Exception as error:
            if getattr(error, "pgcode", None) == "23505":
                raise ErrorApi(409, "Ese horario acaba de ser ocupado, elige otro") from error
            raise

    def receta(self, receta_id):
        fila = self._uno(
            "SELECT r.id::text, c.paciente_id::text, c.doctor_id::text, r.diagnostico, r.tratamiento, "
            "c.fecha_hora, pd.nombre_completo, pd.especialidad, r.documento_url, r.consulta_id::text, u.nombre "
            "FROM receta r "
            "JOIN cita c ON c.id = r.cita_id "
            "JOIN perfil_doctor pd ON pd.id = c.doctor_id "
            "JOIN usuario u ON u.id = c.paciente_id "
            "WHERE r.id = %s",
            (receta_id,),
        )
        if not fila:
            return None
        return {
            "id": fila[0],
            "patientId": fila[1],
            "doctorId": fila[2],
            "diagnosis": fila[3],
            "treatment": fila[4],
            "dateTime": fila[5],
            "doctorName": fila[6],
            "specialty": fila[7],
            "documentKey": fila[8],
            "consultationId": fila[9],
            "patientName": fila[10],
        }


def semilla_postgres(cursor):
    """Completa los datos de demo de app.py con los campos nuevos (idempotente)."""
    allow = os.environ.get("ALLOW_DEMO_SEED")
    if allow is not None:
        if allow.strip().lower() != "true":
            return
    elif os.environ.get("NODE_ENV") == "production":
        return

    cursor.execute("UPDATE usuario SET nombre = 'Paciente Demo' WHERE email = 'paciente@midoc.local' AND nombre IS NULL")
    cursor.execute("UPDATE usuario SET nombre = 'Dra. Ana López' WHERE email = 'doctor@midoc.local' AND nombre IS NULL")
    cursor.execute(
        "UPDATE perfil_doctor SET ciudad = ubicacion, "
        "descripcion = 'Atención de primer contacto para toda la familia.', "
        "biografia = COALESCE(biografia, 'Atención de primer contacto para toda la familia.') "
        "WHERE id = '10000000-0000-0000-0000-000000000001' AND ciudad IS NULL"
    )
    cursor.execute("SELECT 1 FROM disponibilidad WHERE doctor_id = '10000000-0000-0000-0000-000000000001' LIMIT 1")
    if cursor.fetchone() is None:
        for bloque in HORARIO_DEMO:
            cursor.execute(
                "INSERT INTO disponibilidad (doctor_id, dia_semana, hora_inicio, hora_fin) "
                "VALUES ('10000000-0000-0000-0000-000000000001', %s, %s, %s)",
                (bloque["dia_semana"], bloque["hora_inicio"], bloque["hora_fin"]),
            )


def repositorio(app):
    actual = _repositorio_actual.get()
    if actual is not None:
        return actual
    return RepoPostgres(app) if app._database_ready() else RepoMemoria(app)


# ===========================================================================
# Utilidades de los handlers
# ===========================================================================

def a_json(valor):
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items() if k != "password_hash"}
    if isinstance(valor, (list, tuple)):
        return [a_json(v) for v in valor]
    if isinstance(valor, datetime):
        return (valor.astimezone(ZONA) if valor.tzinfo else valor).isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def _ok(app, datos, status=200):
    return app._response(status, {"data": a_json(datos)})


def _header(headers: dict | None, nombre: str) -> str | None:
    if not headers:
        return None
    objetivo = nombre.lower()
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == objetivo and isinstance(v, str):
            return v
    return None


def _ejecutar_idempotente(app, repo, usuario, method, path, headers, body, fn):
    clave = (_header(headers, "idempotency-key") or "").strip()
    if not clave:
        return fn()
    if len(clave) > 160:
        raise ErrorApi(400, "La cabecera Idempotency-Key admite máximo 160 caracteres")
    ruta = f"{method} {path}"
    request_hash = hashlib.sha256(
        json.dumps({"m": method, "p": path, "b": body or {}}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    previo = repo.obtener_idempotencia(usuario["sub"], ruta, clave)
    if previo:
        if previo["requestHash"] != request_hash:
            raise ErrorApi(409, "La clave de idempotencia ya se usó con una petición distinta")
        return app._response(previo["statusCode"], json.loads(previo["responseJson"]))
    respuesta = fn()
    if 200 <= respuesta["statusCode"] < 300:
        repo.guardar_idempotencia(usuario["sub"], ruta, clave, request_hash, respuesta["statusCode"], respuesta["body"])
    return respuesta


def _requerir_rol(usuario, *roles):
    if usuario["role"] not in roles:
        raise ErrorApi(403, "Tu rol no tiene permiso para esta operación")


def _doctor_de_sesion(repo, usuario):
    _requerir_rol(usuario, *reglas.ROLES_DOCTOR)
    doctor_id = repo.doctor_id_de_usuario(usuario["sub"])
    if doctor_id is None:
        raise ErrorApi(404, "Tu cuenta no tiene perfil de doctor")
    return doctor_id


def _suscripcion(repo, doctor_id):
    return reglas.resumen_suscripcion(repo.suscripciones(doctor_id), reglas.hoy())


def _requerir_suscripcion(repo, doctor_id):
    if not reglas.suscripcion_vigente(_suscripcion(repo, doctor_id), reglas.hoy()):
        raise ErrorApi(402, "Necesitas una suscripción activa ($20 USD/mes) para usar el panel del doctor")


def _doctor_visible(repo, doctor_id):
    doctor = repo.doctor(reglas.identificador(doctor_id, "doctorId", repo.usa_uuid))
    if doctor is None or not reglas.suscripcion_vigente(_suscripcion(repo, doctor["id"]), reglas.hoy()):
        raise ErrorApi(404, "El doctor no existe o no está disponible en MiDoc")
    return doctor


def _horarios_libres(repo, doctor, dia, excluir_id=None):
    return reglas.generar_horarios(
        dia,
        repo.horario(doctor["id"]),
        doctor["durationMin"],
        repo.ocupados(doctor["id"], dia, excluir_id),
        reglas.ahora(),
    )


def _notificar(repo, user_id, tipo, titulo, mensaje, referencia=None):
    if user_id:
        repo.notificar(user_id, tipo, titulo, mensaje, referencia)


def _notificaciones_actualizadas(repo, usuario):
    user_id = usuario["sub"]
    actuales = repo.notificaciones(user_id)
    referencias = {item.get("reference") for item in actuales}
    doctor_id = repo.doctor_id_de_usuario(user_id) if usuario["role"] in reglas.ROLES_DOCTOR else None
    ahora = reglas.ahora()
    for cita in repo.citas_de(user_id, doctor_id):
        fecha = reglas.fecha_hora(cita["dateTime"], "dateTime")
        if cita["status"] not in reglas.ESTADOS_CITA_ACTIVA or not ahora < fecha <= ahora + timedelta(hours=24):
            continue
        referencia = f"recordatorio-cita:{cita['id']}:{fecha.isoformat()}"
        if referencia not in referencias:
            _notificar(
                repo,
                user_id,
                "RECORDATORIO_CITA",
                "Tienes una cita próximamente",
                f"Tienes una cita con {cita['doctorName']} el {fecha.strftime('%d/%m/%Y a las %H:%M')}.",
                referencia,
            )
    if doctor_id:
        suscripcion = _suscripcion(repo, doctor_id)
        if suscripcion and suscripcion["status"] == "ACTIVA":
            dias = (suscripcion["end"] - reglas.hoy()).days
            referencia = f"vencimiento-suscripcion:{suscripcion['end']}"
            if 0 <= dias <= 7 and referencia not in referencias:
                _notificar(
                    repo,
                    user_id,
                    "VENCIMIENTO_SUSCRIPCION",
                    "Tu suscripción está por vencer",
                    f"Tu suscripción termina el {suscripcion['end']}. Renueva para mantener tu perfil visible.",
                    referencia,
                )
    return repo.notificaciones(user_id)


@transaccional
def generar_recordatorios(app):
    """Trabajo periódico invocado por EventBridge, sin sesiones de navegador.

    Sólo considera usuarios con citas próximas o suscripciones por vencer.
    Las referencias únicas de notificacion hacen seguros los reintentos.
    """
    repo = repositorio(app)
    ahora = reglas.ahora()
    if repo.usa_uuid:
        filas = repo.q(
            "SELECT DISTINCT u.id::text, u.rol FROM usuario u WHERE "
            "EXISTS (SELECT 1 FROM cita c JOIN perfil_doctor pd ON pd.id = c.doctor_id "
            "WHERE (c.paciente_id = u.id OR pd.usuario_id = u.id) "
            "AND c.estado IN ('PENDIENTE','CONFIRMADA') AND c.fecha_hora > %s AND c.fecha_hora <= %s) "
            "OR EXISTS (SELECT 1 FROM suscripcion s JOIN perfil_doctor pd ON pd.id = s.doctor_id "
            "WHERE pd.usuario_id = u.id AND s.estado = 'ACTIVA' AND s.fecha_fin BETWEEN %s AND %s)",
            (ahora, ahora + timedelta(hours=24), reglas.hoy(), reglas.hoy() + timedelta(days=7)),
        ) or []
        usuarios = [{"sub": fila[0], "role": fila[1]} for fila in filas]
    else:
        usuarios = [{"sub": u["id"], "role": u["role"]} for u in repo.db["users"]]
    for usuario in usuarios:
        _notificaciones_actualizadas(repo, usuario)
    return {"processedUsers": len(usuarios), "status": "ok"}


def _cita_propia(repo, usuario, cita_id):
    cita = repo.cita(reglas.identificador(cita_id, "appointmentId", repo.usa_uuid))
    doctor_id = repo.doctor_id_de_usuario(usuario["sub"]) if usuario["role"] in reglas.ROLES_DOCTOR else None
    if cita is None or not (cita["patientId"] == usuario["sub"] or (doctor_id and cita["doctorId"] == doctor_id)):
        raise ErrorApi(404, "La cita no existe")
    return cita


def _validar_perfil(datos, actual=None):
    actual = actual or {}
    combinado = {**actual, **{k: v for k, v in datos.items() if v is not None}}
    return {
        "name": reglas.texto(combinado, "name", max_len=150, min_len=2),
        "specialty": reglas.texto(combinado, "specialty", max_len=100),
        "location": reglas.texto(combinado, "location", max_len=255),
        "city": reglas.texto(combinado, "city", requerido=False, max_len=100) or combinado.get("location"),
        "description": reglas.texto(combinado, "description", requerido=False, max_len=2000),
        "price": reglas.decimal(combinado, "price", Decimal("0"), Decimal("100000")),
        "durationMin": reglas.entero(combinado, "durationMin", 10, 240, requerido=False, defecto=30),
    }


def _perfil_completo(repo, user_id):
    perfil = repo.usuario(user_id)
    if perfil is None:
        raise ErrorApi(404, "El usuario ya no existe")
    if perfil["doctorId"]:
        perfil["doctor"] = {**repo.doctor(perfil["doctorId"]), "schedule": repo.horario(perfil["doctorId"])}
        actual = _suscripcion(repo, perfil["doctorId"])
        perfil["subscription"] = (
            {**actual, "active": reglas.suscripcion_vigente(actual, reglas.hoy())} if actual else None
        )
    return perfil


# ===========================================================================
# Autenticación y sesiones
# ===========================================================================

def _extraer_ip_cliente(headers: dict | None, client_ip: str | None = None) -> str:
    if isinstance(client_ip, str) and client_ip.strip():
        return client_ip.strip()
    xff = _header(headers, "x-forwarded-for") or ""
    if xff.strip():
        partes = [p.strip() for p in xff.split(",") if p.strip()]
        if partes:
            return partes[-1]
    return "local"


def iniciar_sesion(app, body, headers=None, client_ip: str | None = None):
    repo = repositorio(app)
    email_raw = body.get("email")
    email = email_raw.strip().lower() if isinstance(email_raw, str) else ""
    password = body.get("password")
    ip_raw = _extraer_ip_cliente(headers, client_ip)
    clave = hashlib.sha256(f"{email}|{ip_raw}".encode("utf-8")).hexdigest()
    ahora_utc = datetime.now(timezone.utc)

    if repo.login_bloqueado(clave, ahora_utc):
        return app._response(429, {"error": "Demasiados intentos fallidos. Intenta nuevamente en unos minutos"})

    usuario = None
    if email and isinstance(password, str) and password.strip():
        encontrado = repo.usuario_por_email(email)
        if encontrado and app.verify_password(password, encontrado["password_hash"]):
            usuario = encontrado

    if not usuario:
        repo.registrar_fallo_login(clave, ahora_utc, MAX_LOGIN_INTENTOS, VENTANA_LOGIN_SEG, BLOQUEO_LOGIN_SEG)
        return app._response(401, {"error": "Credenciales inválidas"})

    repo.limpiar_fallos_login(clave)
    return app._response(
        200,
        {
            "token": app.create_token(usuario),
            "user": {"id": usuario["id"], "email": usuario["email"], "role": usuario["role"]},
        },
    )


def refrescar_sesion(app, usuario):
    repo = repositorio(app)
    perfil = repo.usuario(usuario["sub"])
    if perfil is None:
        raise ErrorApi(404, "El usuario ya no existe")
    token = app.create_token({"id": perfil["id"], "role": perfil["role"]})
    return app._response(200, {"token": token, "user": a_json(perfil)})


# ===========================================================================
# Rutas existentes de app.py ampliadas (mismo contrato, más validaciones)
# ===========================================================================

def _resumen_promocion(doctor, promos):
    if not promos:
        return None
    mejor = max(promos, key=lambda p: p["discountPercent"])
    precio_desc = round(float(doctor["price"]) * (1 - mejor["discountPercent"] / 100), 2)
    return {
        "count": len(promos),
        "maxDiscountPercent": mejor["discountPercent"],
        "title": mejor["title"],
        "discountedPrice": precio_desc,
    }


def _proximo_slot_disponible(doctor, bloques, ocupados, ahora_ref):
    hoy_ref = ahora_ref.date()
    for offset in range(7):
        dia = hoy_ref + timedelta(days=offset)
        ocupados_dia = [o for o in ocupados if o.astimezone(ZONA).date() == dia]
        libres = reglas.generar_horarios(dia, bloques, doctor["durationMin"], ocupados_dia, ahora_ref)
        if libres:
            return libres[0]
    return None


def buscar_doctores(app, query):
    repo = repositorio(app)
    criterio_orden = reglas.opcion(query, "sort", ("NAME", "PRICE_ASC", "PRICE_DESC", "AVAILABILITY"), requerido=False) or "NAME"
    hoy_ref = reglas.hoy()
    ahora_ref = reglas.ahora()
    doctores = repo.buscar_doctores(
        reglas.texto(query, "specialty", requerido=False, max_len=100),
        reglas.texto(query, "location", requerido=False, max_len=100),
        reglas.texto(query, "q", requerido=False, max_len=100),
        hoy_ref,
    )
    if not doctores:
        return _ok(app, [])

    ids = [d["id"] for d in doctores]
    promos_por_doc = repo.promociones_lote(ids, hoy_ref)
    horarios_por_doc = repo.horarios_lote(ids)
    inicio_rango = datetime.combine(hoy_ref, time(0, 0), tzinfo=ZONA)
    ocupados_por_doc = repo.ocupados_rango_lote(ids, inicio_rango, inicio_rango + timedelta(days=7))

    for doctor in doctores:
        promos = promos_por_doc.get(doctor["id"], [])
        doctor["promotions"] = promos
        doctor["promotionSummary"] = _resumen_promocion(doctor, promos)
        slot = _proximo_slot_disponible(
            doctor,
            horarios_por_doc.get(doctor["id"], []),
            ocupados_por_doc.get(doctor["id"], []),
            ahora_ref,
        )
        doctor["nextAvailableSlot"] = slot.isoformat() if slot else None

    if criterio_orden == "PRICE_ASC":
        doctores.sort(key=lambda d: (d["price"], (d["name"] or "").lower()))
    elif criterio_orden == "PRICE_DESC":
        doctores.sort(key=lambda d: (-d["price"], (d["name"] or "").lower()))
    elif criterio_orden == "AVAILABILITY":
        doctores.sort(key=lambda d: (d["nextAvailableSlot"] is None, d["nextAvailableSlot"] or "", (d["name"] or "").lower()))
    else:
        doctores.sort(key=lambda d: ((d["name"] or "").lower(), d["id"]))

    return _ok(app, doctores)


@transaccional
def agendar_cita(app, usuario, body, headers=None):
    repo = repositorio(app)

    def ejecutar():
        doctor = _doctor_visible(repo, body.get("doctorId"))
        fecha_hora = reglas.fecha_hora(body.get("dateTime"), "dateTime")
        motivo = reglas.texto(body, "reason", requerido=False, max_len=500)
        reglas.validar_fecha_agendable(fecha_hora.date(), reglas.hoy())
        if fecha_hora not in _horarios_libres(repo, doctor, fecha_hora.date()):
            raise ErrorApi(409, "Ese horario no está disponible; consulta /api/doctors/{id}/availability")
        cita = repo.crear_cita(usuario["sub"], doctor["id"], fecha_hora, motivo)
        _notificar(
            repo,
            doctor["userId"],
            "CITA_NUEVA",
            "Nueva solicitud de cita",
            f"{cita['patientName']} solicitó una cita para {reglas.fecha_hora(cita['dateTime'], 'dateTime').strftime('%d/%m/%Y %H:%M')}.",
            cita["id"],
        )
        _notificar(
            repo,
            usuario["sub"],
            "CITA_SOLICITADA",
            "Cita solicitada",
            f"Tu cita con {doctor['name']} está pendiente de confirmación.",
            cita["id"],
        )
        return _ok(app, cita, 201)

    return _ejecutar_idempotente(app, repo, usuario, "POST", "/api/appointments", headers, body, ejecutar)


def listar_citas(app, usuario, query):
    repo = repositorio(app)
    doctor_id = repo.doctor_id_de_usuario(usuario["sub"]) if usuario["role"] in reglas.ROLES_DOCTOR else None
    estado = reglas.opcion(query, "status", reglas.ESTADOS_CITA, requerido=False)
    citas = [c for c in repo.citas_de(usuario["sub"], doctor_id) if not estado or c["status"] == estado]
    return _ok(app, citas)


@transaccional
def actualizar_estado_cita(app, usuario, cita_id, body):
    repo = repositorio(app)
    cita = _cita_propia(repo, usuario, cita_id)
    estado_nuevo = reglas.opcion(body, "status", ("CONFIRMADA", "CANCELADA"))
    ahora = reglas.ahora()
    fecha = reglas.fecha_hora(cita["dateTime"], "dateTime")
    if fecha <= ahora:
        raise ErrorApi(409, "La cita ya comenzó y no se puede cambiar")
    if usuario["role"] == "PACIENTE":
        if estado_nuevo != "CANCELADA":
            raise ErrorApi(403, "El paciente puede cancelar, pero no confirmar, una cita")
    else:
        doctor_id = _doctor_de_sesion(repo, usuario)
        if cita["doctorId"] != doctor_id:
            raise ErrorApi(404, "La cita no existe")
        if estado_nuevo == "CONFIRMADA" and cita["status"] != "PENDIENTE":
            raise ErrorApi(409, "Sólo se puede confirmar una cita pendiente")
    if cita["status"] not in reglas.ESTADOS_CITA_ACTIVA:
        raise ErrorApi(409, "La cita ya no está activa")
    if not repo.cambiar_estado_cita(cita["id"], cita["status"], estado_nuevo):
        raise ErrorApi(409, "La cita cambió mientras se actualizaba")
    resultado = (
        repo.cita(cita["id"])
        if repo.usa_uuid
        else next(c for c in repo.citas_de(cita["patientId"], None) if c["id"] == cita["id"])
    )
    receptor = cita["patientId"] if usuario["role"] in reglas.ROLES_DOCTOR else repo.user_id_de_doctor(cita["doctorId"])
    etiqueta = "confirmada" if estado_nuevo == "CONFIRMADA" else "cancelada"
    _notificar(
        repo,
        receptor,
        f"CITA_{estado_nuevo}",
        f"Cita {etiqueta}",
        f"La cita con {cita['doctorName']} del {reglas.fecha_hora(cita['dateTime'], 'dateTime').strftime('%d/%m/%Y %H:%M')} fue {etiqueta}.",
        cita["id"],
    )
    return _ok(app, resultado)


@transaccional
def reprogramar_cita(app, usuario, cita_id, body):
    repo = repositorio(app)
    cita = _cita_propia(repo, usuario, cita_id)
    if cita["status"] not in reglas.ESTADOS_CITA_ACTIVA:
        raise ErrorApi(409, "Sólo puedes reprogramar una cita pendiente o confirmada")
    if reglas.fecha_hora(cita["dateTime"], "dateTime") <= reglas.ahora():
        raise ErrorApi(409, "La cita ya comenzó y no se puede reprogramar")
    fecha_hora = reglas.fecha_hora(body.get("dateTime"), "dateTime")
    reglas.validar_fecha_agendable(fecha_hora.date(), reglas.hoy())
    doctor = repo.doctor(cita["doctorId"])
    if not reglas.suscripcion_vigente(_suscripcion(repo, cita["doctorId"]), reglas.hoy()):
        raise ErrorApi(409, "El profesional ya no tiene una suscripción vigente")
    if fecha_hora not in _horarios_libres(repo, doctor, fecha_hora.date(), excluir_id=cita["id"]):
        raise ErrorApi(409, "Ese horario no está disponible; elige otro")
    anterior = cita["dateTime"]
    if not repo.reprogramar_cita(cita["id"], fecha_hora):
        raise ErrorApi(409, "No se pudo reprogramar la cita; actualiza la agenda")
    resultado = (
        repo.cita(cita["id"])
        if repo.usa_uuid
        else next(c for c in repo.citas_de(cita["patientId"], None) if c["id"] == cita["id"])
    )
    receptor = cita["patientId"] if usuario["role"] in reglas.ROLES_DOCTOR else repo.user_id_de_doctor(cita["doctorId"])
    _notificar(
        repo,
        receptor,
        "CITA_REPROGRAMADA",
        "Cita reprogramada",
        f"La cita con {cita['doctorName']} cambió de {reglas.fecha_hora(anterior, 'dateTime').strftime('%d/%m/%Y %H:%M')} a {fecha_hora.strftime('%d/%m/%Y %H:%M')}.",
        cita["id"],
    )
    return _ok(app, resultado)


def ver_receta(app, usuario, receta_id):
    repo = repositorio(app)
    receta = repo.receta(reglas.identificador(receta_id, "prescriptionId", repo.usa_uuid))
    if receta is None:
        raise ErrorApi(404, "La receta no existe")
    if usuario["role"] == "PACIENTE":
        if receta["patientId"] != usuario["sub"]:
            raise ErrorApi(404, "La receta no existe")
    else:
        doctor_id = _doctor_de_sesion(repo, usuario)
        if receta["doctorId"] != doctor_id:
            raise ErrorApi(404, "La receta no existe")
        _requerir_suscripcion(repo, doctor_id)
        if not repo.tiene_consentimiento(receta["patientId"], doctor_id):
            raise ErrorApi(403, "Se requiere consentimiento vigente")
    doc_key = receta.pop("documentKey", None)
    try:
        download_url = servicios_aws.url_descarga_receta(doc_key, receta["id"]) if doc_key else None
    except Exception as error:
        raise ErrorApi(503, "El almacenamiento seguro no está configurado") from error
    return _ok(app, {**receta, "downloadUrl": download_url, "hasPdf": bool(doc_key)})


def validar_doctor_para_consentimiento(app, doctor_id):
    repo = repositorio(app)
    if repo.doctor(reglas.identificador(doctor_id, "doctorId", repo.usa_uuid)) is None:
        raise ErrorApi(404, "El doctor no existe")


@transaccional
def administrar_consentimiento(app, usuario, body):
    _requerir_rol(usuario, "PACIENTE")
    repo = repositorio(app)
    doctor_id = reglas.identificador(body.get("doctorId"), "doctorId", repo.usa_uuid)
    if not isinstance(body.get("granted"), bool):
        raise ErrorApi(400, "doctorId y granted son requeridos")
    doctor = repo.doctor(doctor_id)
    if doctor is None:
        raise ErrorApi(404, "El doctor no existe")
    consentimiento = repo.guardar_consentimiento(usuario["sub"], doctor_id, body["granted"])
    paciente = repo.usuario(usuario["sub"]) or {}
    tipo = "CONSENTIMIENTO_OTORGADO" if body["granted"] else "CONSENTIMIENTO_REVOCADO"
    titulo = "Consentimiento otorgado" if body["granted"] else "Consentimiento revocado"
    accion = "otorgó" if body["granted"] else "revocó"
    _notificar(
        repo,
        doctor["userId"],
        tipo,
        titulo,
        f"{paciente.get('name') or 'Un paciente'} {accion} el acceso a su expediente clínico.",
        f"consent:{usuario['sub']}:{uuid.uuid4().hex[:8]}",
    )
    return _ok(app, consentimiento)


@transaccional
def ver_expediente(app, usuario, query):
    repo = repositorio(app)
    if usuario["role"] == "PACIENTE":
        paciente_id = usuario["sub"]
    else:
        doctor_id = _doctor_de_sesion(repo, usuario)
        paciente_id = reglas.identificador(query.get("patientId"), "patientId", repo.usa_uuid)
        _requerir_suscripcion(repo, doctor_id)
        if not repo.tiene_consentimiento(paciente_id, doctor_id):
            raise ErrorApi(403, "El paciente no ha otorgado consentimiento")
        repo.registrar_acceso(paciente_id, usuario["sub"])
    return _ok(app, _expediente_completo(repo, paciente_id))


def _expediente_completo(repo, paciente_id):
    paciente = repo.usuario(paciente_id) or {}
    datos = repo.expediente(paciente_id) or {
        "patient_id": paciente_id,
        "allergies": [],
        "notes": "",
        "birthDate": None,
        "sex": None,
        "bloodType": None,
        "chronicConditions": [],
        "medications": [],
        "updatedAt": None,
    }
    return {
        **datos,
        "patient": {"id": paciente_id, "name": paciente.get("name"), "email": paciente.get("email")},
        "consultations": repo.historial(paciente_id),
    }


@transaccional
def registrar_consulta(app, usuario, body, headers=None):
    repo = repositorio(app)

    def ejecutar():
        doctor_id = _doctor_de_sesion(repo, usuario)
        _requerir_suscripcion(repo, doctor_id)
        paciente_id = reglas.identificador(body.get("patientId"), "patientId", repo.usa_uuid)
        cita = repo.cita(reglas.identificador(body.get("appointmentId"), "appointmentId", repo.usa_uuid))
        if cita is None or cita["doctorId"] != doctor_id or cita["patientId"] != paciente_id:
            raise ErrorApi(404, "La cita no existe o no corresponde a ese paciente")
        if not repo.tiene_consentimiento(paciente_id, doctor_id):
            raise ErrorApi(403, "Se requiere consentimiento vigente")
        if cita["status"] not in reglas.ESTADOS_CITA_ACTIVA:
            raise ErrorApi(409, f"No se puede registrar la consulta de una cita {cita['status']}")
        if reglas.fecha_hora(cita["dateTime"], "dateTime") > reglas.ahora():
            raise ErrorApi(409, "No se puede registrar la consulta antes de la hora de la cita")

        diagnostico = reglas.texto(body, "diagnosis", max_len=5000, min_len=3)
        tratamiento = reglas.texto(body, "treatment", max_len=5000, min_len=3)
        notas = reglas.texto(body, "notes", requerido=False, max_len=5000)

        receta_id = str(uuid.uuid4()) if repo.usa_uuid else f"rx-{uuid.uuid4().hex[:8]}"
        consulta_id = repo.registrar_consulta(
            cita["id"],
            paciente_id,
            doctor_id,
            diagnostico,
            tratamiento,
            notas,
            receta_id,
        )
        if consulta_id is None:
            raise ErrorApi(409, "La cita cambió de estado mientras se registraba la consulta")

        doctor = repo.doctor(doctor_id) or {}
        paciente = repo.usuario(paciente_id) or {}
        pdf_bytes = pdf_receta.generar_pdf_receta(
            receta_id=receta_id,
            consulta_id=consulta_id,
            fecha_emision=reglas.ahora().strftime("%d/%m/%Y %H:%M UTC-6"),
            doctor_nombre=doctor.get("name") or usuario.get("name") or "Profesional MiDoc",
            especialidad=doctor.get("specialty") or "",
            paciente_nombre=paciente.get("name") or paciente.get("email") or "Paciente",
            diagnostico=diagnostico,
            tratamiento=tratamiento,
            notas=notas,
            ubicacion=doctor.get("location"),
        )
        try:
            doc_key = servicios_aws.subir_receta_pdf(receta_id, pdf_bytes)
        except Exception as error:
            raise ErrorApi(503, "No se pudo almacenar la receta en S3") from error

        if doc_key:
            repo.actualizar_documento_receta(receta_id, doc_key)
            download_url = servicios_aws.url_descarga_receta(doc_key, receta_id)
        else:
            if not repo.usa_uuid:
                repo.db["prescription_pdfs"][receta_id] = pdf_bytes
            download_url = None

        _notificar(
            repo,
            paciente_id,
            "RECETA_NUEVA",
            "Tu receta está lista",
            f"{doctor.get('name') or usuario.get('name') or 'Tu profesional'} registró la consulta y la receta ya está disponible en tu historial.",
            cita["id"],
        )
        return _ok(
            app,
            {
                "id": consulta_id,
                "appointmentId": cita["id"],
                "diagnosis": diagnostico,
                "treatment": tratamiento,
                "notes": notas,
                "prescriptionId": receta_id,
                "documentKey": doc_key,
                "downloadUrl": download_url,
                "hasPdf": bool(doc_key),
            },
            201,
        )

    return _ejecutar_idempotente(app, repo, usuario, "POST", "/api/consultations", headers, body, ejecutar)


def _resumen_suscripcion_api(doctor_id, actual, default_mode):
    if not actual:
        return None
    return {
        "doctor_id": doctor_id,
        "status": actual["status"],
        "amount": actual["amount"],
        "start": actual["start"],
        "end": actual["end"],
        "cardBrand": actual.get("cardBrand"),
        "cardLast4": actual.get("cardLast4"),
        "paymentRef": actual.get("paymentRef"),
        "stripeSessionId": actual.get("stripeSessionId"),
        "paymentMode": actual.get("paymentMode") or default_mode,
        "paidAt": actual.get("paidAt"),
        "active": reglas.suscripcion_vigente(actual, reglas.hoy()),
    }


def ver_suscripcion(app, usuario):
    _requerir_rol(usuario, *reglas.ROLES_DOCTOR)
    repo = repositorio(app)
    doctor_id = _doctor_de_sesion(repo, usuario)
    periodos = repo.suscripciones(doctor_id)
    actual = reglas.resumen_suscripcion(periodos, reglas.hoy())
    cfg = pagos_stripe.obtener_config()
    historial = [p for p in periodos if p.get("status") != "PENDIENTE"][:20]
    return _ok(
        app,
        {
            "subscription": _resumen_suscripcion_api(doctor_id, actual, cfg["payment_mode"]),
            "paymentMode": cfg["payment_mode"],
            "history": historial,
        },
    )


def webhook_stripe(app, headers, raw_body, body):
    if isinstance(raw_body, bytes):
        raw_bytes = raw_body
    elif isinstance(raw_body, str):
        raw_bytes = raw_body.encode("utf-8")
    else:
        raw_bytes = json.dumps(body or {}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    sig_header = _header(headers, "stripe-signature")
    evento = pagos_stripe.verificar_webhook(raw_bytes, sig_header)
    tipo = evento.get("type")
    obj = (evento.get("data") or {}).get("object") or {}

    cfg = pagos_stripe.obtener_config()
    if "livemode" in obj and bool(obj.get("livemode")) != (cfg["payment_mode"] == "live"):
        raise ErrorApi(400, "El modo del webhook de Stripe no corresponde al configurado")

    session_id = obj.get("id")
    lock_key = f"stripe-webhook:{session_id or 'evt'}"
    repo = repositorio(app)
    with repo.atomic(lock_key):
        if tipo == "checkout.session.completed" and obj.get("payment_status") == "paid":
            doctor_id = (obj.get("metadata") or {}).get("doctorId") or obj.get("client_reference_id")
            if not session_id or not doctor_id:
                return _ok(app, {"received": True, "processed": False, "eventId": evento.get("id")})
            if not repo.doctor(doctor_id):
                return _ok(app, {"received": True, "processed": False, "eventId": evento.get("id")})

            pi_obj = obj.get("payment_intent")
            pi_id = pi_obj.get("id") if isinstance(pi_obj, dict) else (pi_obj if isinstance(pi_obj, str) else None)
            card_brand = None
            card_last4 = None
            mode = "live" if obj.get("livemode") else "test"
            amount_total = obj.get("amount_total")
            try:
                detalle = pagos_stripe.consultar_sesion_checkout(session_id)
                pi_id = detalle.get("paymentIntentId") or pi_id
                card_brand = detalle.get("cardBrand")
                card_last4 = detalle.get("cardLast4")
                mode = detalle.get("paymentMode") or mode
                if detalle.get("amountTotal") is not None:
                    amount_total = detalle["amountTotal"]
            except ErrorApi as exc:
                if exc.status not in (502, 503):
                    raise

            monto = Decimal(str(round((amount_total or 2000) / 100, 2)))
            pago, activada = repo.activar_suscripcion_stripe(
                doctor_id,
                session_id,
                pi_id,
                monto,
                card_brand,
                card_last4,
                mode,
            )
            if activada:
                doc_user_id = repo.user_id_de_doctor(doctor_id)
                _notificar(
                    repo,
                    doc_user_id,
                    "SUSCRIPCION_ACTIVA",
                    "Suscripción activada",
                    f"Tu suscripción está vigente hasta el {pago['end']}.",
                    session_id,
                )
                metricas.registrar_metrica("PaymentSucceeded", 1)
            return _ok(app, {"received": True, "processed": bool(activada), "eventId": evento.get("id")})

        if tipo in ("checkout.session.expired", "payment_intent.payment_failed"):
            obj_id = obj.get("id") or ""
            if isinstance(obj_id, str) and obj_id.startswith("cs_"):
                repo.marcar_checkout_expirado(obj_id)
            metricas.registrar_metrica("PaymentFailed", 1)
            return _ok(app, {"received": True, "processed": False, "eventId": evento.get("id")})

    return _ok(app, {"received": True, "processed": False, "eventId": evento.get("id")})


# ===========================================================================
# Rutas nuevas
# ===========================================================================

def _segmentos(path):
    return [s for s in path.strip("/").split("/") if s]


def atender_publico(app, method, path, query, body):
    """Rutas que no requieren sesión. Regresa None si la ruta no es de este módulo."""
    partes = _segmentos(path)
    repo = repositorio(app)

    if method == "POST" and partes == ["api", "auth", "register"]:
        email = reglas.email(body)
        password = reglas.password(body)
        rol = reglas.opcion(body, "role", reglas.ROLES)
        nombre = reglas.texto(body, "name", max_len=150, min_len=2)
        telefono = reglas.texto(body, "phone", requerido=False, max_len=20)
        perfil = _validar_perfil(body, {"name": nombre}) if rol in reglas.ROLES_DOCTOR else None
        try:
            usuario = repo.crear_usuario(email, app.hash_password(password), rol, nombre, telefono, perfil)
        except Exception as error:
            if getattr(error, "pgcode", None) == "23505":
                raise ErrorApi(409, "Ya existe una cuenta con ese correo")
            raise
        return app._response(201, {"token": app.create_token(usuario), "user": a_json(usuario)})

    if method == "GET" and len(partes) == 3 and partes[:2] == ["api", "doctors"]:
        doctor = _doctor_visible(repo, partes[2])
        promos = repo.promociones(doctor["id"], reglas.hoy(), solo_activas=True)
        return _ok(
            app,
            {
                **doctor,
                "schedule": repo.horario(doctor["id"]),
                "promotions": promos,
                "promotionSummary": _resumen_promocion(doctor, promos),
            },
        )

    if method == "GET" and len(partes) == 4 and partes[:2] == ["api", "doctors"] and partes[3] == "availability":
        doctor = _doctor_visible(repo, partes[2])
        dia = reglas.fecha(query.get("date"), "date")
        reglas.validar_fecha_agendable(dia, reglas.hoy())
        return _ok(
            app,
            {
                "doctorId": doctor["id"],
                "date": dia,
                "durationMin": doctor["durationMin"],
                "slots": _horarios_libres(repo, doctor, dia),
            },
        )
    return None


def _valor_alias(body, *claves):
    for c in claves:
        if c in body:
            return True, body[c]
    return False, None


@transaccional
def atender_autenticado(app, usuario, method, path, query, body, headers=None):
    """Rutas que requieren sesión. Regresa None si la ruta no es de este módulo."""
    partes = _segmentos(path)
    repo = repositorio(app)

    if method == "GET" and partes == ["api", "notifications"]:
        return _ok(app, _notificaciones_actualizadas(repo, usuario))

    if method == "PUT" and len(partes) == 4 and partes[:2] == ["api", "notifications"] and partes[3] == "read":
        notification_id = reglas.identificador(partes[2], "notificationId", repo.usa_uuid)
        notificacion = repo.marcar_notificacion(usuario["sub"], notification_id)
        if not notificacion:
            raise ErrorApi(404, "La notificación no existe")
        return _ok(app, notificacion)

    if method == "GET" and partes == ["api", "messages"]:
        if usuario["role"] in reglas.ROLES_DOCTOR:
            _requerir_suscripcion(repo, _doctor_de_sesion(repo, usuario))
        return _ok(app, repo.conversaciones(usuario["sub"]))

    if method == "GET" and len(partes) == 3 and partes[:2] == ["api", "messages"]:
        if usuario["role"] in reglas.ROLES_DOCTOR:
            _requerir_suscripcion(repo, _doctor_de_sesion(repo, usuario))
        otro_id = reglas.identificador(partes[2], "userId", repo.usa_uuid)
        if not repo.puede_mensajear(usuario["sub"], otro_id):
            raise ErrorApi(404, "La conversación no existe")
        return _ok(app, repo.mensajes(usuario["sub"], otro_id))

    if method == "POST" and partes == ["api", "messages"]:
        def enviar():
            if usuario["role"] in reglas.ROLES_DOCTOR:
                _requerir_suscripcion(repo, _doctor_de_sesion(repo, usuario))
            recipient_id = reglas.identificador(body.get("recipientId"), "recipientId", repo.usa_uuid)
            if not repo.puede_mensajear(usuario["sub"], recipient_id):
                raise ErrorApi(
                    403,
                    "Para iniciar una conversación debe existir un consentimiento o una cita con ese profesional",
                )
            contenido = reglas.texto(body, "content", max_len=2000)
            message = repo.enviar_mensaje(usuario["sub"], recipient_id, contenido)
            _notificar(
                repo,
                recipient_id,
                "MENSAJE_NUEVO",
                "Nuevo mensaje",
                f"Tienes un mensaje nuevo de {usuario.get('name') or usuario.get('email')}.",
                message["id"],
            )
            return _ok(app, message, 201)

        return _ejecutar_idempotente(app, repo, usuario, method, path, headers, body, enviar)

    # --- Perfil de la sesión --------------------------------------------------
    if method == "GET" and partes == ["api", "me"]:
        return _ok(app, _perfil_completo(repo, usuario["sub"]))

    if method == "PUT" and partes == ["api", "me"]:
        perfil_actual = repo.usuario(usuario["sub"])
        if perfil_actual is None:
            raise ErrorApi(404, "El usuario ya no existe")

        tiene_nombre, raw_nombre = _valor_alias(body, "nombreCompleto", "nombre", "name")
        if tiene_nombre:
            nombre = reglas.texto({"name": raw_nombre}, "name", max_len=150, min_len=2)
        else:
            nombre = perfil_actual.get("name")

        tiene_tel, raw_tel = _valor_alias(body, "telefono", "phone")
        if tiene_tel:
            telefono = reglas.texto({"phone": raw_tel}, "phone", requerido=False, max_len=20)
        else:
            telefono = perfil_actual.get("phone")

        new_password_hash = None
        if "currentPassword" in body or "newPassword" in body:
            curr = body.get("currentPassword")
            new_pwd = body.get("newPassword")
            if not isinstance(curr, str) or not curr.strip() or not isinstance(new_pwd, str) or not new_pwd:
                raise ErrorApi(400, "Debes proporcionar currentPassword y newPassword")
            if not app.verify_password(curr, perfil_actual["password_hash"]):
                raise ErrorApi(400, "La contraseña actual es incorrecta")
            reglas.password(body, "newPassword")
            new_password_hash = app.hash_password(new_pwd)

        doctor_datos = None
        if perfil_actual.get("doctorId"):
            doctor_actual = repo.doctor(perfil_actual["doctorId"]) or {}
            mapeo = {}
            if tiene_nombre:
                mapeo["name"] = raw_nombre
            for dst, aliases in (
                ("specialty", ("especialidad", "specialty")),
                ("location", ("ubicacion", "location")),
                ("city", ("ciudad", "city")),
                ("description", ("biografia", "descripcion", "description")),
                ("price", ("precioConsulta", "price")),
                ("durationMin", ("duracionCitaMin", "durationMin")),
            ):
                encontrado, val = _valor_alias(body, *aliases)
                if encontrado:
                    mapeo[dst] = val
            doctor_datos = _validar_perfil(mapeo, actual=doctor_actual)
            if not tiene_nombre:
                nombre = doctor_datos["name"]

        repo.actualizar_perfil(
            usuario["sub"],
            perfil_actual.get("doctorId"),
            nombre,
            telefono,
            new_password_hash,
            doctor_datos,
        )
        return _ok(app, _perfil_completo(repo, usuario["sub"]))

    # --- Flujo 1: agenda --------------------------------------------------------
    if method == "GET" and len(partes) == 3 and partes[:2] == ["api", "appointments"]:
        return _ok(app, _cita_propia(repo, usuario, partes[2]))

    if method == "PUT" and partes == ["api", "doctor", "schedule"]:
        doctor_id = _doctor_de_sesion(repo, usuario)
        entrada = body.get("blocks")
        if not isinstance(entrada, list) or len(entrada) > 30:
            raise ErrorApi(400, "El campo 'blocks' debe ser una lista de máximo 30 bloques")
        bloques = []
        for bloque in entrada:
            if not isinstance(bloque, dict):
                raise ErrorApi(400, "Cada bloque debe ser un objeto {day, start, end}")
            inicio, fin = reglas.hora(bloque.get("start"), "start"), reglas.hora(bloque.get("end"), "end")
            if fin <= inicio:
                raise ErrorApi(400, "La hora de fin debe ser posterior a la de inicio")
            bloques.append({"dia_semana": reglas.entero(bloque, "day", 1, 7), "hora_inicio": inicio, "hora_fin": fin})
        if reglas.bloques_se_traslapan(bloques):
            raise ErrorApi(400, "Hay bloques de horario que se enciman en el mismo día")
        repo.reemplazar_horario(doctor_id, bloques)
        return _ok(app, repo.horario(doctor_id))

    if partes[:3] == ["api", "doctor", "inventory"]:
        doctor_id = _doctor_de_sesion(repo, usuario)
        _requerir_suscripcion(repo, doctor_id)
        if method == "GET" and len(partes) == 3:
            return _ok(app, repo.inventario(doctor_id))
        if method == "POST" and len(partes) == 3:
            item = {
                "name": reglas.texto(body, "name", max_len=120),
                "quantity": reglas.decimal(body, "quantity", Decimal("0"), Decimal("100000000")),
                "unit": reglas.texto(body, "unit", max_len=30),
            }
            try:
                return _ok(app, repo.guardar_insumo(doctor_id, item), 201)
            except Exception as error:
                if getattr(error, "pgcode", None) == "23505":
                    raise ErrorApi(409, "No se pudo guardar el insumo") from error
                raise
        if method == "DELETE" and len(partes) == 4:
            item_id = reglas.identificador(partes[3], "inventoryId", repo.usa_uuid)
            if not repo.eliminar_insumo(doctor_id, item_id):
                raise ErrorApi(404, "El insumo no existe")
            return _ok(app, {"deleted": True})

    if partes[:3] == ["api", "doctor", "promotions"]:
        doctor_id = _doctor_de_sesion(repo, usuario)
        _requerir_suscripcion(repo, doctor_id)
        if method == "GET" and len(partes) == 3:
            return _ok(app, repo.promociones(doctor_id))
        if method == "POST" and len(partes) == 3:
            promo = {
                "title": reglas.texto(body, "title", max_len=120),
                "description": reglas.texto(body, "description", requerido=False, max_len=500) or "",
                "discountPercent": reglas.entero(body, "discountPercent", 1, 90),
                "start": reglas.fecha(body.get("start"), "start"),
                "end": reglas.fecha(body.get("end"), "end"),
            }
            if promo["end"] < promo["start"]:
                raise ErrorApi(400, "La fecha final debe ser igual o posterior a la inicial")
            return _ok(app, repo.guardar_promocion(doctor_id, promo), 201)
        if method == "DELETE" and len(partes) == 4:
            promo_id = reglas.identificador(partes[3], "promotionId", repo.usa_uuid)
            if not repo.eliminar_promocion(doctor_id, promo_id):
                raise ErrorApi(404, "La promoción no existe")
            return _ok(app, {"deleted": True})

    # --- Flujo 2: expediente y consentimientos ----------------------------------
    if method == "PUT" and partes == ["api", "records"]:
        _requerir_rol(usuario, "PACIENTE")
        nacimiento = reglas.fecha(body.get("birthDate"), "birthDate", requerido=False)
        if nacimiento and not date(1900, 1, 1) <= nacimiento <= reglas.hoy():
            raise ErrorApi(400, "La fecha de nacimiento no es válida")
        repo.guardar_expediente(
            usuario["sub"],
            {
                "birthDate": nacimiento,
                "sex": reglas.opcion(body, "sex", reglas.SEXOS, requerido=False),
                "bloodType": reglas.opcion(body, "bloodType", reglas.TIPOS_SANGRE, requerido=False),
                "allergies": reglas.lista_textos(body, "allergies"),
                "chronicConditions": reglas.lista_textos(body, "chronicConditions"),
                "medications": reglas.lista_textos(body, "medications"),
                "notes": reglas.texto(body, "notes", requerido=False, max_len=5000) or "",
            },
        )
        return _ok(app, _expediente_completo(repo, usuario["sub"]))

    if method == "GET" and partes == ["api", "records", "access-log"]:
        _requerir_rol(usuario, "PACIENTE")
        return _ok(app, repo.accesos_expediente(usuario["sub"]))

    if method == "GET" and partes == ["api", "consents"]:
        _requerir_rol(usuario, "PACIENTE")
        return _ok(app, repo.consentimientos(usuario["sub"]))

    # Los objetos clínicos se mantienen privados en S3; sólo se entregan URLs firmadas y breves.
    if partes[:3] == ["api", "records", "documents"]:
        if method == "POST" and len(partes) == 3:
            _requerir_rol(usuario, "PACIENTE")
            try:
                carga = servicios_aws.crear_carga(
                    usuario["sub"],
                    body.get("name", ""),
                    body.get("contentType", ""),
                    body.get("size"),
                )
            except ValueError as error:
                raise ErrorApi(400, str(error)) from error
            except RuntimeError as error:
                raise ErrorApi(503, "El almacenamiento seguro no está configurado") from error
            return _ok(app, carga, 201)
        if method == "GET" and len(partes) == 3:
            if usuario["role"] == "PACIENTE":
                paciente_id = usuario["sub"]
            else:
                doctor_id = _doctor_de_sesion(repo, usuario)
                paciente_id = reglas.identificador(query.get("patientId"), "patientId", repo.usa_uuid)
                _requerir_suscripcion(repo, doctor_id)
                if not repo.tiene_consentimiento(paciente_id, doctor_id):
                    raise ErrorApi(403, "Se requiere consentimiento vigente")
                repo.registrar_acceso(paciente_id, usuario["sub"])
            try:
                return _ok(app, servicios_aws.listar_documentos(paciente_id))
            except RuntimeError as error:
                raise ErrorApi(503, "El almacenamiento seguro no está configurado") from error
        if method == "DELETE" and len(partes) == 4:
            _requerir_rol(usuario, "PACIENTE")
            try:
                eliminado = servicios_aws.eliminar_documento(
                    usuario["sub"],
                    reglas.identificador(partes[3], "documentId", True),
                )
            except RuntimeError as error:
                raise ErrorApi(503, "El almacenamiento seguro no está configurado") from error
            if not eliminado:
                raise ErrorApi(404, "El archivo no existe")
            return _ok(app, {"deleted": True})

    # --- Flujo 3: suscripción Stripe y pacientes --------------------------------
    if method == "POST" and partes == ["api", "subscriptions", "checkout"]:
        def iniciar_checkout():
            doctor_id = _doctor_de_sesion(repo, usuario)
            perfil_usuario = repo.usuario(usuario["sub"]) or {}
            success_url = reglas.texto(body, "successUrl", requerido=False, max_len=500)
            cancel_url = reglas.texto(body, "cancelUrl", requerido=False, max_len=500)
            idem_key = (_header(headers, "idempotency-key") or "").strip() or None
            sesion = pagos_stripe.crear_checkout_suscripcion(
                doctor_id,
                usuario["sub"],
                perfil_usuario.get("email"),
                success_url,
                cancel_url,
                idempotency_key=idem_key,
            )
            repo.registrar_checkout_pendiente(
                doctor_id,
                Decimal(str(sesion["amountUsd"])),
                sesion["sessionId"],
                sesion["mode"],
                reglas.hoy(),
            )
            return _ok(app, sesion, 201)

        return _ejecutar_idempotente(app, repo, usuario, method, path, headers, body, iniciar_checkout)

    if method == "POST" and partes == ["api", "subscriptions", "confirm"]:
        doctor_id = _doctor_de_sesion(repo, usuario)
        session_id = reglas.texto(body, "sessionId", max_len=255)
        existente = repo.suscripcion_por_sesion(session_id)
        if existente:
            if existente["doctorId"] != doctor_id:
                raise ErrorApi(403, "La sesión de pago no pertenece a este profesional")
            if existente["status"] == "ACTIVA":
                actual = _suscripcion(repo, doctor_id)
                return _ok(
                    app,
                    {
                        "subscription": _resumen_suscripcion_api(
                            doctor_id,
                            actual or existente,
                            existente.get("paymentMode") or "test",
                        ),
                        "payment": existente,
                    },
                )

        sesion = pagos_stripe.consultar_sesion_checkout(session_id)
        meta_doc = (sesion.get("metadata") or {}).get("doctorId") or sesion.get("clientReferenceId")
        if meta_doc != doctor_id:
            raise ErrorApi(403, "La sesión de pago no pertenece a este profesional")
        if sesion.get("paymentStatus") != "paid":
            raise ErrorApi(402, "El pago en Stripe aún no ha sido completado")

        monto = Decimal(str(round((sesion.get("amountTotal") or 2000) / 100, 2)))
        pago, activada = repo.activar_suscripcion_stripe(
            doctor_id,
            session_id,
            sesion.get("paymentIntentId"),
            monto,
            sesion.get("cardBrand"),
            sesion.get("cardLast4"),
            sesion.get("paymentMode") or "test",
        )
        if activada:
            _notificar(
                repo,
                usuario["sub"],
                "SUSCRIPCION_ACTIVA",
                "Suscripción activada",
                f"Tu suscripción está vigente hasta el {pago['end']}.",
                session_id,
            )
            metricas.registrar_metrica("PaymentSucceeded", 1)
        actual = _suscripcion(repo, doctor_id)
        return _ok(
            app,
            {
                "subscription": _resumen_suscripcion_api(
                    doctor_id,
                    actual or pago,
                    sesion.get("paymentMode") or "test",
                ),
                "payment": pago,
            },
        )

    if method == "GET" and partes == ["api", "doctor", "patients"]:
        doctor_id = _doctor_de_sesion(repo, usuario)
        _requerir_suscripcion(repo, doctor_id)
        return _ok(app, repo.pacientes_de(doctor_id))

    return None
