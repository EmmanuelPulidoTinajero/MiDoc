# Monitoreo del Proyecto Integrador: cinco métricas, dos alarmas y un dashboard.
#
# Las cinco métricas las emite la Lambda en formato EMF (backend/src/metricas.py) sobre
# stdout, así que CloudWatch Logs las crea sin PutMetricData y sin permisos IAM extra
# sobre el rol existente. Terraform sólo declara las alarmas y el dashboard.
#
# Para añadir notificaciones cuando una alarma se dispare basta crear un topic SNS y
# asignarlo en alarm_actions; el Laboratorio niega SES, no la creación de topics propios.

variable "enable_monitoring" {
  type        = bool
  default     = true
  description = "Create the CloudWatch alarms and dashboard. Disable only if the learner lab denies cloudwatch:PutMetricAlarm or cloudwatch:PutDashboard."
}

locals {
  monitoreo_servicio = { Service = "midoc-api" }
}

resource "aws_cloudwatch_metric_alarm" "errores_servidor" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-api-errores-5xx"
  alarm_description   = "Más de 5 respuestas 5xx en 5 minutos: la API está fallando para quien la usa."
  namespace           = "MiDoc"
  metric_name         = "ServerErrors"
  dimensions          = local.monitoreo_servicio
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "latencia_p95" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-api-latencia-p95"
  alarm_description   = "El p95 de latencia supera 3 s en dos periodos consecutivos de 5 minutos."
  namespace           = "MiDoc"
  metric_name         = "RequestLatencyMs"
  dimensions          = local.monitoreo_servicio
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = 3000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_dashboard" "estado" {
  count = var.enable_monitoring ? 1 : 0

  dashboard_name = "${var.project_name}-estado"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "alarm"
        x      = 0
        y      = 0
        width  = 24
        height = 3
        properties = {
          title = "Alarmas de MiDoc"
          alarms = [
            aws_cloudwatch_metric_alarm.errores_servidor[0].arn,
            aws_cloudwatch_metric_alarm.latencia_p95[0].arn,
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 3
        width  = 12
        height = 6
        properties = {
          title  = "Uso del producto: citas, consultas e inicios de sesión fallidos"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["MiDoc", "AppointmentsCreated", "Service", "midoc-api", { label = "Citas agendadas" }],
            ["MiDoc", "ConsultationsRegistered", "Service", "midoc-api", { label = "Consultas registradas" }],
            ["MiDoc", "LoginFailures", "Service", "midoc-api", { label = "Inicios de sesión fallidos" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 3
        width  = 6
        height = 6
        properties = {
          title  = "Latencia de la API (ms)"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["MiDoc", "RequestLatencyMs", "Service", "midoc-api", { stat = "p95", label = "p95" }],
            ["MiDoc", "RequestLatencyMs", "Service", "midoc-api", { stat = "Average", label = "Promedio" }],
          ]
          annotations = {
            horizontal = [
              {
                label = "Umbral de la alarma (3000 ms)"
                value = 3000
              },
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 18
        y      = 3
        width  = 6
        height = 6
        properties = {
          title  = "Errores 5xx"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["MiDoc", "ServerErrors", "Service", "midoc-api", { label = "Respuestas 5xx" }],
          ]
          annotations = {
            horizontal = [
              {
                label = "Umbral de la alarma (5 por 5 min)"
                value = 5
              },
            ]
          }
        }
      },
    ]
  })
}

output "dashboard_name" {
  value = var.enable_monitoring ? aws_cloudwatch_dashboard.estado[0].dashboard_name : ""
}

output "alarmas" {
  value = var.enable_monitoring ? [
    aws_cloudwatch_metric_alarm.errores_servidor[0].alarm_name,
    aws_cloudwatch_metric_alarm.latencia_p95[0].alarm_name,
  ] : []
}
