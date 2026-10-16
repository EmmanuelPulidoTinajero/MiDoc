"""Genera el borrador PDF de fase dos (4 páginas) usando Edge/Chrome local."""
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
"""

PAGES = ["""
<p class="meta">MiDoc · Proyecto Integrador · 16 de octubre de 2026 · 1/4</p>
<h1>Marketplace de salud</h1><h2>Avance de fase dos</h2>
<p>MiDoc centraliza el expediente bajo control del paciente y ofrece a profesionales y centros médicos búsqueda, agenda y seguimiento. La nube permite compartir los servicios entre ubicaciones y mantener la persistencia sin un servidor local permanente.</p>
<p><b>Repositorio:</b> <a href="https://github.com/EmmanuelPulidoTinajero/MiDoc">github.com/EmmanuelPulidoTinajero/MiDoc</a></p>
<p class="pending"><b>Video:</b> pendiente por indicación del usuario. Este PDF es un borrador; no acredita una entrega final completa.</p>
<table><tr><th>Flujo que se demostrará</th><th>Entrada, lógica y resultado</th><th>Evidencia disponible</th></tr>
<tr><td>1. Búsqueda y agenda</td><td>Filtrar por especialidad/ubicación, revisar perfil/disponibilidad, reservar; confirmar, cancelar o reprogramar con validación de horario.</td><td>API y navegador Edge verificados; video pendiente.</td></tr>
<tr><td>2. Expediente y consentimiento</td><td>Paciente actualiza expediente y autoriza/revoca acceso. Profesional requiere suscripción y consentimiento; documentos privados usan URLs firmadas S3.</td><td>Persistencia, acceso y ciclo de archivo sintético probados en AWS.</td></tr>
<tr><td>3. Suscripción y consulta</td><td>Suscripción demo de $20 USD/30 días; consulta de cita iniciada registra diagnóstico, tratamiento y receta en historial.</td><td>Consulta en RDS y receta desde Edge verificadas. Pago simulado.</td></tr></table>
<h3>Alcance adicional del Reporte 1</h3>
<p>Incluye historial, recetas imprimibles, inventario, promociones, mensajes y avisos internos. EventBridge genera recordatorios cada 15 minutos sin navegador; sin correo/push.</p>
<p>Los consultorios, clínicas y hospitales comparten el rol CLINICA de Tarea 2. Pacientes se registran gratis. Todas las pruebas usan datos sintéticos.</p>
""", """
<p class="meta">MiDoc · Servicios y arquitectura · 2/4</p><h2>Arquitectura implementada</h2>
<svg viewBox="0 0 740 330" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Navegador, S3, API Gateway, Lambda y servicios de persistencia">
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#246b59"/></marker></defs>
<g fill="#eef6f1" stroke="#246b59" stroke-width="2"><rect x="10" y="15" width="165" height="48" rx="7"/><rect x="245" y="15" width="210" height="48" rx="7"/><rect x="10" y="110" width="165" height="48" rx="7"/><rect x="245" y="110" width="210" height="48" rx="7"/><rect x="525" y="110" width="205" height="48" rx="7"/><rect x="10" y="245" width="165" height="48" rx="7"/><rect x="195" y="245" width="165" height="48" rx="7"/><rect x="380" y="245" width="165" height="48" rx="7"/><rect x="565" y="245" width="165" height="48" rx="7"/></g>
<g fill="none" stroke="#246b59" stroke-width="2" marker-end="url(#a)"><path d="M175 39H245"/><path d="M92 63V110"/><path d="M175 134H245"/><path d="M455 134H525"/><path d="M350 158V205H92V245"/><path d="M350 205H277V245"/><path d="M350 205H462V245"/><path d="M350 205H647V245"/></g>
<g fill="#17352b" font-family="Arial" font-size="15" text-anchor="middle"><text x="92" y="45">Navegador</text><text x="350" y="45">Angular / S3 HTTPS</text><text x="92" y="139">API Gateway</text><text x="350" y="139">Lambda / LabRole</text><text x="627" y="139">RDS PostgreSQL</text><text x="92" y="274">Secrets Manager</text><text x="277" y="274">S3 documentos</text><text x="462" y="274">DynamoDB</text><text x="647" y="274">CloudWatch Logs</text><text x="210" y="29" font-size="12">HTTPS</text><text x="63" y="92" font-size="12">HTTPS</text></g></svg>
<table><tr><th>Servicio</th><th>Uso y decisión</th></tr>
<tr><td>Lambda + API Gateway</td><td>API Python 3.12 dentro de VPC, expuesta por HTTPS con JWT y validación por rol.</td></tr>
<tr><td>RDS PostgreSQL</td><td>Fuente relacional: usuarios, citas, consentimiento, expediente, consultas/recetas y ampliaciones. Instancia privada y cifrada.</td></tr>
<tr><td>Secrets Manager</td><td>Llave JWT y credenciales RDS. Tarea 2 sustituye Cognito por autenticación propia debido a la restricción documentada de User Pools.</td></tr>
<tr><td>S3</td><td>Web estática separada de documentos privados. POST/GET firmados por 300 segundos para archivos clínicos sintéticos.</td></tr>
<tr><td>DynamoDB</td><td>Bitácora complementaria de accesos; no sustituye relaciones/transacciones de PostgreSQL.</td></tr>
<tr><td>EventBridge</td><td>Invoca Lambda cada 15 minutos para generar recordatorios y vencimientos sin navegador ni roles nuevos.</td></tr>
<tr><td>IAM / CloudWatch</td><td>Usa LabRole existente; no crea IAM roles/policies. Logs Lambda disponibles; monitoreo de negocio pendiente.</td></tr></table>
<p><b>Red:</b> Lambda usa endpoints VPC para Secrets Manager, S3 y DynamoDB; RDS acepta conexiones del security group de Lambda.</p>
""", """
<p class="meta">MiDoc · Decisiones y verificación · 3/4</p><h2>Decisiones, estado y evidencia</h2>
<table><tr><th>Componente</th><th>Estado</th></tr>
<tr><td>Frontend</td><td>Desplegado en endpoint REST S3 HTTPS con /index.html, sin CloudFront.</td></tr>
<tr><td>Backend y datos</td><td>Lambda/API Gateway, RDS, Secrets Manager, DynamoDB y documentos S3 funcionan en AWS.</td></tr>
<tr><td>Equipo local</td><td>Editor, compilación, pruebas y Terraform locales; correcciones desplegadas en AWS. Git sin commit/push.</td></tr>
<tr><td>CI</td><td>Pruebas backend, build Angular y validate Terraform. Node 24 requerido por Angular 22. CD no configurado.</td></tr></table>
<p><b>URLs de evidencia:</b><br><a href="https://4otc5sejki.execute-api.us-east-1.amazonaws.com/health">API: 4otc5sejki.execute-api.us-east-1.amazonaws.com/health</a><br><a href="https://midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html">Frontend HTTPS: midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html</a></p>
<ul><li>Verificación real: API ok, web 200; Lambda Active/Successful; RDS 16.13 available, privado y cifrado.</li>
<li>36 pruebas locales aprobadas: negocio y regresiones de adaptadores HTTP, configuración y login. Build Angular y Terraform fmt/validate aprobados.</li>
<li>Tres flujos AWS: 43 peticiones verificadas más consulta/receta desde Edge; citas, expediente, S3, inventario, promociones y mensajes.</li>
<li>Edge: seis recorridos, ocho vistas axe sin infracciones detectadas, anchos 320/390px. Falta auditoría asistiva manual.</li></ul>
<h3>Correcciones desplegadas</h3>
<p>Evitar duplicados de suscripción semilla; serializar inicialización; exigir configuración RDS y Secrets Manager en producción; TLS obligatorio en el cliente PostgreSQL; soportar DELETE/JSON inválido; alinear Node CI; mejorar carga DICOM y vistas de documentos; script seguro para publicar frontend sin recrear bucket.</p>
<p><b>Consistencia:</b> negocio y avisos comparten transacción; regresiones comprueban rollback ante fallo. Falta idempotencia del cliente ante pérdida de respuesta. EventBridge genera recordatorios cada 15 minutos y su ejecución automática se verificó en CloudWatch.</p>
""", """
<p class="meta">MiDoc · Pendientes y equipo · 4/4</p><h2>Cierre de fase dos</h2>
<p>Los componentes centrales están en AWS. No se afirma un porcentaje funcional exacto sin una matriz de aceptación y demo. Se conservan como pendientes explícitos:</p>
<ol><li>Video parcial de máximo 10 minutos, pendiente por indicación del usuario.</li>
<li>Correo/push y pagos reales no implementados; mantener simulaciones explícitas.</li>
<li>Revisar/publicar cambios locales y alinear el código mostrado en GitHub con el despliegue.</li>
<li>Formalizar migraciones PostgreSQL, idempotencia del cliente y pruebas de recuperación/concurrencia.</li>
<li>Completar revisión manual con lector de pantalla, foco y zoom; axe no certifica conformidad WCAG.</li></ol>
<h3>Permisos: evidencia acotada</h3>
<p>Se denegaron ListDistributions/GetDistribution de CloudFront y GetAccount/ListEmailIdentities de SES. Esto no prueba que crear una distribución o enviar correo estén prohibidos. SNS sólo mostró RedshiftSNS y no se reutilizó. Correo no implementado; scheduler EventBridge desplegado sin roles nuevos.</p>
<h3>Simulaciones y próximos hitos</h3>
<p>La suscripción valida una tarjeta de prueba y asigna vigencia; no cobra. Las promociones no aplican cargos automáticamente. Recordatorios automáticos en AWS; la bandeja se consulta al abrir MiDoc. CI/CD completo se prepara para la sesión del 12 de noviembre; cinco métricas, dos alertas y dashboard quedan para la fase final del Proyecto Integrador.</p>
<table><tr><th>Integrante</th><th>Rol del Reporte 1</th></tr><tr><td>Emmanuel Pulido Tinajero</td><td>DevOps, infraestructura y soporte frontend/backend</td></tr><tr><td>David (Dakewer)</td><td>Frontend de pacientes y profesionales</td></tr><tr><td>Gilberto Anaya</td><td>Backend, expediente y lógica de negocio</td></tr></table>
<p>El historial Git contiene participación de los tres integrantes. Los cambios nuevos siguen pendientes de commit/revisión.</p>
<p><b>Fuentes de alcance:</b> Reporte de fase 1 (pp. 1–2), Tarea 2 (pp. 1–6), Proyecto Integrador (p. 4 para fase dos y pp. 5–6 para hitos posteriores). Ver <code>docs/REVISION-INTEGRAL.md</code> para hallazgos y evidencia detallada.</p>
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
    html_path = ROOT / "ENTREGA-FASE2.html"
    pdf_path = ROOT / "ENTREGA-FASE2.pdf"
    html_path.write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>MiDoc fase 2</title>'
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
