"""Recorrido de interfaz real con Edge/Playwright y auditoría automatizada axe.

Instalar playwright aparte; no es dependencia del runtime Lambda.
"""
import io
import json
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(tempfile.gettempdir()) / "midoc-playwright"))
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
URL = "https://midoc-frontend-647018795197.s3.us-east-1.amazonaws.com/index.html"


def main():
    # Código de axe del paquete oficial npm, sólo para esta prueba.
    with urlopen("https://registry.npmjs.org/axe-core/-/axe-core-4.10.3.tgz", timeout=30) as response:
        with tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz") as archive:
            axe = archive.extractfile("package/axe.min.js").read().decode()
    audits, errors, checks = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="es-MX")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_default_timeout(30000)

        def audit(name):
            page.add_script_tag(content=axe)
            result = page.evaluate("""async () => {
              const r = await axe.run(document, {runOnly: {type:'tag', values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
              return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,
                nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),passes:r.passes.length};
            }""")
            audits.append({"view": name, **result})

        page.goto(URL, wait_until="networkidle")
        expect(page.get_by_role("heading", name="Tu salud, organizada en un solo lugar.")).to_be_visible()
        assert page.evaluate("window.isSecureContext")
        page.keyboard.press("Tab")
        expect(page.get_by_role("link", name="Saltar al contenido principal")).to_be_focused()
        audit("buscar-desktop")
        page.get_by_role("button", name="Iniciar sesión o crear cuenta").click()
        page.get_by_role("button", name="Crear cuenta", exact=True).click()
        page.get_by_label("Nombre completo").fill("E2E DEMO navegador")
        page.get_by_label("Correo", exact=True).fill(f"e2e-browser-{uuid.uuid4().hex[:8]}@example.invalid")
        page.get_by_label("Contraseña (8+ con letras y números)").fill("DemoBrowser2026!Prueba")
        audit("registro")
        page.locator("form").get_by_role("button", name="Crear cuenta", exact=True).click()
        expect(page.get_by_role("button", name="Mis citas", exact=True)).to_be_visible()
        checks.append("Registro de paciente desde interfaz")
        page.get_by_role("button", name="Buscar", exact=True).click()
        demo = page.locator("article").filter(has=page.get_by_role("heading", name="Dra. Ana López"))
        demo.get_by_role("button", name="Ver perfil y agendar").click()
        tomorrow = (datetime.now(timezone(timedelta(hours=-6))) + timedelta(days=3)).date().isoformat()
        page.get_by_label("Fecha", exact=True).fill(tomorrow)
        page.get_by_label("Fecha", exact=True).dispatch_event("change")
        slot = page.locator(".slots button").first
        expect(slot).to_be_visible()
        slot.click()
        expect(page.locator(".notice").last).to_contain_text("Cita")
        checks.append("Búsqueda, perfil y cita desde interfaz")
        page.get_by_role("button", name="Mis citas", exact=True).click()
        expect(page.locator("tbody tr")).to_have_count(1)
        audit("mis-citas")
        page.get_by_role("button", name="Reprogramar", exact=True).click()
        page.get_by_label("Nueva fecha", exact=True).fill(tomorrow)
        page.get_by_role("button", name="Consultar horarios", exact=True).click()
        expect(page.get_by_label("Horario disponible")).to_be_visible()
        page.get_by_label("Horario disponible").select_option(index=1)
        page.get_by_role("button", name="Confirmar nueva fecha", exact=True).click()
        expect(page.locator(".notice")).to_contain_text("La cita se reprogramó")
        checks.append("Reprogramación con confirmación visible tras cerrar formulario")
        page.on("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Cancelar", exact=True).click()
        expect(page.locator(".badge")).to_have_text("CANCELADA")
        checks.append("Cancelación y actualización de estado")
        page.get_by_role("button", name="Mi expediente", exact=True).click()
        page.get_by_label("Antecedentes y notas").fill("E2E DEMO navegador, sin datos clínicos reales")
        with page.expect_response(lambda response: response.url.endswith('/api/records') and response.request.method == 'PUT') as saved:
            page.get_by_role("button", name="Guardar expediente").click()
        assert saved.value.json()['data']['notes'] == 'E2E DEMO navegador, sin datos clínicos reales'
        expect(page.locator(".notice").first).to_contain_text("Expediente actualizado")
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="Mi expediente", exact=True).click()
        expect(page.get_by_label("Antecedentes y notas")).to_have_value('E2E DEMO navegador, sin datos clínicos reales')
        select = page.get_by_label("Dar acceso a")
        option = select.locator("option").filter(has_text="Dra. Ana López")
        select.select_option(option.get_attribute("value"))
        page.get_by_role("button", name="Otorgar acceso", exact=True).click()
        expect(page.get_by_role("button", name="Revocar", exact=True)).to_be_visible()
        page.get_by_role("button", name="Revocar", exact=True).click()
        expect(page.get_by_role("button", name="Otorgar", exact=True)).to_be_visible()
        page.get_by_label("Agregar archivo clínico").set_input_files({"name":"browser-demo.dcm",
            "mimeType":"application/octet-stream", "buffer":b"E2E DEMO DICOM synthetic"})
        expect(page.get_by_role("link", name="browser-demo.dcm").first).to_be_visible()
        page.get_by_role("button", name="Eliminar", exact=True).click()
        expect(page.get_by_role("link", name="browser-demo.dcm")).to_have_count(0)
        checks.append("Expediente, otorgar/revocar y carga/eliminación DICOM por HTTPS con CORS")
        audit("expediente-desktop")
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e =>
          e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('.table-scroll'))
          .map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,
          right:e.getBoundingClientRect().right,text:e.textContent.slice(0,80)})).slice(0,15)""")
        if overflow:
            print(json.dumps({"overflow": overflow}, ensure_ascii=True), flush=True)
        assert not overflow, "Overflow móvil"
        audit("expediente-mobile")
        page.set_viewport_size({"width": 320, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Overflow a 320px"
        audit("expediente-320px")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(ROOT / "docs/frontend-mobile.png"), full_page=True)
        page.get_by_role("button", name="Mensajes", exact=True).click()
        audit("mensajes-mobile")
        page.get_by_role("button", name="Cerrar sesión", exact=True).click()
        page.get_by_role("button", name="Iniciar sesión o crear cuenta").click()
        page.get_by_label("Correo", exact=True).fill("doctor@midoc.local")
        page.get_by_label("Contraseña", exact=True).fill("doctor-demo")
        page.get_by_role("button", name="Entrar", exact=True).click()
        page.get_by_role("button", name="Mi panel", exact=True).click()
        expect(page.get_by_role("heading", name="Suscripción", exact=True)).to_be_visible()
        audit("panel-doctor-mobile")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Overflow panel móvil"
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.screenshot(path=str(ROOT / "docs/frontend-profesional.png"), full_page=True)
        checks.append("Sesión profesional, panel y diseño móvil")
        browser.close()
    report = {"testedAt": datetime.now(timezone.utc).isoformat(), "url": URL,
              "browser": "Microsoft Edge headless / Playwright", "checks": checks,
              "pageErrors": errors, "accessibility": audits,
              "limitations": "axe y teclado básico no sustituyen lector de pantalla ni auditoría WCAG manual completa"}
    (ROOT / "docs/evidencia-browser.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    serious = [v for a in audits for v in a["violations"] if v["impact"] in ("serious", "critical")]
    assert not errors, errors
    assert not serious, serious
    print(f"PASS: {len(checks)} recorridos, {len(audits)} vistas auditadas, sin errores JS ni violaciones axe graves.")


if __name__ == "__main__":
    main()
