variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "catalyst-backtester"
}

variable "app_port" {
  description = "Port the container listens on (matches Dockerfile/entrypoint default)."
  type        = string
  default     = "7860"
}

variable "image_tag" {
  description = "ECR image tag App Runner serves and auto-deploys on push."
  type        = string
  default     = "latest"
}

# -- App Runner sizing ------------------------------------------------------
variable "apprunner_cpu" {
  description = "App Runner vCPU units (e.g. 1024 = 1 vCPU)."
  type        = string
  default     = "1024"
}

variable "apprunner_memory" {
  description = "App Runner memory in MB."
  type        = string
  default     = "2048"
}

variable "apprunner_unsupported_az_ids" {
  description = "AZ IDs where App Runner VPC connectors are unavailable (excluded from the connector subnets)."
  type        = list(string)
  default     = ["use1-az3"]
}

# -- Database ---------------------------------------------------------------
variable "db_username" {
  description = "Postgres master username."
  type        = string
  default     = "catalyst"
}

variable "db_password" {
  description = "Postgres master password (set via TF_VAR_db_password or a tfvars file; do not commit)."
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "catalyst"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage in GB."
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "Postgres engine version."
  type        = string
  default     = "16"
}
