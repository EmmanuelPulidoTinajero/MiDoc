data "archive_file" "backend" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/.lambda-build"
  output_path = "${path.module}/../backend/lambda-package.zip"
  depends_on  = [terraform_data.lambda_dependencies]
}

resource "terraform_data" "lambda_dependencies" {
  triggers_replace = concat(
    [
      filemd5("${path.module}/../backend/requirements.txt"),
      filemd5("${path.module}/build_lambda.py"),
      filemd5("${path.module}/../backend/src/schema.sql"),
    ],
    [
      for f in sort(fileset("${path.module}/../backend/src", "*.py")) :
      filemd5("${path.module}/../backend/src/${f}")
    ],
  )

  provisioner "local-exec" {
    command     = "python build_lambda.py"
    working_dir = path.module
  }
}

data "aws_iam_role" "lambda" {
  name = var.lambda_role_name
}

resource "aws_cloudwatch_log_group" "lambda_api" {
  name              = "/aws/lambda/${var.project_name}-api"
  retention_in_days = 14

  tags = {
    Name    = "${var.project_name}-lambda-logs"
    Project = var.project_name
  }
}

resource "aws_cloudwatch_log_group" "apigw_http" {
  name              = "/aws/apigateway/${var.project_name}-http-api"
  retention_in_days = 14

  tags = {
    Name    = "${var.project_name}-apigw-logs"
    Project = var.project_name
  }
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project_name}-api"
  role             = data.aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "lambda_function.handler"
  filename         = data.archive_file.backend.output_path
  source_code_hash = data.archive_file.backend.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      NODE_ENV                  = "production"
      SECRETS_MANAGER_SECRET_ID = aws_secretsmanager_secret.application.id
      DYNAMODB_TABLE_NAME       = aws_dynamodb_table.application_events.name
      MEDICAL_DOCUMENTS_BUCKET  = terraform_data.medical_documents_bucket.input.bucket
      DATABASE_SECRET_ARN       = var.enable_rds ? aws_db_instance.postgres[0].master_user_secret[0].secret_arn : ""
      DATABASE_NAME             = var.enable_rds ? aws_db_instance.postgres[0].db_name : ""
      DATABASE_HOST             = var.enable_rds ? aws_db_instance.postgres[0].address : ""
      PAYMENT_MODE              = var.payment_mode
      STRIPE_SECRET_ARN         = aws_secretsmanager_secret.stripe.arn
      STRIPE_PRICE_AMOUNT_CENTS = tostring(var.stripe_price_amount_cents)
      ALLOW_DEMO_SEED           = var.allow_demo_seed ? "true" : "false"
      FRONTEND_BASE_URL         = var.frontend_base_url != "" ? var.frontend_base_url : "https://${terraform_data.frontend_bucket.input.bucket}.s3.${var.aws_region}.amazonaws.com/index.html"
      METRICS_ENABLED           = var.enable_monitoring ? "true" : "false"
    }
  }
  dynamic "vpc_config" {
    for_each = var.enable_rds ? [1] : []
    content {
      subnet_ids         = local.lambda_subnet_ids
      security_group_ids = [aws_security_group.lambda.id]
    }
  }
  depends_on = [
    terraform_data.lambda_dependencies,
    terraform_data.medical_documents_bucket,
    aws_vpc_endpoint.s3,
    aws_vpc_endpoint.dynamodb,
    aws_route_table_association.private,
    aws_cloudwatch_log_group.lambda_api,
  ]
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.project_name}-http-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  dynamic "access_log_settings" {
    for_each = var.enable_monitoring ? [1] : []
    content {
      destination_arn = aws_cloudwatch_log_group.apigw_http.arn
      format = jsonencode({
        requestId               = "$context.requestId"
        sourceIp                = "$context.identity.sourceIp"
        requestTime             = "$context.requestTime"
        protocol                = "$context.protocol"
        httpMethod              = "$context.httpMethod"
        routeKey                = "$context.routeKey"
        path                    = "$context.path"
        status                  = "$context.status"
        responseLength          = "$context.responseLength"
        integrationStatus       = "$context.integrationStatus"
        integrationLatency      = "$context.integrationLatency"
        responseLatency         = "$context.responseLatency"
        integrationErrorMessage = "$context.integrationErrorMessage"
      })
    }
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

output "api_url" { value = aws_apigatewayv2_api.http.api_endpoint }
