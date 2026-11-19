# Observabilidad en CloudWatch: métricas EMF (MiDoc), métricas AWS (Lambda, API Gateway, RDS),
# notificaciones vía SNS, dashboard unificado y consultas de Logs Insights.
#
# Las métricas de aplicación las emite la Lambda en formato EMF (backend/src/metricas.py) sobre
# stdout, así que CloudWatch Logs las crea sin PutMetricData y sin permisos IAM extra sobre LabRole.

variable "enable_monitoring" {
  type        = bool
  default     = true
  description = "Create the CloudWatch alarms, SNS topic, dashboard, and Logs Insights queries. Disable only if the learner lab denies cloudwatch:PutMetricAlarm or cloudwatch:PutDashboard."
}

locals {
  monitoreo_servicio = { Service = "midoc-api" }
}

resource "aws_sns_topic" "alerts" {
  count = var.enable_monitoring ? 1 : 0
  name  = "${var.project_name}-alerts"

  tags = {
    Name    = "${var.project_name}-alerts"
    Project = var.project_name
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.enable_monitoring && trimspace(var.alert_email) != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = trimspace(var.alert_email)
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
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
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
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "reminders_errors" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-reminders-errors"
  alarm_description   = "Errores en la ejecución programada de recordatorios (EventBridge)."
  namespace           = "MiDoc"
  metric_name         = "RemindersJobErrors"
  dimensions          = local.monitoreo_servicio
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "payment_failed" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-payment-failed"
  alarm_description   = "Más de 3 fallos en pagos Stripe en 5 minutos."
  namespace           = "MiDoc"
  metric_name         = "PaymentFailed"
  dimensions          = local.monitoreo_servicio
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-lambda-errors"
  alarm_description   = "Errores de ejecución o timeout en la función Lambda de MiDoc."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-lambda-throttles"
  alarm_description   = "Invocaciones limitadas (throttled) en la función Lambda de MiDoc."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "apigw_5xx" {
  count = var.enable_monitoring ? 1 : 0

  alarm_name          = "${var.project_name}-apigw-5xx"
  alarm_description   = "Más de 5 respuestas 5xx en API Gateway HTTP v2 en 5 minutos."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.http.id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  count = var.enable_monitoring && var.enable_rds ? 1 : 0

  alarm_name          = "${var.project_name}-rds-cpu"
  alarm_description   = "Uso promedio de CPU en RDS PostgreSQL supera el 80% durante 10 minutos."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres[0].identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  count = var.enable_monitoring && var.enable_rds ? 1 : 0

  alarm_name          = "${var.project_name}-rds-storage"
  alarm_description   = "Espacio libre en RDS PostgreSQL menor a 2 GiB."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres[0].identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2147483648
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  count = var.enable_monitoring && var.enable_rds ? 1 : 0

  alarm_name          = "${var.project_name}-rds-connections"
  alarm_description   = "Conexiones activas a RDS PostgreSQL superan 45 durante 10 minutos."
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres[0].identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 45
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]
}

resource "aws_cloudwatch_dashboard" "estado" {
  count = var.enable_monitoring ? 1 : 0

  dashboard_name = "${var.project_name}-estado"
  dashboard_body = jsonencode({
    widgets = concat(
      [
        {
          type   = "alarm"
          x      = 0
          y      = 0
          width  = 24
          height = 3
          properties = {
            title = "Alarmas de MiDoc (Aplicación e Infraestructura)"
            alarms = concat(
              [
                aws_cloudwatch_metric_alarm.errores_servidor[0].arn,
                aws_cloudwatch_metric_alarm.latencia_p95[0].arn,
                aws_cloudwatch_metric_alarm.reminders_errors[0].arn,
                aws_cloudwatch_metric_alarm.payment_failed[0].arn,
                aws_cloudwatch_metric_alarm.lambda_errors[0].arn,
                aws_cloudwatch_metric_alarm.lambda_throttles[0].arn,
                aws_cloudwatch_metric_alarm.apigw_5xx[0].arn,
              ],
              var.enable_rds ? [
                aws_cloudwatch_metric_alarm.rds_cpu[0].arn,
                aws_cloudwatch_metric_alarm.rds_storage[0].arn,
                aws_cloudwatch_metric_alarm.rds_connections[0].arn,
              ] : []
            )
          }
        },
        {
          type   = "metric"
          x      = 0
          y      = 3
          width  = 8
          height = 6
          properties = {
            title  = "Uso clínico: citas, consultas e inicios fallidos"
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
          x      = 8
          y      = 3
          width  = 8
          height = 6
          properties = {
            title  = "Pagos Stripe, recordatorios y resiliencia"
            region = var.aws_region
            view   = "timeSeries"
            stat   = "Sum"
            period = 300
            metrics = [
              ["MiDoc", "PaymentCheckoutCreated", "Service", "midoc-api", { label = "Checkouts Stripe" }],
              ["MiDoc", "PaymentSucceeded", "Service", "midoc-api", { label = "Pagos confirmados" }],
              ["MiDoc", "PaymentFailed", "Service", "midoc-api", { label = "Pagos fallidos" }],
              ["MiDoc", "RemindersJobRuns", "Service", "midoc-api", { label = "Ejecuciones recordatorios" }],
              ["MiDoc", "RemindersJobErrors", "Service", "midoc-api", { label = "Errores recordatorios" }],
              ["MiDoc", "DocumentOpsErrors", "Service", "midoc-api", { label = "Errores documentos S3" }],
              ["MiDoc", "DynamoAuditErrors", "Service", "midoc-api", { label = "Errores bitácora DynamoDB" }],
            ]
          }
        },
        {
          type   = "metric"
          x      = 16
          y      = 3
          width  = 8
          height = 6
          properties = {
            title  = "Latencia API y API Gateway (ms)"
            region = var.aws_region
            view   = "timeSeries"
            period = 300
            metrics = [
              ["MiDoc", "RequestLatencyMs", "Service", "midoc-api", { stat = "p95", label = "API p95" }],
              ["MiDoc", "RequestLatencyMs", "Service", "midoc-api", { stat = "Average", label = "API Promedio" }],
              ["AWS/ApiGateway", "Latency", "ApiId", aws_apigatewayv2_api.http.id, { stat = "p95", label = "APIGW Latency p95" }],
              ["AWS/ApiGateway", "IntegrationLatency", "ApiId", aws_apigatewayv2_api.http.id, { stat = "Average", label = "Integration Latency Avg" }],
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
          x      = 0
          y      = 9
          width  = 12
          height = 6
          properties = {
            title  = "Errores y tráfico: MiDoc, Lambda y API Gateway"
            region = var.aws_region
            view   = "timeSeries"
            stat   = "Sum"
            period = 300
            metrics = [
              ["MiDoc", "ServerErrors", "Service", "midoc-api", { label = "MiDoc 5xx" }],
              ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.api.function_name, { label = "Lambda Invocations" }],
              ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.api.function_name, { label = "Lambda Errors" }],
              ["AWS/Lambda", "Throttles", "FunctionName", aws_lambda_function.api.function_name, { label = "Lambda Throttles" }],
              ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.api.function_name, { stat = "Average", label = "Lambda Duration Avg (ms)" }],
              ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.http.id, { label = "APIGW Requests" }],
              ["AWS/ApiGateway", "4xx", "ApiId", aws_apigatewayv2_api.http.id, { label = "APIGW 4xx" }],
              ["AWS/ApiGateway", "5xx", "ApiId", aws_apigatewayv2_api.http.id, { label = "APIGW 5xx" }],
            ]
            annotations = {
              horizontal = [
                {
                  label = "Umbral 5xx (5 por 5 min)"
                  value = 5
                },
              ]
            }
          }
        },
      ],
      var.enable_rds ? [
        {
          type   = "metric"
          x      = 12
          y      = 9
          width  = 12
          height = 6
          properties = {
            title  = "Salud de RDS PostgreSQL"
            region = var.aws_region
            view   = "timeSeries"
            stat   = "Average"
            period = 300
            metrics = [
              ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.postgres[0].identifier, { label = "CPU (%)" }],
              ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.postgres[0].identifier, { label = "Conexiones" }],
              ["AWS/RDS", "FreeStorageSpace", "DBInstanceIdentifier", aws_db_instance.postgres[0].identifier, { label = "Almacenamiento libre (Bytes)" }],
            ]
          }
        },
      ] : [],
      [
        {
          type   = "log"
          x      = 0
          y      = 15
          width  = 24
          height = 6
          properties = {
            title  = "Logs recientes de Lambda y API Gateway"
            region = var.aws_region
            view   = "table"
            query  = "SOURCE '${aws_cloudwatch_log_group.lambda_api.name}' | SOURCE '${aws_cloudwatch_log_group.apigw_http.name}' | fields @timestamp, @logStream, @message | sort @timestamp desc | limit 25"
          }
        },
      ]
    )
  })
}

resource "aws_cloudwatch_query_definition" "api_errors" {
  count = var.enable_monitoring ? 1 : 0

  name            = "${var.project_name}/api-errors"
  log_group_names = [aws_cloudwatch_log_group.lambda_api.name]
  query_string    = <<-EOT
    fields @timestamp, @message
    | filter @message like /ERROR|Traceback|"statusCode":\s*5|"status":\s*5/
    | sort @timestamp desc
    | limit 50
  EOT
}

resource "aws_cloudwatch_query_definition" "slow_requests" {
  count = var.enable_monitoring ? 1 : 0

  name            = "${var.project_name}/slow-requests"
  log_group_names = [aws_cloudwatch_log_group.lambda_api.name, aws_cloudwatch_log_group.apigw_http.name]
  query_string    = <<-EOT
    fields @timestamp, @logStream, RequestLatencyMs, responseLatency, path, status, @message
    | filter RequestLatencyMs > 1000 or responseLatency > 1000
    | sort @timestamp desc
    | limit 50
  EOT
}

resource "aws_cloudwatch_query_definition" "payments_and_reminders" {
  count = var.enable_monitoring ? 1 : 0

  name            = "${var.project_name}/payments-and-reminders"
  log_group_names = [aws_cloudwatch_log_group.lambda_api.name]
  query_string    = <<-EOT
    fields @timestamp, @message
    | filter @message like /stripe|payment|checkout|reminders/i
    | sort @timestamp desc
    | limit 50
  EOT
}

resource "aws_cloudwatch_query_definition" "apigw_5xx_access" {
  count = var.enable_monitoring ? 1 : 0

  name            = "${var.project_name}/apigw-5xx-access"
  log_group_names = [aws_cloudwatch_log_group.apigw_http.name]
  query_string    = <<-EOT
    fields @timestamp, httpMethod, path, status, integrationStatus, responseLatency, integrationErrorMessage
    | filter status >= 400
    | sort @timestamp desc
    | limit 50
  EOT
}

output "dashboard_name" {
  value = var.enable_monitoring ? aws_cloudwatch_dashboard.estado[0].dashboard_name : ""
}

output "alerts_topic_arn" {
  value = var.enable_monitoring ? aws_sns_topic.alerts[0].arn : ""
}

output "alarmas" {
  value = var.enable_monitoring ? concat(
    [
      aws_cloudwatch_metric_alarm.errores_servidor[0].alarm_name,
      aws_cloudwatch_metric_alarm.latencia_p95[0].alarm_name,
      aws_cloudwatch_metric_alarm.reminders_errors[0].alarm_name,
      aws_cloudwatch_metric_alarm.payment_failed[0].alarm_name,
      aws_cloudwatch_metric_alarm.lambda_errors[0].alarm_name,
      aws_cloudwatch_metric_alarm.lambda_throttles[0].alarm_name,
      aws_cloudwatch_metric_alarm.apigw_5xx[0].alarm_name,
    ],
    var.enable_rds ? [
      aws_cloudwatch_metric_alarm.rds_cpu[0].alarm_name,
      aws_cloudwatch_metric_alarm.rds_storage[0].alarm_name,
      aws_cloudwatch_metric_alarm.rds_connections[0].alarm_name,
    ] : []
  ) : []
}

output "log_groups" {
  value = {
    lambda_api = aws_cloudwatch_log_group.lambda_api.name
    apigw_http = aws_cloudwatch_log_group.apigw_http.name
  }
}
