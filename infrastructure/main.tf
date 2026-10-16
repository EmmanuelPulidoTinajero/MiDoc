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
    values = [var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default.id]
  }
}

data "aws_route_tables" "default" {
  vpc_id = local.vpc_id
}

locals {
  vpc_id            = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default.id
  lambda_subnet_ids = length(var.lambda_subnet_ids) > 0 ? var.lambda_subnet_ids : slice(data.aws_subnets.default.ids, 0, 2)
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
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.lambda_subnet_ids
  security_group_ids  = [aws_security_group.lambda.id]
  private_dns_enabled = true
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.default.ids
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.default.ids
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
}

resource "aws_secretsmanager_secret" "application" {
  name_prefix = "${var.project_name}-application-"
  description = "Secretos de ejecución de MiDoc; los valores se cargan fuera del repositorio."
}

resource "aws_secretsmanager_secret_version" "application" {
  secret_id     = aws_secretsmanager_secret.application.id
  secret_string = jsonencode({ jwt_secret = var.jwt_secret })

  lifecycle {
    ignore_changes = [secret_string]
  }
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
    bucket = "${var.project_name}-documents-${data.aws_caller_identity.current.account_id}"
    region = var.aws_region
  }
  triggers_replace = [var.project_name, data.aws_caller_identity.current.account_id,
  filemd5("${path.module}/s3_medical.py")]

  provisioner "local-exec" {
    command     = "python s3_medical.py"
    working_dir = path.module
    environment = {
      AWS_REGION             = var.aws_region
      MIDOC_DOCUMENTS_BUCKET = "${var.project_name}-documents-${data.aws_caller_identity.current.account_id}"
      MIDOC_FRONTEND_BUCKET  = terraform_data.frontend_bucket.input.bucket
    }
  }
}

output "database_endpoint" {
  value = var.enable_rds ? aws_db_instance.postgres[0].address : null
}
output "application_secret_arn" { value = aws_secretsmanager_secret.application.arn }
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
