# Una regla programada puede invocar Lambda con una política del recurso.
# No crea roles IAM ni modifica LabRole.
resource "aws_cloudwatch_event_rule" "reminders" {
  name                = "${var.project_name}-reminders"
  description         = "Genera avisos de citas y vencimientos aunque el navegador esté cerrado"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_lambda_permission" "reminders" {
  statement_id  = "AllowMiDocReminders"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reminders.arn
}

resource "aws_cloudwatch_event_target" "reminders" {
  rule       = aws_cloudwatch_event_rule.reminders.name
  target_id  = "midoc-api-reminders"
  arn        = aws_lambda_function.api.arn
  input      = jsonencode({ source = "midoc.reminders" })
  depends_on = [aws_lambda_permission.reminders]
}
