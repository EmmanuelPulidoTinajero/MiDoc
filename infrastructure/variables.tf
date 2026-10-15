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
