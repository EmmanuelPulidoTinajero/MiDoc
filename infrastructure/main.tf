terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_route_table" "default_main" {
  vpc_id = local.vpc_id
  filter {
    name   = "association.main"
    values = ["true"]
  }
}

data "aws_subnet" "public_nat" {
  count  = local.use_managed_private_network ? 1 : 0
  vpc_id = local.vpc_id
  filter {
    name   = "availability-zone"
    values = [var.private_subnet_azs[0]]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

locals {
  vpc_id                      = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default.id
  use_managed_private_network = var.enable_rds && var.enable_nat_gateway && length(var.lambda_subnet_ids) == 0
  lambda_subnet_ids           = length(var.lambda_subnet_ids) > 0 ? var.lambda_subnet_ids : (local.use_managed_private_network ? aws_subnet.private[*].id : slice(sort(data.aws_subnets.default.ids), 0, 2))
  gateway_route_table_ids     = distinct(concat([data.aws_route_table.default_main.id], local.use_managed_private_network ? [aws_route_table.private[0].id] : []))
}

resource "aws_subnet" "private" {
  count                   = local.use_managed_private_network ? 2 : 0
  vpc_id                  = local.vpc_id
  cidr_block              = var.private_subnet_cidrs[count.index]
  availability_zone       = var.private_subnet_azs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name    = "${var.project_name}-private-${var.private_subnet_azs[count.index]}"
    Project = var.project_name
  }
}

resource "aws_eip" "nat" {
  count  = local.use_managed_private_network ? 1 : 0
  domain = "vpc"

  tags = {
    Name    = "${var.project_name}-nat-eip"
    Project = var.project_name
  }
}

resource "aws_nat_gateway" "this" {
  count         = local.use_managed_private_network ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = data.aws_subnet.public_nat[0].id

  tags = {
    Name    = "${var.project_name}-nat"
    Project = var.project_name
  }
}

resource "aws_route_table" "private" {
  count  = local.use_managed_private_network ? 1 : 0
  vpc_id = local.vpc_id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[0].id
  }

  tags = {
    Name    = "${var.project_name}-private-rt"
    Project = var.project_name
  }
}

resource "aws_route_table_association" "private" {
  count          = local.use_managed_private_network ? 2 : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-rds-"
  description = "MiDoc PostgreSQL access from Lambda"
  vpc_id      = local.vpc_id

  ingress {
    description     = "PostgreSQL from MiDoc Lambda"
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-rds-sg"
    Project = var.project_name
  }
}

resource "aws_security_group" "lambda" {
  name_prefix = "${var.project_name}-lambda-"
  description = "MiDoc Lambda VPC access"
  vpc_id      = local.vpc_id

  ingress {
    description = "Private AWS service endpoints"
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    self        = true
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-lambda-sg"
    Project = var.project_name
  }
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.lambda_subnet_ids
  security_group_ids  = [aws_security_group.lambda.id]
  private_dns_enabled = true

  tags = {
    Name    = "${var.project_name}-vpce-secretsmanager"
    Project = var.project_name
  }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.gateway_route_table_ids

  tags = {
    Name    = "${var.project_name}-vpce-s3"
    Project = var.project_name
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.gateway_route_table_ids

  tags = {
    Name    = "${var.project_name}-vpce-dynamodb"
    Project = var.project_name
  }
}

resource "aws_db_instance" "postgres" {
  count                       = var.enable_rds ? 1 : 0
  identifier_prefix           = "${var.project_name}-"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.db_instance_class
  allocated_storage           = 20
  db_name                     = "midoc"
  username                    = var.db_username
  manage_master_user_password = true
  skip_final_snapshot         = true
  publicly_accessible         = false
  storage_encrypted           = true
  vpc_security_group_ids      = [aws_security_group.rds.id]

  tags = {
    Name    = "${var.project_name}-postgres"
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret" "application" {
  name_prefix             = "${var.project_name}-application-"
  description             = "Secretos de ejecución de MiDoc; los valores se cargan fuera del repositorio."
  recovery_window_in_days = 0

  tags = {
    Name    = "${var.project_name}-application"
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "application" {
  secret_id     = aws_secretsmanager_secret.application.id
  secret_string = jsonencode({ jwt_secret = var.jwt_secret })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "stripe" {
  name_prefix             = "${var.project_name}-stripe-"
  description             = "Configuración y credenciales de Stripe para MiDoc (modo test o live)."
  recovery_window_in_days = 0

  tags = {
    Name    = "${var.project_name}-stripe"
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "stripe" {
  secret_id = aws_secretsmanager_secret.stripe.id
  secret_string = jsonencode({
    payment_mode          = var.payment_mode
    stripe_secret_key     = var.stripe_secret_key
    stripe_webhook_secret = var.stripe_webhook_secret
    price_amount_cents    = var.stripe_price_amount_cents
  })
}

resource "aws_dynamodb_table" "application_events" {
  name         = "${var.project_name}-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  server_side_encryption { enabled = true }

  tags = {
    Name    = "${var.project_name}-events"
    Project = var.project_name
  }
}

resource "terraform_data" "frontend_bucket" {
  input = {
    bucket = var.frontend_bucket_name != "" ? var.frontend_bucket_name : "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"
    region = var.aws_region
  }
  triggers_replace = [var.project_name, data.aws_caller_identity.current.account_id, filemd5("${path.module}/s3_frontend.py")]

  provisioner "local-exec" {
    command     = "python s3_frontend.py create"
    working_dir = path.module
    environment = {
      AWS_REGION            = var.aws_region
      MIDOC_FRONTEND_BUCKET = var.frontend_bucket_name != "" ? var.frontend_bucket_name : "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"
      MIDOC_FRONTEND_DIST   = "${path.module}/../frontend/dist/midoc-frontend"
    }
  }

  provisioner "local-exec" {
    when        = destroy
    command     = "python s3_frontend.py destroy"
    working_dir = path.module
    environment = {
      AWS_REGION            = self.input.region
      MIDOC_FRONTEND_BUCKET = self.input.bucket
    }
  }
}

resource "terraform_data" "medical_documents_bucket" {
  input = {
    bucket            = "${var.project_name}-documents-${data.aws_caller_identity.current.account_id}"
    region            = var.aws_region
    delete_on_destroy = var.delete_medical_bucket_on_destroy
  }
  triggers_replace = [var.project_name, data.aws_caller_identity.current.account_id, filemd5("${path.module}/s3_medical.py")]

  provisioner "local-exec" {
    command     = "python s3_medical.py create"
    working_dir = path.module
    environment = {
      AWS_REGION             = var.aws_region
      MIDOC_DOCUMENTS_BUCKET = "${var.project_name}-documents-${data.aws_caller_identity.current.account_id}"
      MIDOC_FRONTEND_BUCKET  = terraform_data.frontend_bucket.input.bucket
    }
  }

  provisioner "local-exec" {
    when        = destroy
    command     = "python s3_medical.py destroy"
    working_dir = path.module
    environment = {
      AWS_REGION                      = self.input.region
      MIDOC_DOCUMENTS_BUCKET          = self.input.bucket
      MIDOC_DELETE_MEDICAL_ON_DESTROY = tostring(self.input.delete_on_destroy)
    }
  }
}

output "database_endpoint" {
  value = var.enable_rds ? aws_db_instance.postgres[0].address : null
}
output "application_secret_arn" { value = aws_secretsmanager_secret.application.arn }
output "stripe_secret_arn" { value = aws_secretsmanager_secret.stripe.arn }
output "payment_mode" { value = var.payment_mode }
output "events_table_name" { value = aws_dynamodb_table.application_events.name }
output "frontend_bucket_name" {
  value = var.frontend_bucket_name != "" ? var.frontend_bucket_name : "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"
}
output "frontend_url" {
  value = "https://${terraform_data.frontend_bucket.input.bucket}.s3.${var.aws_region}.amazonaws.com/index.html"
}
output "medical_documents_bucket" {
  value = terraform_data.medical_documents_bucket.input.bucket
}
