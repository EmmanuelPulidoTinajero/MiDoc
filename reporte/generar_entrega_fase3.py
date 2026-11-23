"""Genera el reporte PDF de fase tres con el formato del reporte de fase 1 usando Edge/Chrome local."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "https://github.com/EmmanuelPulidoTinajero/MiDoc"

# Misma "piel" que reporte-fase1: carta, Arial, títulos azul #0a5d8e con filete inferior,
# tablas con encabezado azul claro y bordes grises.
STYLE = """
@page { size: Letter; margin: 15mm 17mm 14mm; }
* { box-sizing: border-box; }
body { font: 9.6pt/1.42 Arial, Helvetica, sans-serif; color: #1a1a1a; margin: 0; }
h1 { font: 900 19pt/1.15 "Arial Black", Arial, sans-serif; color: #0a5d8e; margin: 0 0 1.2mm; letter-spacing: -.2pt; }
.sub { color: #545454; font-size: 9.8pt; margin: 0 0 4mm; }
.sub a { color: #0000ee; }
h2 { font: 900 11.4pt/1.2 "Arial Black", Arial, sans-serif; color: #0a5d8e; margin: 4.6mm 0 2mm;
     padding-bottom: 1.1mm; border-bottom: 1.4px solid #0a5d8e; }
h3 { font: 900 9.6pt/1.3 "Arial Black", Arial, sans-serif; color: #1a1a1a; margin: 3mm 0 1.2mm; }
p { margin: 0 0 1.8mm; }
ol, ul { margin: 0 0 2mm; padding-left: 6mm; }
li { margin-bottom: 1.1mm; }
b, strong { font-family: "Arial Black", Arial, sans-serif; font-weight: 900; font-size: 9.2pt; }
table { border-collapse: collapse; width: 100%; margin: 1.5mm 0 2.5mm; font-size: 8.9pt; line-height: 1.35; }
th, td { border: 1px solid #c9d3dc; padding: 1.5mm 2mm; text-align: left; vertical-align: top; }
th { background: #e8f1f8; font-family: "Arial Black", Arial, sans-serif; font-weight: 900; font-size: 8.6pt; }
td:first-child { white-space: nowrap; }
td.wrap { white-space: normal; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.4pt; color: #253746; }
.page { break-after: page; }
.page:last-child { break-after: auto; }
.diagram { margin: 2mm 0 1mm; }
.diagram svg { width: 100%; height: auto; display: block; }
.caption { font-size: 8.4pt; color: #545454; margin-top: 1mm; }
.note { color: #545454; font-size: 8.6pt; }
"""


def icon(x, y, color, glyph, size=30):
    """Ícono cuadrado al estilo de los iconos de arquitectura AWS (color de categoría + glifo)."""
    fs = 13 if len(glyph) <= 2 else 10
    return (f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="3" fill="{color}"/>'
            f'<text x="{x + size / 2}" y="{y + size / 2 + fs * .36}" text-anchor="middle" fill="#fff" '
            f'font-size="{fs}" font-weight="700">{glyph}</text>')


def box(x, y, w, h, title, lines, color=None, glyph=None, sub=None):
    """Caja blanca con ícono, título en negrita, filete y detalle en itálica (estilo de la captura)."""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#232f3e" stroke-width="1.2"/>']
    tx = x + 10
    if glyph:
        out.append(icon(x + 9, y + 9, color, glyph))
        tx = x + 48
    out.append(f'<text x="{tx}" y="{y + 23}" font-size="13" font-weight="700" fill="#232f3e">{title}</text>')
    ty = y + 36
    if sub:
        out.append(f'<text x="{tx}" y="{y + 36}" font-size="10" fill="#232f3e">{sub}</text>')
        ty = y + 48
    out.append(f'<line x1="{tx}" y1="{ty - 6}" x2="{x + w - 10}" y2="{ty - 6}" stroke="#9aa5b1" stroke-width=".8"/>')
    for i, line in enumerate(lines):
        out.append(f'<text x="{tx}" y="{ty + 7 + i * 12}" font-size="9.6" font-style="italic" fill="#232f3e">{line}</text>')
    return "".join(out)


def arrow(d, label=None, lx=0, ly=0, dashed=False, anchor="middle"):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = f'<path d="{d}" fill="none" stroke="#232f3e" stroke-width="1.3" marker-end="url(#ah)"{dash}/>'
    if label:
        for i, part in enumerate(label.split("|")):
            out += (f'<text x="{lx}" y="{ly + i * 11}" font-size="9.6" text-anchor="{anchor}" '
                    f'fill="#232f3e" stroke="#fff" stroke-width="3" paint-order="stroke">{part}</text>')
    return out


ORANGE, GREEN, DB, RED, PINK, PURPLE, BLUE = "#ED7100", "#7AA116", "#C925D1", "#DD344C", "#E7157B", "#8C4FFF", "#2E73B8"


def diagram():
    p = ['<svg viewBox="0 0 1080 700" xmlns="http://www.w3.org/2000/svg" font-family="Arial, Helvetica, sans-serif" '
         'role="img" aria-label="Arquitectura de MiDoc en AWS">',
         '<defs><marker id="ah" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
         '<path d="M0 0L9 4.5L0 9z" fill="#232f3e"/></marker></defs>']

    # Contenedores: AWS Cloud > región > VPC
    p.append('<rect x="262" y="8" width="810" height="676" fill="none" stroke="#232f3e" stroke-width="1.3"/>')
    p.append('<rect x="262" y="8" width="30" height="24" fill="#232f3e"/>'
             '<text x="277" y="24" text-anchor="middle" font-size="10" font-weight="700" fill="#fff">aws</text>'
             '<text x="300" y="26" font-size="13" font-weight="700" fill="#232f3e">AWS Cloud</text>')
    p.append('<rect x="276" y="44" width="784" height="626" fill="none" stroke="#147EBA" stroke-width="1.3" stroke-dasharray="7 5"/>')
    p.append('<rect x="276" y="44" width="22" height="22" fill="#147EBA"/>'
             '<path d="M283 49v12M283 50h9l-2 3 2 3h-9" stroke="#fff" stroke-width="1.6" fill="none"/>'
             '<text x="305" y="60" font-size="12" font-weight="700" fill="#147EBA">us-east-1</text>')
    p.append('<rect x="306" y="194" width="740" height="250" fill="none" stroke="#8C4FFF" stroke-width="1.3"/>'
             '<rect x="1024" y="194" width="22" height="22" fill="#8C4FFF"/>'
             '<text x="1035" y="209" text-anchor="middle" font-size="9" font-weight="700" fill="#fff">VPC</text>'
             '<text x="1018" y="210" text-anchor="end" font-size="12" font-weight="700" fill="#8C4FFF">VPC default · subredes privadas</text>')

    # Lado izquierdo (fuera de AWS)
    p.append(box(10, 18, 232, 236, "GitHub Actions", [], PURPLE, "GH", sub="repo + workflows"))
    gh = [("ci.yml", ["push / PR a main: unittest (107),", "tsc + Vitest + build Angular,", "terraform fmt + validate"]),
          ("cd.yml", ["push a main o manual: preflight", "de credenciales, terraform apply,", "publica SPA + config.json, smoke"]),
          ("terraform", ["todo lo de us-east-1 (49 recursos)", "se crea y destruye con IaC"])]
    y = 76
    for name, lines in gh:
        p.append(f'<text x="58" y="{y}" font-size="10.5" font-weight="700" fill="#232f3e">{name}</text>')
        for i, line in enumerate(lines):
            p.append(f'<text x="58" y="{y + 13 + i * 12}" font-size="9.6" font-style="italic" fill="#232f3e">{line}</text>')
        y += 13 + len(lines) * 12 + 12
    p.append(box(10, 272, 232, 86, "Navegador", ["paciente · doctor · clínica", "HTTPS → SPA en S3 y API Gateway"], BLUE, "WEB"))
    p.append(box(10, 378, 232, 92, "Stripe", ["Checkout Sessions $20 USD/mes", "webhook HMAC → /api/webhooks", "modos test · live · simulado"], "#635BFF", "S"))
    p.append(box(10, 602, 232, 62, "Correo", ["suscripción SNS (alert_email)"], PINK, "@"))

    # Fila 1
    p.append(box(320, 86, 240, 86, "API Gateway", ["HTTP API v2 · HTTPS · CORS", "ruta $default → Lambda", "logs JSON de acceso"], PURPLE, "API"))
    p.append(box(590, 86, 220, 86, "Amazon S3", ["bucket público midoc-frontend", "SPA Angular 22 + config.json", "(apiUrl, paymentMode)"], GREEN, "S3"))
    p.append(box(840, 86, 200, 86, "Secrets Manager", ["llave JWT · credenciales RDS", "config. Stripe (modo, llave,", "webhook, precio)"], RED, "SM"))

    # VPC
    p.append(box(320, 228, 240, 122, "AWS Lambda", ["midoc-api · Python 3.12 · 256 MB", "LabRole · subredes 172.31.96/112", "VPC endpoints: S3, DynamoDB,", "Secrets Manager", "logs JSON + 12 métricas EMF"], ORANGE, "λ"))
    p.append(box(320, 370, 150, 60, "NAT Gateway", ["salida HTTPS a Stripe"], PURPLE, "NAT"))
    p.append(box(830, 228, 200, 96, "Amazon RDS", ["db.t3.micro · privada", "cifrada · sslmode=require", "migraciones 001–004"], DB, "DB", sub="PostgreSQL 16"))

    # Fila 3
    p.append(box(320, 466, 190, 88, "Amazon S3", ["bucket privado AES-256", "estudios + recetas PDF", "URLs firmadas 300 s"], GREEN, "S3"))
    p.append(box(530, 466, 240, 88, "DynamoDB", ["bitácora de accesos al expediente", "pk=PACIENTE#id · sk=ACCESO#…", "tolerante a fallos"], DB, "DDB"))
    p.append(box(840, 466, 200, 88, "EventBridge", ["regla midoc-reminders", "rate(15 minutes): citas 24 h", "y vencimientos de suscripción"], PINK, "EB"))

    # Fila 4
    p.append(box(320, 576, 440, 82, "Amazon CloudWatch", [
        "2 log groups (14 días) · 12 métricas EMF (MiDoc) + nativas AWS/Lambda,",
        "AWS/ApiGateway y AWS/RDS · 10 alarmas · dashboard midoc-estado · 4 Logs Insights"], PINK, "CW"))
    p.append(box(840, 576, 200, 82, "Amazon SNS", ["tópico midoc-alerts", "notificación de alarmas"], PINK, "SNS"))

    # Flechas
    p.append(arrow("M242 336H256V129H320"))
    p.append(arrow("M242 292H250V72H660V86", "HTTPS · index.html + config.json", 470, 68))
    p.append(arrow("M242 34H760V86", "cd.yml · publish_frontend.py", 470, 30))
    p.append(arrow("M440 172V228", "proxy", 446, 204, anchor="start"))
    p.append(arrow("M540 228V183H940V172", "GetSecretValue", 930, 196, anchor="end"))
    p.append(arrow("M560 272H830", "SQL :5432 · TLS", 695, 266))
    p.append(arrow("M395 350V370"))
    p.append(arrow("M320 400H242"))
    p.append(arrow("M490 350V466", "PutObject ·|URL firmada", 484, 452, anchor="end"))
    p.append(arrow("M545 350V466", "PutItem", 551, 452, anchor="start"))
    p.append(arrow("M940 466V338H560", "invoca · rate(15 min)", 765, 332))
    p.append(arrow("M560 308H795V594H760", "logs + EMF", 801, 560, anchor="start"))
    p.append(arrow("M760 617H840", "ALARM", 800, 611))
    p.append(arrow("M940 658V677H126V664", "correo de la alarma", 540, 680))
    p.append('</svg>')
    return "".join(p)


PAGES = [f"""
<h1>MiDoc — Marketplace de Salud</h1>
<p class="sub">Reporte de Fase 3 · Repositorio: <a href="{REPO}">github.com/EmmanuelPulidoTinajero/MiDoc</a></p>

<h2>1. Descripción de la aplicación y problema que resuelve</h2>
<p>MiDoc es un marketplace de salud que conecta a pacientes con doctores y clínicas. Hoy el expediente médico
de un paciente vive fragmentado entre consultorios, sin que el paciente controle quién accede a su información,
y los doctores independientes y clínicas pequeñas carecen de herramientas accesibles para agendar, dar
seguimiento, emitir recetas y llevar inventario. MiDoc centraliza el expediente en manos del paciente, quien
decide explícitamente con quién compartirlo, y ofrece a doctores y clínicas un panel de gestión mediante una
suscripción mensual de $20 USD; para el paciente la app es gratuita.</p>
<p>La aplicación es una SPA en Angular 22 servida desde S3 que consume una API REST en Python 3.12 sobre
Lambda y API Gateway, con PostgreSQL en RDS como fuente de verdad. Toda la infraestructura se crea y destruye
con Terraform y se despliega con GitHub Actions. Además de los tres flujos, incluye inventario, promociones,
mensajería condicionada por cita o consentimiento, bandeja de avisos y recordatorios automáticos.</p>

<h2>2. Flujos end to end desarrollados</h2>
<ol>
<li><b>Búsqueda y agenda:</b> el paciente filtra profesionales por especialidad, ubicación y texto, ordena por
precio o disponibilidad, abre el perfil (con promociones vigentes y horarios libres) y agenda, reprograma o
cancela su cita; el profesional configura su horario semanal y confirma o cancela.</li>
<li><b>Expediente y consentimiento:</b> el paciente crea y actualiza su expediente, sube estudios privados
(PDF, JPG, PNG, DICOM ≤ 10 MB) a S3, concede o revoca acceso por doctor o clínica y consulta la bitácora
de quién vio su expediente; cada lectura profesional queda auditada en PostgreSQL y DynamoDB.</li>
<li><b>Suscripción y consulta del doctor:</b> el doctor o clínica paga su suscripción de $20 USD/30 días con
Stripe Checkout; con suscripción activa y consentimiento vigente atiende la cita, registra diagnóstico,
tratamiento y notas, y genera una receta digital en PDF guardada en S3 que el paciente descarga e imprime.</li>
</ol>

<h2>3. Servicios de AWS utilizados y por qué</h2>
<table>
<tr><th>Servicio</th><th>Uso en MiDoc y justificación</th></tr>
<tr><td>AWS Lambda</td><td>Ejecuta la API y el job de recordatorios. Escala con la demanda y no cobra cuando no hay tráfico, ideal para un proyecto con uso intermitente.</td></tr>
<tr><td>Amazon API Gateway</td><td>HTTP API v2 que publica la Lambda por HTTPS con CORS y logs de acceso, sin administrar servidores ni certificados.</td></tr>
<tr><td>Amazon RDS (PostgreSQL 16)</td><td>Datos relacionales con integridad referencial: usuarios, citas, expediente, consentimientos, suscripciones y recetas. Privada, cifrada y con TLS obligatorio.</td></tr>
<tr><td>Amazon S3</td><td>Dos buckets: uno público para la SPA y uno privado cifrado (AES-256) para estudios y recetas PDF, entregados con URLs firmadas de 300 s.</td></tr>
<tr><td>Amazon CloudWatch + SNS</td><td>Logs, métricas de negocio y de infraestructura, alarmas y dashboard; SNS reparte las notificaciones de alarma.</td></tr>
<tr><td class="wrap">Complementarios</td><td><b>Secrets Manager</b> (llave JWT, credenciales de RDS y Stripe), <b>DynamoDB</b> (bitácora de accesos), <b>EventBridge</b> (recordatorios cada 15 min) y <b>VPC + NAT Gateway</b> (Lambda privada con salida solo hacia Stripe).</td></tr>
</table>
""", f"""
<h2>4. Diagrama de la arquitectura</h2>
<div class="diagram">{diagram()}</div>
<p class="caption">Todo lo que está dentro de us-east-1 lo crea <code>terraform apply</code> (local o desde <code>cd.yml</code>) con el
rol <code>LabRole</code> del Learner Lab. La Lambda vive en subredes privadas: llega a S3, DynamoDB y Secrets
Manager por VPC endpoints y a Stripe por el NAT Gateway; RDS solo acepta conexiones del security group de la Lambda.</p>

<h2>5. Roles del equipo</h2>
<table>
<tr><th>Integrante</th><th>Rol</th></tr>
<tr><td>Emmanuel Pulido Tinajero</td><td>DevOps e infraestructura (Terraform, CI/CD, monitoreo); soporte técnico a frontend y backend</td></tr>
<tr><td>David (Dakewer)</td><td>Frontend: app de pacientes y profesionales, design system</td></tr>
<tr><td>Gilberto Anaya (gilbertoanayam17)</td><td>Backend: APIs, expediente, pagos con Stripe y lógica de negocio</td></tr>
</table>
""", """
<h2>6. CI/CD</h2>
<p>El repositorio usa dos workflows de GitHub Actions:</p>
<table>
<tr><th>Workflow</th><th>Disparador</th><th>Qué hace</th></tr>
<tr><td><code>ci.yml</code></td><td>push y pull request a <code>main</code></td><td class="wrap">Tres jobs en paralelo. <b>backend:</b> 107 pruebas <code>unittest</code> (reglas de negocio, adaptadores HTTP, Stripe, PDF de receta, monitoreo). <b>frontend:</b> <code>tsc</code> de app y pruebas, Vitest y <code>ng build</code> de producción. <b>infrastructure:</b> <code>terraform fmt -check</code>, <code>terraform validate</code> y <code>py_compile</code> de los scripts de despliegue.</td></tr>
<tr><td><code>cd.yml</code></td><td>push a <code>main</code> o ejecución manual</td><td class="wrap"><b>preflight:</b> valida que existan las credenciales temporales del Lab y la llave JWT como <i>repository secrets</i>, que la llave de Stripe coincida con el modo (<code>sk_test_</code>/<code>sk_live_</code>) y que el token siga vigente (<code>sts get-caller-identity</code>). <b>deploy:</b> compila el frontend, <code>terraform apply</code> (estado opcional en S3), publica la SPA y <code>config.json</code>, y corre smoke checks de <code>/health</code>, <code>/api/doctors</code>, frontend, alarmas y log groups.</td></tr>
</table>
<p>La infraestructura es 100% código: <code>terraform destroy</code> elimina los 49 recursos (incluidos ambos buckets y los
secretos sin ventana de recuperación) y <code>verify_teardown.py</code> audita 21 categorías para confirmar que no quedan remanentes.</p>

<h2>7. Monitoreo</h2>
<p>La Lambda escribe logs JSON estructurados (con PII y secretos redactados) y publica métricas con
<b>Embedded Metric Format</b> en el namespace <code>MiDoc</code>, sin llamadas extra a la API de CloudWatch: latencia,
errores 5xx, citas creadas, consultas registradas, logins fallidos, checkout/pagos exitosos/fallidos, ejecuciones y
errores de recordatorios, y errores de documentos y de auditoría. API Gateway escribe su propio log de acceso.</p>
<table>
<tr><th>Alarma</th><th>Métrica</th><th>Se dispara cuando</th></tr>
<tr><td>api-errores-5xx</td><td>MiDoc / ServerErrors</td><td>&gt; 5 errores en 5 min</td></tr>
<tr><td>api-latencia-p95</td><td>MiDoc / RequestLatencyMs</td><td>p95 &gt; 3000 ms</td></tr>
<tr><td>payment-failed</td><td>MiDoc / PaymentFailed</td><td>&gt; 3 pagos fallidos (webhooks inválidos o checkout con error)</td></tr>
<tr><td>reminders-errors</td><td>MiDoc / RemindersJobErrors</td><td>cualquier fallo del job de EventBridge</td></tr>
<tr><td>lambda-errors / -throttles</td><td>AWS/Lambda</td><td>errores o throttling &gt; 0</td></tr>
<tr><td>apigw-5xx</td><td>AWS/ApiGateway / 5xx</td><td>&gt; 5 respuestas 5xx</td></tr>
<tr><td>rds-cpu / -storage / -connections</td><td>AWS/RDS</td><td>CPU &gt; 80 %, espacio libre &lt; 2 GB, conexiones &gt; 45</td></tr>
</table>
<p>Las 10 alarmas notifican al tópico SNS <code>midoc-alerts</code> (suscripción por correo con la variable <code>alert_email</code>).
El dashboard <code>midoc-estado</code> reúne tráfico, latencia, errores, métricas de negocio, salud de RDS y el estado de
las alarmas, y hay 4 consultas de Logs Insights guardadas (errores de la API, peticiones lentas, 5xx de acceso y
pagos/recordatorios) para depurar.</p>
""", """
<h2>8. Decisiones técnicas y su justificación</h2>
<table>
<tr><th>Decisión</th><th>Justificación</th></tr>
<tr><td class="wrap">Serverless (Lambda + API Gateway) en lugar de EC2</td><td>Uso intermitente durante el semestre: se paga por invocación, escala solo y no hay sistema operativo que parchar.</td></tr>
<tr><td class="wrap">JWT propio + Secrets Manager en lugar de Cognito</td><td>El Learner Lab no permite crear User Pools. Se usa JWT HS256 de 1 h, contraseñas con <code>scrypt</code>, límite de 5 intentos de login por 300 s y la llave firmante en Secrets Manager.</td></tr>
<tr><td class="wrap">PostgreSQL como fuente de verdad + DynamoDB para la bitácora</td><td>Citas, consentimientos y pagos necesitan transacciones e integridad referencial; la bitácora de accesos es un log de escritura por clave que encaja en DynamoDB y no bloquea la lectura si falla.</td></tr>
<tr><td class="wrap">Lambda en subredes privadas con NAT y VPC endpoints</td><td>RDS no es pública; la Lambda necesita alcanzarla dentro de la VPC. Los endpoints mantienen privado el tráfico a S3, DynamoDB y Secrets Manager, y el NAT solo se usa para salir a <code>api.stripe.com</code>.</td></tr>
<tr><td class="wrap">Stripe Checkout con modos test / live / simulado</td><td>Checkout evita manejar datos de tarjeta (PCI). El modo se elige con una variable de Terraform sin cambiar código; sin llave se usa el modo simulado, rotulado en la interfaz.</td></tr>
<tr><td class="wrap">SPA en S3 con hash routing y <code>config.json</code></td><td>CloudFront no está disponible en el Lab; <code>HashLocationStrategy</code> permite deep links y recargas sin reglas de reescritura, y <code>config.json</code> evita recompilar cuando cambia la URL de la API.</td></tr>
<tr><td class="wrap">Avisos in-app + EventBridge en lugar de correo/SMS</td><td>SES está denegado en el Lab. Los recordatorios de citas (24 h) y vencimientos (7 días) se guardan en una bandeja dentro de la app.</td></tr>
<tr><td class="wrap">Métricas con EMF</td><td>Las métricas salen de los propios logs: no agregan latencia ni permisos de <code>PutMetricData</code> a la petición.</td></tr>
<tr><td class="wrap">Terraform + destroy verificado</td><td>Las credenciales del Lab expiran; poder recrear todo en minutos y comprobar que no quedan recursos evita costos y deriva de configuración.</td></tr>
</table>
"""]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path)
    args = parser.parse_args()
    candidates = [args.browser, Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
                  Path("C:/Program Files/Google/Chrome/Application/chrome.exe")]
    browser = next((p for p in candidates if p and p.is_file()), None)
    if not browser:
        parser.error("Indica --browser con la ruta de Edge o Chrome instalado")
    html_path = ROOT / "ENTREGA-FASE3.html"
    pdf_path = ROOT / "ENTREGA-FASE3.pdf"
    html_path.write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>MiDoc fase 3</title>'
                         f'<style>{STYLE}</style><body>' + ''.join(f'<section class="page">{p}</section>' for p in PAGES)
                         + '</body></html>', encoding="utf-8")
    profile = Path(tempfile.mkdtemp(prefix="midoc-pdf-")).resolve()
    try:
        subprocess.run([str(browser), "--headless=new", "--disable-gpu", "--disable-extensions",
                        "--disable-background-networking", "--no-first-run", "--no-pdf-header-footer",
                        f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                       check=True, timeout=60, capture_output=True)
    finally:
        if profile.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            shutil.rmtree(profile, ignore_errors=True)
    if not pdf_path.is_file():
        raise RuntimeError("El navegador no generó el PDF")
    print(pdf_path)


if __name__ == "__main__":
    main()
