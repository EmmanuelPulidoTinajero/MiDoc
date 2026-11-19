variable "project_name" {
  type    = string
  default = "midoc"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_username" {
  type      = string
  sensitive = true
  default   = "midoc_admin"
}

variable "lambda_role_name" {
  type    = string
  default = "LabRole"
}

variable "enable_rds" {
  type    = bool
  default = true
}

variable "jwt_secret" {
  type        = string
  sensitive   = true
  description = "Secret used to sign JWTs; provide through TF_VAR_jwt_secret or a local tfvars file."
  validation {
    condition     = length(var.jwt_secret) >= 32
    error_message = "jwt_secret must contain at least 32 characters."
  }
}

variable "frontend_bucket_name" {
  type        = string
  default     = ""
  description = "Optional globally unique bucket name. Empty uses project-account."
}

variable "vpc_id" {
  type    = string
  default = ""
}

variable "lambda_subnet_ids" {
  type    = list(string)
  default = []
}

variable "enable_nat_gateway" {
  type        = bool
  default     = true
  description = "Create private subnets + NAT Gateway so VPC Lambda reaches Stripe HTTPS endpoints."
}

variable "private_subnet_cidrs" {
  type        = list(string)
  default     = ["172.31.96.0/20", "172.31.112.0/20"]
  description = "CIDR blocks for managed private Lambda subnets inside the default VPC."
  validation {
    condition     = length(var.private_subnet_cidrs) == 2
    error_message = "private_subnet_cidrs must contain exactly 2 CIDR blocks."
  }
}

variable "private_subnet_azs" {
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
  description = "Availability zones for managed private Lambda subnets."
  validation {
    condition     = length(var.private_subnet_azs) == 2
    error_message = "private_subnet_azs must contain exactly 2 availability zones."
  }
}

variable "payment_mode" {
  type        = string
  default     = "test"
  description = "Stripe payment mode: 'test' for sandbox, 'live' for production, or 'simulado' to run payments simulated without a real key."
  validation {
    condition     = contains(["test", "live", "simulado"], var.payment_mode)
    error_message = "payment_mode must be 'test', 'live' or 'simulado'."
  }
}

variable "stripe_secret_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Stripe secret key (sk_test_... for test mode, sk_live_... for live mode)."
  validation {
    condition = (
      var.stripe_secret_key == "" ||
      (var.payment_mode == "test" && startswith(var.stripe_secret_key, "sk_test_")) ||
      (var.payment_mode == "live" && startswith(var.stripe_secret_key, "sk_live_"))
    )
    error_message = "When provided, stripe_secret_key must start with 'sk_test_' in test mode or 'sk_live_' in live mode."
  }
}

variable "stripe_webhook_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Stripe webhook signing secret (whsec_...)."
  validation {
    condition     = var.stripe_webhook_secret == "" || startswith(var.stripe_webhook_secret, "whsec_")
    error_message = "When provided, stripe_webhook_secret must start with 'whsec_'."
  }
}

variable "stripe_price_amount_cents" {
  type        = number
  default     = 2000
  description = "Monthly subscription price in USD cents (default 2000 = $20.00 USD)."
  validation {
    condition     = var.stripe_price_amount_cents >= 50 && floor(var.stripe_price_amount_cents) == var.stripe_price_amount_cents
    error_message = "stripe_price_amount_cents must be an integer >= 50."
  }
}

variable "allow_demo_seed" {
  type        = bool
  default     = false
  description = "Allow backend cold-start demo user seeding (keep false in production)."
}

variable "frontend_base_url" {
  type        = string
  default     = ""
  description = "Optional public base URL for frontend redirects; empty defaults to S3 HTTPS index.html."
}

variable "alert_email" {
  type        = string
  default     = ""
  description = "Optional email address subscribed to the CloudWatch alerts SNS topic."
}

variable "delete_medical_bucket_on_destroy" {
  type        = bool
  default     = true
  description = "Empty and delete the private medical documents S3 bucket during terraform destroy."
}
