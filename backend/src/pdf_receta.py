"""Generador puro en Python de recetas médicas digitales en formato PDF 1.4."""
import textwrap


def _a_winansi(texto: str) -> bytes:
    normalizado = (
        (texto or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("•", "-")
        .replace("≥", ">=")
        .replace("≤", "<=")
        .replace("—", "-")
        .replace("–", "-")
    )
    return normalizado.encode("cp1252", errors="replace")


def _escapar_pdf(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _envolver_lineas(texto: str, ancho: int = 82) -> list[str]:
    lineas: list[str] = []
    for parrafo in (texto or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not parrafo.strip():
            lineas.append("")
            continue
        envueltas = textwrap.wrap(parrafo, width=ancho, replace_whitespace=False)
        lineas.extend(envueltas or [""])
    return lineas or [""]


def _comando_texto(fuente: str, tamano: float, x: float, y: float, texto: str) -> bytes:
    contenido = _escapar_pdf(_a_winansi(texto))
    return f"BT /{fuente} {tamano:.1f} Tf 1 0 0 1 {x:.1f} {y:.1f} Tm (".encode("ascii") + contenido + b") Tj ET\n"


def generar_pdf_receta(
    *,
    receta_id: str,
    consulta_id: str,
    fecha_emision: str,
    doctor_nombre: str,
    especialidad: str,
    paciente_nombre: str,
    diagnostico: str,
    tratamiento: str,
    notas: str | None = None,
    ubicacion: str | None = None,
) -> bytes:
    """Construye un PDF 1.4 válido (tamaño Carta 612x792) con offsets xref exactos."""
    paginas: list[list[bytes]] = []
    stream_actual: list[bytes] = []
    y = 742.0

    def iniciar_pagina(continuacion: bool = False) -> None:
        nonlocal stream_actual, y
        stream_actual = []
        titulo = "MiDoc · Receta Médica Digital" + (" (cont.)" if continuacion else "")
        stream_actual.append(_comando_texto("F2", 16.0, 50.0, 742.0, titulo))
        stream_actual.append(b"0.8 w 50 726 m 562 726 l S\n")
        y = 706.0

    def asegurar_espacio(alto: float) -> None:
        nonlocal y
        if y - alto < 72.0:
            paginas.append(stream_actual)
            iniciar_pagina(continuacion=True)

    iniciar_pagina(continuacion=False)

    metadatos = [
        ("Folio:", receta_id),
        ("Consulta:", consulta_id),
        ("Fecha de emisión:", fecha_emision),
        ("Profesional:", f"{doctor_nombre} ({especialidad})" if especialidad else doctor_nombre),
    ]
    if ubicacion:
        metadatos.append(("Ubicación:", ubicacion))
    metadatos.append(("Paciente:", paciente_nombre))

    for etiqueta, valor in metadatos:
        lineas_val = _envolver_lineas(str(valor), ancho=68)
        for idx_linea, linea_val in enumerate(lineas_val):
            asegurar_espacio(16.0)
            if idx_linea == 0:
                stream_actual.append(_comando_texto("F2", 10.0, 50.0, y, etiqueta))
            if linea_val:
                stream_actual.append(_comando_texto("F1", 10.0, 155.0, y, linea_val))
            y -= 14.0 if len(lineas_val) > 1 and idx_linea < len(lineas_val) - 1 else 16.0

    y -= 6.0
    asegurar_espacio(10.0)
    stream_actual.append(b"0.4 w 50 " + f"{y:.1f}".encode("ascii") + b" m 562 " + f"{y:.1f}".encode("ascii") + b" l S\n")
    y -= 20.0

    secciones = [
        ("Diagnóstico", diagnostico),
        ("Tratamiento e indicaciones", tratamiento),
    ]
    if notas and notas.strip():
        secciones.append(("Notas clínicas", notas))

    for titulo_sec, cuerpo_sec in secciones:
        asegurar_espacio(24.0)
        stream_actual.append(_comando_texto("F2", 12.0, 50.0, y, titulo_sec))
        y -= 16.0
        for linea in _envolver_lineas(cuerpo_sec, ancho=82):
            asegurar_espacio(14.0)
            if linea:
                stream_actual.append(_comando_texto("F1", 10.5, 50.0, y, linea))
            y -= 14.0
        y -= 8.0

    paginas.append(stream_actual)

    total_paginas = len(paginas)
    streams_bytes: list[bytes] = []
    for idx, cmds in enumerate(paginas, start=1):
        pie = (
            b"0.4 w 50 56 m 562 56 l S\n"
            + _comando_texto(
                "F1",
                8.5,
                50.0,
                42.0,
                f"Documento generado electrónicamente por MiDoc. Página {idx} de {total_paginas}.",
            )
        )
        streams_bytes.append(b"".join(cmds) + pie)

    objetos: dict[int, bytes] = {}
    # 1: Catalog, 2: Pages, 3: Helvetica, 4: Helvetica-Bold
    objetos[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    objetos[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"

    kids_refs: list[str] = []
    obj_num = 5
    for stream_data in streams_bytes:
        content_id = obj_num
        page_id = obj_num + 1
        obj_num += 2
        objetos[content_id] = (
            f"<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
            + stream_data
            + b"endstream"
        )
        objetos[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        kids_refs.append(f"{page_id} 0 R")

    objetos[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objetos[2] = f"<< /Type /Pages /Kids [{' '.join(kids_refs)}] /Count {len(kids_refs)} >>".encode("ascii")

    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    total_objs = max(objetos)
    for idx in range(1, total_objs + 1):
        offsets[idx] = len(salida)
        salida.extend(f"{idx} 0 obj\n".encode("ascii"))
        salida.extend(objetos[idx])
        salida.extend(b"\nendobj\n")

    xref_pos = len(salida)
    salida.extend(f"xref\n0 {total_objs + 1}\n".encode("ascii"))
    salida.extend(b"0000000000 65535 f \n")
    for idx in range(1, total_objs + 1):
        salida.extend(f"{offsets[idx]:010d} 00000 n \n".encode("ascii"))
    salida.extend(
        f"trailer\n<< /Size {total_objs + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(salida)
