# El frontend lee la URL de la API y paymentMode de config.json al arrancar, así no hay que
# editar el código ni recompilar cada vez que API Gateway cambia de URL o de modo de pago.
# Se vuelve a publicar si cambia la URL, paymentMode, frontend_config.py o si se recrea el bucket
# (s3_frontend.py sincroniza con --delete y borraría config.json).
resource "terraform_data" "frontend_config" {
  triggers_replace = [
    aws_apigatewayv2_api.http.api_endpoint,
    terraform_data.frontend_bucket.id,
    var.payment_mode,
    filemd5("${path.module}/frontend_config.py"),
  ]

  provisioner "local-exec" {
    command     = "python frontend_config.py"
    working_dir = path.module
    environment = {
      AWS_REGION            = var.aws_region
      MIDOC_FRONTEND_BUCKET = terraform_data.frontend_bucket.input.bucket
      MIDOC_API_URL         = aws_apigatewayv2_api.http.api_endpoint
      MIDOC_PAYMENT_MODE    = var.payment_mode
    }
  }
}
