"""Contract fixtures used ONLY when `--mode self-test` is explicitly selected.

NEVER imported or used when `--mode live` is active.
"""
from __future__ import annotations

from typing import Any


SELF_TEST_VARIABLES_TF = """
variable "payment_mode" {
  type    = string
  default = "test"
  validation {
    condition     = contains(["test", "live"], var.payment_mode)
    error_message = "payment_mode must be test or live."
  }
}

variable "stripe_secret_key" {
  type      = string
  sensitive = true
  default   = ""
  validation {
    condition = (
      var.stripe_secret_key == "" ||
      (var.payment_mode == "test" && startswith(var.stripe_secret_key, "sk_test_")) ||
      (var.payment_mode == "live" && startswith(var.stripe_secret_key, "sk_live_"))
    )
    error_message = "stripe_secret_key prefix must match payment_mode."
  }
}

variable "stripe_webhook_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "stripe_price_amount_cents" {
  type    = number
  default = 2000
}
"""

SELF_TEST_MAIN_TF_STRIPE_FRAGMENT = """
resource "aws_secretsmanager_secret" "stripe" {
  name                    = "${var.project_name}/stripe"
  recovery_window_in_days = 0
}
"""

SELF_TEST_MONITORING_TF = """
resource "aws_sns_topic" "alertas" {
  name = "${var.project_name}-alertas"
}

resource "aws_cloudwatch_log_group" "lambda_api" {
  name              = "/aws/lambda/${var.project_name}-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "apigw_access" {
  name              = "/aws/apigateway/${var.project_name}-http"
  retention_in_days = 14
}

resource "aws_cloudwatch_metric_alarm" "errores_servidor" {
  alarm_name          = "${var.project_name}-api-errores-5xx"
  namespace           = "MiDoc"
  metric_name         = "ServerErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
}

resource "aws_cloudwatch_metric_alarm" "latencia_p95" {
  alarm_name          = "${var.project_name}-api-latencia-p95"
  namespace           = "MiDoc"
  metric_name         = "RequestLatencyMs"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = 3000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
}

resource "aws_cloudwatch_dashboard" "estado" {
  dashboard_name = "${var.project_name}-estado"
}

resource "aws_cloudwatch_query_definition" "errores_recientes" {
  name = "${var.project_name}/errores-recientes"
}
"""

SELF_TEST_CD_YML = """name: MiDoc CD
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify AWS credentials
        run: aws sts get-caller-identity
      - name: Terraform apply
        run: terraform -chdir=infrastructure apply -auto-approve
      - name: Publish frontend
        run: python infrastructure/publish_frontend.py
"""

SELF_TEST_DOCS: dict[str, str] = {
    "docs/EVALUACION-INTEGRAL.md": (
        "# Evaluacion Integral MiDoc\n\n"
        "Matriz de trazabilidad R1 y R2: REQ-F1-01, REQ-T2-01, REQ-F2-01, REQ-F3-01.\n"
        "Mejoras documentadas dentro del alcance: Design System, Stripe Checkout, CloudWatch EMF.\n"
    ),
    "docs/PAGOS-STRIPE.md": (
        "# Pagos con Stripe en MiDoc\n\n"
        "Comparativa PayPal vs Stripe: se eligio Stripe por Checkout Sessions y HMAC webhooks.\n"
        "Cambio entre modo test y modo live pre-despliegue con payment_mode, sk_test_ y sk_live_.\n"
        "Nunca comitear claves sk_live_ en git; usar terraform.tfvars, Secrets Manager o GitHub Secrets.\n"
    ),
    "docs/OBSERVABILIDAD-Y-CICD.md": (
        "# Observabilidad CloudWatch y CI/CD\n\n"
        "Namespace MiDoc, Service=midoc-api, RequestLatencyMs, ServerErrors, AppointmentsCreated, "
        "ConsultationsRegistered, LoginFailures, PaymentCheckoutCreated, PaymentSucceeded, PaymentFailed.\n"
        "Flujos en .github/workflows/ci.yml y .github/workflows/cd.yml.\n"
    ),
    "docs/CIERRE-AWS.md": (
        "# Cierre de Despliegue y Teardown AWS\n\n"
        "Ciclo completo terraform apply, validacion cloud y terraform destroy con verify_teardown.py.\n"
        "Ver [DEPLOYMENT.md](DEPLOYMENT.md) y [API.md](API.md).\n"
    ),
    "docs/API.md": (
        "# API MiDoc\n\n"
        "Suscripciones Stripe: POST /api/subscriptions/checkout, POST /api/subscriptions/confirm, "
        "POST /api/webhooks/stripe, GET /api/subscriptions.\n"
        "Cuenta y bitacora: PUT /api/me, POST /api/auth/refresh, GET /api/records/access-log.\n"
    ),
    "README.md": (
        "# MiDoc\n\n"
        "Plataforma medica con pagos reales mediante Stripe Checkout (/api/subscriptions/checkout, "
        "/api/subscriptions/confirm, /api/webhooks/stripe).\n"
        "Guias: [docs/API.md](docs/API.md), [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).\n"
    ),
}

SELF_TEST_DS_PRIMITIVES = [
    "ds-button",
    "ds-card",
    "ds-badge",
    "ds-field",
    "ds-modal",
    "ds-empty-state",
    "ds-skeleton",
    "ds-alert",
    "ds-page-header",
]

SELF_TEST_HTML_SHELL = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MiDoc — Self-Test Contract Shell</title>
  <style>
    :root {
      --color-canvas: #f4f2ec;
      --color-surface: #ffffff;
      --color-text: #17352b;
      --color-primary: #246b59;
      --color-danger: #a83a32;
      --color-accent: #8a4b00;
      --color-focus: #17352b;
      --color-border-strong: #7d8f86;
      --font-display: ui-serif, Georgia, "Times New Roman", serif;
      --font-ui: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
      --font-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
      --control-height: 2.5rem;
      --motion-fast: 120ms;
      --motion-base: 200ms;
      --motion-slow: 320ms;
    }
    @media (prefers-reduced-motion: reduce) {
      :root { --motion-fast: 1ms; --motion-base: 1ms; --motion-slow: 1ms; }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font-ui);
      background: var(--color-canvas);
      color: var(--color-text);
      overflow-x: hidden;
    }
    .skip-link { position: absolute; left: 0.5rem; top: -4rem; background: var(--color-surface); padding: 0.5rem; }
    .skip-link:focus { top: 0.5rem; outline: 2px solid var(--color-focus); }
    main { max-width: 72rem; margin: 0 auto; padding: 1rem; }
    nav { display: flex; flex-wrap: wrap; gap: 0.5rem; padding: 0.75rem 1rem; background: var(--color-surface); border-bottom: 1px solid var(--color-border-strong); }
    .ds-button { min-height: var(--control-height); padding: 0.5rem 1rem; background: var(--color-primary); color: #fff; border: 0; border-radius: 0.5rem; cursor: pointer; }
    .ds-card { background: var(--color-surface); padding: 1rem; border-radius: 0.75rem; margin-top: 1rem; }
    .ds-badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 999px; background: #d5efe2; color: var(--color-text); }
    .ds-empty-state { padding: 1.5rem; border: 1px dashed var(--color-border-strong); border-radius: 0.75rem; }
    .table-scroll { overflow-x: auto; max-width: 100%; }
  </style>
</head>
<body>
  <a class="skip-link" href="#contenido-principal">Saltar al contenido principal</a>
  <nav aria-label="Navegación principal">
    <a href="#/buscar">Buscar</a>
    <a href="#/acceso">Acceso</a>
    <a href="#/citas">Mis citas</a>
    <a href="#/expediente">Mi expediente</a>
    <a href="#/mensajes">Mensajes</a>
    <a href="#/panel">Panel</a>
    <a href="#/panel/suscripcion">Suscripción</a>
  </nav>
  <main id="contenido-principal">
    <header class="ds-page-header">
      <h1>Tu salud, organizada en un solo lugar.</h1>
    </header>
    <section class="ds-card" id="route-view">
      <div role="tablist" aria-label="Secciones">
        <button role="tab" aria-selected="true" id="tab-resumen">Resumen</button>
        <button role="tab" aria-selected="false" id="tab-detalle">Detalle</button>
      </div>
      <div role="tabpanel" aria-labelledby="tab-resumen" id="panel-content">
        <p id="route-label">Ruta actual: #/buscar</p>
        <span class="ds-badge" id="status-badge">Pendiente</span>
        <div class="ds-empty-state" id="empty-state-box">
          <p>Aún no hay elementos.</p>
          <button class="ds-button" id="btn-open-confirm" type="button">Cancelar cita</button>
        </div>
      </div>
    </section>
  </main>
  <dialog id="confirm-dialog" aria-labelledby="confirm-dialog-title">
    <h2 id="confirm-dialog-title">Confirmar acción</h2>
    <p id="confirm-dialog-msg">¿Deseas continuar?</p>
    <button class="ds-button" id="dialog-confirm-yes" type="button">Confirmar</button>
    <button class="ds-button" id="dialog-confirm-no" type="button">Cerrar</button>
  </dialog>
  <script>
    (function () {
      const protectedRoutes = ['#/expediente', '#/panel', '#/panel/suscripcion', '#/citas', '#/mensajes'];
      function renderRoute() {
        let hash = window.location.hash || '#/buscar';
        const loggedIn = Boolean(window.localStorage.getItem('midoc_token'));
        if (!loggedIn && protectedRoutes.some(r => hash.startsWith(r))) {
          window.location.hash = '#/acceso';
          hash = '#/acceso';
        }
        const label = document.getElementById('route-label');
        if (label) label.textContent = 'Ruta actual: ' + hash;
      }
      window.addEventListener('hashchange', renderRoute);
      document.getElementById('btn-open-confirm').addEventListener('click', function () {
        const dlg = document.getElementById('confirm-dialog');
        if (dlg && typeof dlg.showModal === 'function') dlg.showModal();
      });
      document.getElementById('dialog-confirm-no').addEventListener('click', function () {
        const dlg = document.getElementById('confirm-dialog');
        if (dlg && typeof dlg.close === 'function') dlg.close();
      });
      document.getElementById('dialog-confirm-yes').addEventListener('click', function () {
        const dlg = document.getElementById('confirm-dialog');
        const badge = document.getElementById('status-badge');
        if (badge) badge.textContent = 'Cancelada';
        if (dlg && typeof dlg.close === 'function') dlg.close();
      });
      renderRoute();
    })();
  </script>
</body>
</html>
"""

SELF_TEST_REQUIRED_EMF_METRICS = [
    "RequestLatencyMs",
    "ServerErrors",
    "AppointmentsCreated",
    "ConsultationsRegistered",
    "LoginFailures",
    "RemindersJobRuns",
    "RemindersJobErrors",
    "PaymentCheckoutCreated",
    "PaymentSucceeded",
    "PaymentFailed",
    "DocumentOpsErrors",
    "DynamoAuditErrors",
]


def get_self_test_config_json(api_url: str, payment_mode: str = "test") -> dict[str, Any]:
    return {"apiUrl": api_url, "paymentMode": payment_mode}
