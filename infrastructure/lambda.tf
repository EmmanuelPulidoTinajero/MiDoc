data "archive_file" "backend" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/.lambda-build"
  output_path = "${path.module}/../backend/lambda-package.zip"
  depends_on  = [terraform_data.lambda_dependencies]
}

resource "terraform_data" "lambda_dependencies" {
  triggers_replace = [
    filemd5("${path.module}/../backend/requirements.txt"),
    filemd5("${path.module}/build_lambda.py"),
    filemd5("${path.module}/../backend/src/app.py"),
    filemd5("${path.module}/../backend/src/flujos.py"),
    filemd5("${path.module}/../backend/src/reglas.py"),
    filemd5("${path.module}/../backend/src/servicios_aws.py"),
    filemd5("${path.module}/../backend/src/lambda_function.py"),
    filemd5("${path.module}/../backend/src/metricas.py"),
    filemd5("${path.module}/../backend/src/schema.sql"),
  ]

  provisioner "local-exec" {
    command     = "python build_lambda.py"
    working_dir = path.module
  }
}

data "aws_iam_role" "lambda" {
  name = var.lambda_role_name
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
    }
  }
  dynamic "vpc_config" {
    for_each = var.enable_rds ? [1] : []
    content {
      subnet_ids         = local.lambda_subnet_ids
      security_group_ids = [aws_security_group.lambda.id]
    }
  }
  depends_on = [terraform_data.lambda_dependencies, terraform_data.medical_documents_bucket,
  aws_vpc_endpoint.s3, aws_vpc_endpoint.dynamodb]
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
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

output "api_url" { value = aws_apigatewayv2_api.http.api_endpoint }
