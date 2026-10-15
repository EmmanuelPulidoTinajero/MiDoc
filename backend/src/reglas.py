"""Reglas de negocio y validación del input, sin AWS ni base de datos.

Todas las funciones de validación lanzan ErrorApi con el código HTTP y un
mensaje en español; app.handle la convierte en la respuesta JSON.
"""
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

# Ciudad de México no tiene horario de verano desde 2022: UTC-6 todo el año.
# Se usa un offset fijo para no depender de la base de datos de zonas horarias.
ZONA = timezone(timedelta(hours=-6), "America/Mexico_City")

ROLES = ("PACIENTE", "DOCTOR", "CLINICA")
ROLES_DOCTOR = ("DOCTOR", "CLINICA")
ESTADOS_CITA = ("PENDIENTE", "CONFIRMADA", "CANCELADA", "COMPLETADA")
ESTADOS_CITA_ACTIVA = ("PENDIENTE", "CONFIRMADA")
SEXOS = ("FEMENINO", "MASCULINO", "OTRO")
TIPOS_SANGRE = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
MONTO_SUSCRIPCION = Decimal("20.00")
DIAS_SUSCRIPCION = 30
DIAS_MAXIMOS_ANTICIPACION = 90
# Tarjeta de prueba que siempre se rechaza (misma convención que Stripe).
TARJETA_RECHAZADA = "4000000000000002"


class ErrorApi(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


def ahora():
    return datetime.now(ZONA)


def hoy():
    return ahora().date()


# ---------------------------------------------------------------------------
# Validación del input
# ---------------------------------------------------------------------------

def _falta(campo):
    return ErrorApi(400, f"El campo '{campo}' es obligatorio")


def texto(datos, campo, requerido=True, max_len=255, min_len=1):
    valor = datos.get(campo)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if requerido:
            raise _falta(campo)
        return None
    if not isinstance(valor, str):
        raise ErrorApi(400, f"El campo '{campo}' debe ser texto")
    valor = valor.strip()
    if len(valor) < min_len:
        raise ErrorApi(400, f"El campo '{campo}' debe tener al menos {min_len} caracteres")
    if len(valor) > max_len:
        raise ErrorApi(400, f"El campo '{campo}' admite máximo {max_len} caracteres")
    return valor


def email(datos, campo="email"):
    valor = texto(datos, campo, max_len=150)
    if not re.match(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", valor):
        raise ErrorApi(400, f"El campo '{campo}' no es un correo válido")
    return valor.lower()


def password(datos, campo="password"):
    valor = datos.get(campo)
    if not isinstance(valor, str) or not valor:
        raise _falta(campo)
    if not 8 <= len(valor) <= 128:
        raise ErrorApi(400, "La contraseña debe tener entre 8 y 128 caracteres")
    if not re.search(r"[A-Za-z]", valor) or not re.search(r"[0-9]", valor):
        raise ErrorApi(400, "La contraseña debe incluir letras y números")
    return valor


def opcion(datos, campo, opciones, requerido=True):
    valor = texto(datos, campo, requerido=requerido, max_len=50)
    if valor is None:
        return None
    valor = valor.upper()
    if valor not in opciones:
        raise ErrorApi(400, f"El campo '{campo}' debe ser uno de: {', '.join(opciones)}")
    return valor


def identificador(valor, campo, es_uuid):
    """En AWS los ids son UUID; en el modo de demostración local son textos como 'd-1'."""
    if not isinstance(valor, str) or not valor.strip():
        raise _falta(campo)
    if not es_uuid:
        return valor.strip()
    try:
        return str(uuid.UUID(valor.strip()))
    except ValueError:
        raise ErrorApi(400, f"El campo '{campo}' no es un identificador válido")


def fecha(valor, campo, requerido=True):
    if valor in (None, ""):
        if requerido:
            raise _falta(campo)
        return None
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ErrorApi(400, f"El campo '{campo}' debe tener formato AAAA-MM-DD")


def fecha_hora(valor, campo):
    """ISO 8601; sin zona se interpreta como hora de Ciudad de México."""
    if not isinstance(valor, str) or not valor.strip():
        raise _falta(campo)
    try:
        resultado = datetime.fromisoformat(valor.strip())
    except ValueError:
        raise ErrorApi(400, f"El campo '{campo}' debe tener formato ISO 8601, p. ej. 2026-10-20T10:00:00-06:00")
    if resultado.tzinfo is None:
        resultado = resultado.replace(tzinfo=ZONA)
    return resultado.astimezone(ZONA).replace(second=0, microsecond=0)


def hora(valor, campo):
    if not isinstance(valor, str) or not valor.strip():
        raise _falta(campo)
    try:
        return time.fromisoformat(valor.strip()).replace(second=0, microsecond=0)
    except ValueError:
        raise ErrorApi(400, f"El campo '{campo}' debe tener formato HH:MM")


def decimal(datos, campo, minimo, maximo, requerido=True):
    valor = datos.get(campo)
    if valor is None or valor == "":
        if requerido:
            raise _falta(campo)
        return None
    if isinstance(valor, bool):
        raise ErrorApi(400, f"El campo '{campo}' debe ser numérico")
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise ErrorApi(400, f"El campo '{campo}' debe ser numérico")
    if not numero.is_finite() or not minimo <= numero <= maximo:
        raise ErrorApi(400, f"El campo '{campo}' debe estar entre {minimo} y {maximo}")
    return numero.quantize(Decimal("0.01"))


def entero(datos, campo, minimo, maximo, requerido=True, defecto=None):
    valor = datos.get(campo)
    if valor is None or valor == "":
        if requerido:
            raise _falta(campo)
        return defecto
    if isinstance(valor, bool):
        raise ErrorApi(400, f"El campo '{campo}' debe ser un número entero")
    try:
        numero = int(str(valor))
    except ValueError:
        raise ErrorApi(400, f"El campo '{campo}' debe ser un número entero")
    if not minimo <= numero <= maximo:
        raise ErrorApi(400, f"El campo '{campo}' debe estar entre {minimo} y {maximo}")
    return numero


def lista_textos(datos, campo, max_elementos=30, max_len=150):
    valor = datos.get(campo)
    if valor is None:
        return []
    if not isinstance(valor, list) or len(valor) > max_elementos:
        raise ErrorApi(400, f"El campo '{campo}' debe ser una lista de máximo {max_elementos} textos")
    resultado = []
    for elemento in valor:
        if not isinstance(elemento, str) or not elemento.strip() or len(elemento.strip()) > max_len:
            raise ErrorApi(400, f"Los elementos de '{campo}' deben ser textos de 1 a {max_len} caracteres")
        resultado.append(elemento.strip())
    return resultado


# ---------------------------------------------------------------------------
# Flujo 1: horarios y agenda
# ---------------------------------------------------------------------------

def validar_fecha_agendable(dia, referencia):
    if dia < referencia:
        raise ErrorApi(400, "La fecha no puede estar en el pasado")
    if dia > referencia + timedelta(days=DIAS_MAXIMOS_ANTICIPACION):
        raise ErrorApi(400, f"Solo se puede agendar con {DIAS_MAXIMOS_ANTICIPACION} días de anticipación")


def generar_horarios(dia, bloques, duracion_min, ocupados, momento):
    """Horarios libres del doctor en `dia` (hora de Ciudad de México).

    bloques: horario semanal [{dia_semana (1=lunes), hora_inicio, hora_fin}]
    ocupados: datetimes con zona de las citas no canceladas
    momento: no se ofrecen horarios que ya pasaron
    """
    duracion = timedelta(minutes=duracion_min)
    ocupados = {o.astimezone(ZONA) for o in ocupados}
    libres = set()
    for bloque in bloques:
        if bloque["dia_semana"] != dia.isoweekday():
            continue
        actual = datetime.combine(dia, bloque["hora_inicio"], tzinfo=ZONA)
        fin = datetime.combine(dia, bloque["hora_fin"], tzinfo=ZONA)
        while actual + duracion <= fin:
            if actual > momento and actual not in ocupados:
                libres.add(actual)
            actual += duracion
    return sorted(libres)


def bloques_se_traslapan(bloques):
    por_dia = {}
    for bloque in bloques:
        por_dia.setdefault(bloque["dia_semana"], []).append(bloque)
    for del_dia in por_dia.values():
        del_dia.sort(key=lambda b: b["hora_inicio"])
        for anterior, siguiente in zip(del_dia, del_dia[1:]):
            if siguiente["hora_inicio"] < anterior["hora_fin"]:
                return True
    return False


# ---------------------------------------------------------------------------
# Flujo 3: suscripción y pago simulado
# ---------------------------------------------------------------------------

def resumen_suscripcion(periodos, referencia):
    """Une los periodos pagados del doctor en uno solo.

    Si hay un periodo vigente hoy, el resumen va de su inicio al fin del último
    periodo pagado por adelantado (se encadenan). Si no, es el periodo más reciente.
    """
    if not periodos:
        return None
    activos = [p for p in periodos if p.get("status") == "ACTIVA"]
    vigentes = [p for p in activos if suscripcion_vigente(p, referencia)]
    reciente = max(periodos, key=lambda p: p.get("end") or date.min)
    if not vigentes:
        return dict(reciente)
    fines = [p["end"] for p in activos if p.get("end") and p["end"] >= referencia]
    inicios = [p["start"] for p in vigentes if p.get("start")]
    pagado = max(activos, key=lambda p: p.get("end") or date.min)
    return {**pagado, "status": "ACTIVA", "start": min(inicios) if inicios else None,
            "end": max(fines) if fines else None}


def suscripcion_vigente(suscripcion, referencia):
    if not suscripcion or suscripcion.get("status") != "ACTIVA":
        return False
    inicio, fin = suscripcion.get("start"), suscripcion.get("end")
    if inicio is None or fin is None:
        return True
    return inicio <= referencia <= fin


def periodo_nueva_suscripcion(actual, referencia):
    """Si el doctor paga antes de vencer, el nuevo periodo empieza al terminar el actual."""
    if suscripcion_vigente(actual, referencia) and actual.get("end"):
        inicio = actual["end"] + timedelta(days=1)
    else:
        inicio = referencia
    return inicio, inicio + timedelta(days=DIAS_SUSCRIPCION - 1)


def _luhn_valido(numero):
    suma = 0
    for i, digito in enumerate(reversed(numero)):
        valor = int(digito) * (2 if i % 2 else 1)
        suma += valor - 9 if valor > 9 else valor
    return suma % 10 == 0


def _marca(numero):
    if numero.startswith("4"):
        return "VISA"
    if re.match(r"^(5[1-5]|2[2-7])", numero):
        return "MASTERCARD"
    if re.match(r"^3[47]", numero):
        return "AMEX"
    return "OTRA"


def procesar_pago_simulado(numero, mes, anio, cvv, referencia):
    """Valida la tarjeta como lo haría una pasarela; no cobra nada.
    Regresa (marca, últimos 4). Nunca se guarda el número completo."""
    numero = re.sub(r"[\s-]", "", numero or "")
    if not numero.isdigit() or not 13 <= len(numero) <= 19 or not _luhn_valido(numero):
        raise ErrorApi(400, "El número de tarjeta no es válido")
    if (anio, mes) < (referencia.year, referencia.month):
        raise ErrorApi(400, "La tarjeta está vencida")
    marca = _marca(numero)
    largo_cvv = 4 if marca == "AMEX" else 3
    if not (cvv or "").isdigit() or len(cvv) != largo_cvv:
        raise ErrorApi(400, f"El CVV debe tener {largo_cvv} dígitos")
    if numero == TARJETA_RECHAZADA:
        raise ErrorApi(402, "El banco rechazó el pago")
    return marca, numero[-4:]
