# El frontend lee la URL de la API de config.json al arrancar, así no hay que
# editar el código ni recompilar cada vez que API Gateway cambia de URL.
# Se vuelve a publicar si cambia la URL o si se recrea el bucket del frontend
# (s3_frontend.py sincroniza con --delete y borraría config.json).
resource "terraform_data" "frontend_config" {
  triggers_replace = [aws_apigatewayv2_api.http.api_endpoint, terraform_data.frontend_bucket.id]

  provisioner "local-exec" {
    command     = "python frontend_config.py"
    working_dir = path.module
    environment = {
      MIDOC_FRONTEND_BUCKET = terraform_data.frontend_bucket.input.bucket
      MIDOC_API_URL         = aws_apigatewayv2_api.http.api_endpoint
    }
  }
}
