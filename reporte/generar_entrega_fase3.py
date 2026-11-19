"""Genera el reporte PDF de fase tres (5 páginas) usando Edge/Chrome local."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STYLE = """
@page { size:A4; margin:14mm; }
*{box-sizing:border-box} body{font:10.5pt/1.42 Arial,sans-serif;color:#17352b;margin:0}
h1{font-size:26pt;margin:8mm 0 3mm}h2{font-size:16pt;margin:5mm 0 3mm}h3{font-size:12pt}
p{margin:2.5mm 0}table{border-collapse:collapse;width:100%;font-size:9.5pt;margin:4mm 0}
td,th{padding:2.5mm;border:1px solid #b8c8bf;text-align:left;vertical-align:top}th{background:#e3eee8}
.page{break-after:page}.page:last-child{break-after:auto}.meta{font-size:9pt;color:#42584f}
.pending{border-left:4px solid #8a4b00;background:#fff7e5;padding:3mm;margin:4mm 0}
a{color:#164a3d}li{margin-bottom:2mm}svg{width:100%;height:auto}small{font-size:9pt}
code{font-family:Consolas,monospace;font-size:9pt}
"""

PAGES = ["""
<p class="meta">MiDoc · Proyecto Integrador · Fase 3 · 19 de noviembre de 2026 · 1/5</p>
<h1>Marketplace de salud</h1><h2>Fase 3: producto completo con observabilidad</h2>
<p><b>Estado:</b> los tres flujos end-to-end funcionan en AWS con datos reales en RDS PostgreSQL; la única función simulada, por decisión acordada, es el pago cuando no se configura una llave de Stripe (modo <code>simulado</code>). El mismo binario activa cobros reales de prueba al establecer <code>payment_mode="test"</code> con una llave <code>sk_test_</code>.</p>
<p><b>Repositorio:</b> <a href="https://github.com/EmmanuelPulidoTinajero/MiDoc">github.com/EmmanuelPulidoTinajero/MiDoc</a> · rama <code>feat/producto-completo</code>.</p>
<table><tr><th>Flujo</th><th>Qué demuestra</th><th>Evidencia en vivo</th></tr>
<tr><td>1. Búsqueda y agenda</td><td>Filtros por especialidad/ubicación/texto, orden por precio y disponibilidad, perfil del profesional en ruta propia con deep link (<code>#/doctores/:id</code>), horarios libres UTC-6, reserva con confirmación modal.</td><td>E2E en nube verde; API <code>/api/doctors</code> y disponibilidad respondiendo.</td></tr>
<tr><td>2. Expediente y consentimiento</td><td>Expediente por secciones, documentos privados S3 con URL firmada de 300 s, concesión/revocación con confirmación, bitácora «quién vio mi expediente» (PostgreSQL + DynamoDB).</td><td>Pruebas E2E de consentimiento, acceso y auditoría en nube.</td></tr>
<tr><td>3. Suscripción y consulta</td><td>Stripe Checkout ($20 USD/30 días, test/live/simulado), consulta con diagnóstico/tratamiento, receta digital PDF real en S3 con descarga firmada.</td><td>Checkout→confirm verificado con curl contra la API desplegada; PDF generado por <code>pdf_receta.py</code>.</td></tr></table>
<h3>Design system propio</h3>
<p>Tokens WCAG 2.x en <code>_tokens.css</code> (76 tokens, contrastes probados por <code>tokens.spec.ts</code>), 9 primitivas (<code>ds-button, ds-field, ds-card, ds-badge, ds-modal, ds-alert-banner, ds-empty-state, ds-page-header, ds-skeleton</code>) usadas en todas las pantallas, identidad «papel cálido / tinta verde / serif editorial» definida en <code>design/system.md</code> con direcciones visuales aprobadas por el equipo.</p>
""", """
<p class="meta">MiDoc · Servicios y arquitectura · 2/5</p><h2>Arquitectura implementada</h2>
<svg viewBox="0 0 740 340" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Navegador, S3, API Gateway, Lambda, Stripe, RDS, DynamoDB, S3 documentos, EventBridge, CloudWatch y SNS">
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#246b59"/></marker></defs>
<g fill="#eef6f1" stroke="#246b59" stroke-width="2"><rect x="10" y="15" width="165" height="48" rx="7"/><rect x="245" y="15" width="210" height="48" rx="7"/><rect x="10" y="110" width="165" height="48" rx="7"/><rect x="245" y="110" width="210" height="48" rx="7"/><rect x="525" y="110" width="205" height="48" rx="7"/><rect x="10" y="245" width="150" height="48" rx="7"/><rect x="180" y="245" width="150" height="48" rx="7"/><rect x="350" y="245" width="150" height="48" rx="7"/><rect x="520" y="185" width="210" height="48" rx="7"/><rect x="520" y="245" width="210" height="48" rx="7"/></g>
<g fill="none" stroke="#246b59" stroke-width="2" marker-end="url(#a)"><path d="M175 39H245"/><path d="M92 63V110"/><path d="M175 134H245"/><path d="M455 134H525"/><path d="M350 158V205H85V245"/><path d="M350 205H255V245"/><path d="M350 205H425V245"/><path d="M455 130H600V185"/><path d="M625 233V245"/></g>
<g fill="#17352b" font-family="Arial" font-size="15" text-anchor="middle"><text x="92" y="45">Navegador</text><text x="350" y="45">Angular 22 / S3 HTTPS</text><text x="92" y="139">API Gateway HTTP v2</text><text x="350" y="139">Lambda Python 3.12 (VPC+NAT)</text><text x="627" y="139">RDS PostgreSQL 16</text><text x="85" y="274">Secrets Manager</text><text x="255" y="274">S3 documentos/recetas</text><text x="425" y="274">DynamoDB</text><text x="625" y="214">Stripe Checkout</text><text x="625" y="274">EventBridge → CW Alarmas/SNS</text><text x="210" y="29" font-size="12">HTTPS</text><text x="63" y="92" font-size="12">HTTPS</text><text x="500" y="123" font-size="12">TLS</text></g></svg>
<table><tr><th>Servicio</th><th>Uso en fase 3</th></tr>
<tr><td>Lambda + API Gateway</td><td>API Python 3.12 en subredes privadas con salida NAT a <code>api.stripe.com</code>; CORS y logs JSON hacia CloudWatch.</td></tr>
<tr><td>RDS PostgreSQL 16</td><td>Fuente relacional (usuarios, citas, expediente, suscripciones Stripe, recetas); migraciones 001–004; privada, cifrada, <code>sslmode=require</code>.</td></tr>
<tr><td>Secrets Manager</td><td>JWT, credenciales RDS y configuración Stripe (<code>payment_mode</code>, llave, webhook, precio).</td></tr>
<tr><td>S3 (2 buckets)</td><td>SPA Angular (endpoint REST HTTPS + <code>HashLocationStrategy</code>) y bucket privado cifrado AES-256 para estudios y recetas PDF.</td></tr>
<tr><td>DynamoDB</td><td>Bitácora de accesos al expediente (<code>pk=PACIENTE#id</code>); tolerante a fallos de lectura.</td></tr>
<tr><td>Stripe</td><td>Checkout Sessions + confirmación + webhook HMAC; modos <code>test</code>/<code>live</code>/<code>simulado</code>.</td></tr>
<tr><td>EventBridge</td><td>Recordatorios cada 15 min (citas próximas y vencimientos de suscripción).</td></tr>
<tr><td>CloudWatch + SNS</td><td>2 log groups (14 días), 12 métricas EMF en namespace <code>MiDoc</code>, 10 alarmas, dashboard <code>midoc-estado</code>, tópico SNS <code>midoc-alerts</code>.</td></tr></table>
""", """
<p class="meta">MiDoc · Observabilidad y CI/CD · 3/5</p><h2>Observabilidad CloudWatch</h2>
<p><b>12 métricas EMF</b> (namespace <code>MiDoc</code>): <code>AppointmentsCreated, ConsultationsRegistered, PaymentCheckoutCreated, PaymentSucceeded, PaymentFailed, LoginFailures, RequestLatencyMs, ServerErrors, RemindersJobRuns</code> y métricas de infraestructura; los logs redactan PII y secretos.</p>
<table><tr><th>Alarma</th><th>Umbral</th><th>Estado en la validación</th></tr>
<tr><td>api-errores-5xx / apigw-5xx / lambda-errors</td><td>Errores &gt; 0 en ventana</td><td>OK</td></tr>
<tr><td>api-latencia-p95</td><td>p95 &gt; 3000 ms</td><td>OK</td></tr>
<tr><td>payment-failed</td><td>PaymentFailed &gt; 0</td><td><b>ALARM</b> — disparada por los webhooks maliciosos intencionales del E2E: evidencia de funcionamiento</td></tr>
<tr><td>reminders-errors</td><td>Fallos del job &gt; 0</td><td>OK</td></tr>
<tr><td>lambda-throttles</td><td>Throttles &gt; 0</td><td>OK</td></tr>
<tr><td>rds-cpu / rds-storage / rds-connections</td><td>CPU &gt; 80%, espacio &lt; 5 GB, conexiones &gt; 90</td><td>OK</td></tr></table>
<p>Dashboard <code>midoc-estado</code> con las métricas y alarmas; 4 consultas de Logs Insights listas para depuración. El tópico SNS <code>midoc-alerts</code> queda sin suscripción de correo por decisión del equipo (el Lab no permite SES); las alarmas son visibles en consola y dashboard.</p>
<h3>CI/CD en GitHub Actions</h3>
<p><code>ci.yml</code>: pruebas backend (107), <code>tsc</code> + Vitest (58) + build Angular, y Terraform <code>fmt/validate</code> + <code>py_compile</code> en cada PR. <code>cd.yml</code> en <code>main</code> (o manual): preflight de credenciales, <code>terraform apply</code>, publicación del frontend y smoke checks. Limitación documentada: el Learner Lab expira sesión y credenciales, por lo que el CD en la nube requiere credenciales frescas de la sesión activa.</p>
<h3>Decisiones clave</h3>
<table><tr><th>Decisión</th><th>Justificación</th></tr>
<tr><td>Cognito → JWT propio + Secrets Manager</td><td>El Learner Lab no permite User Pools (Tarea 2, p. 6); JWT HS256 con <code>scrypt</code> y límite 429 en login.</td></tr>
<tr><td>Modo de pago <code>simulado</code></td><td>Único comportamiento simulado permitido (acuerdo S2): sesiones <code>cs_sim_*</code> sin llave; la misma ruta de código acepta <code>sk_test_</code> real sin cambios de producto.</td></tr>
<tr><td>SPA por S3 REST + hash routing</td><td>Sin CloudFront (denegado en el Lab); <code>HashLocationStrategy</code> permite deep links y refresh sin rewrites.</td></tr>
<tr><td>Bitácora en DynamoDB</td><td>Persistencia políglota (Tarea 2): log de accesos por clave única, complementa las transacciones de PostgreSQL.</td></tr></table>
""", """
<p class="meta">MiDoc · Verificación · 4/5</p><h2>Verificación y evidencia</h2>
<table><tr><th>Capa</th><th>Resultado</th></tr>
<tr><td>Backend (unittest)</td><td>107 pruebas OK — negocio, adaptadores HTTP, Stripe (incl. modo simulado), PDF de receta, monitoreo.</td></tr>
<tr><td>Frontend</td><td><code>tsc</code> verde; 58 pruebas Vitest OK (tokens WCAG, guards, componentes); build de producción verde.</td></tr>
<tr><td>E2E caja negra (4 niveles)</td><td>197 casos: 194 pasando, 1 skip legítimo (webhooks firmados no aplican en modo simulado), 0 errores tras las adaptaciones del arnés.</td></tr>
<tr><td>Playwright</td><td>8 recorridos desktop+mobile sobre mocks.</td></tr>
<tr><td>Nube AWS (Learner Lab)</td><td>49 recursos desplegados con Terraform; frontend 200; API <code>/api/doctors</code> respondiendo; checkout/confirm de suscripción verificado end-to-end con curl; métricas y alarmas activas en CloudWatch.</td></tr>
<tr><td>Teardown</td><td><code>terraform destroy</code> + <code>verify_teardown.py</code> audita 21 categorías; cero remanentes esperados al cierre (se ejecuta al terminar la validación).</td></tr></table>
<p><b>URLs de la validación (sessión 19-nov-2026):</b><br>
API: <code>https://v60jbsesn4.execute-api.us-east-1.amazonaws.com</code><br>
Frontend: <code>https://midoc-frontend-211125582285.s3.us-east-1.amazonaws.com/index.html</code></p>
<p class="pending"><b>Nota:</b> los endpoints del Learner Lab expiran al destruir el entorno; las URLs acreditan la validación de esta sesión, no un despliegue permanente.</p>
<h3>Reproducibilidad</h3>
<ol><li><code>npm run build --prefix frontend</code> · 2. <code>terraform -chdir=infrastructure init/plan/apply -var-file=terraform.tfvars</code> (variables en <code>terraform.tfvars.example</code>; secretos por TF_VAR o tfvars local ignorado por Git) · 3. <code>python infrastructure/publish_frontend.py</code> · 4. <code>python tests/e2e/run_e2e.py --mode live --target cloud --stripe-mode live_cloud --tier all</code> · 5. <code>terraform destroy</code> + <code>verify_teardown.py</code>.</ol>
""", """
<p class="meta">MiDoc · Pendientes y equipo · 5/5</p><h2>Cierre de fase tres</h2>
<p>El piso académico (3 flujos E2E, ≥5 servicios AWS, diagrama, métricas+alarmas+dashboard, CI/CD) está cubierto y verificado en la nube. Pendientes explícitos:</p>
<ol><li><b>Llave real de Stripe:</b> establecer <code>payment_mode="test"</code> + <code>stripe_secret_key=sk_test_…</code> (y <code>whsec_…</code> para webhooks) y re-aplicar Terraform; el producto no requiere cambios.</li>
<li><b>Video de máximo 10 minutos:</b> guion sugerido — 1) login paciente, 2) flujo búsqueda→agenda con deep link, 3) expediente/consentimiento/bitácora, 4) suscripción (modo de pago visible), 5) consulta y receta PDF, 6) dashboard CloudWatch y alarmas, 7) teardown.</li>
<li><b>Alarma <code>payment-failed</code> en ALARM:</b> se limpia al desaparecer la métrica (ventana del E2E); si se activa en uso real, investigar intentos de webhook inválidos.</li>
<li><b>Correo/push:</b> fuera del Lab (SES denegado); la bandeja in-app + EventBridge cubre el aviso transaccional.</li></ol>
<h3>Simulaciones restantes</h3>
<p>Sólo el pago sin llave (<code>simulado</code>) queda simulado y está rotulado en la interfaz («Pago simulado (sin cargo real)»). Todo lo demás opera con servicios reales: RDS, S3 firmado, DynamoDB, EventBridge, CloudWatch y (al configurar la llave) Stripe Checkout real.</p>
<table><tr><th>Integrante</th><th>Rol</th></tr><tr><td>Emmanuel Pulido Tinajero</td><td>DevOps, infraestructura y soporte frontend/backend</td></tr><tr><td>David (Dakewer)</td><td>Frontend de pacientes y profesionales</td></tr><tr><td>Gilberto Anaya</td><td>Backend, expediente y lógica de negocio</td></tr></table>
<p><b>Fuentes:</b> Reporte de fase 1 (flujos y roles), Tarea 2 (modelo de datos y sustitución de Cognito), Proyecto Integrador (fase 3: 5 métricas + 2 alarmas + dashboard, CI/CD al integrar a <code>main</code>, PDF ≤ 5 páginas). Detalle: <code>docs/EVALUACION-INTEGRAL.md</code>, <code>docs/OBSERVABILIDAD-Y-CICD.md</code>, <code>docs/CIERRE-AWS.md</code>.</p>
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
                       check=True, timeout=45, capture_output=True)
    finally:
        if profile.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            shutil.rmtree(profile, ignore_errors=True)
    if not pdf_path.is_file():
        raise RuntimeError("El navegador no generó el PDF")
    print(pdf_path)


if __name__ == "__main__":
    main()
