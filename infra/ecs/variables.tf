/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-west-1"
}

variable "vpc_id" {
  description = "VPC ID for ECS and ALB."
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS service tasks."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for ALB placement."
  type        = list(string)
  default     = []
}

variable "app_name" {
  description = "Application name."
  type        = string
  default     = "hardware-genie"
}

variable "repo_name" {
  description = "ECR repository name."
  type        = string
  default     = "hardware-genie"
}

variable "image_uri" {
  description = "Optional full image URI override. By default, read from infra/docker output image_uri."
  type        = string
  default     = null
}

variable "container_port" {
  description = "Container port exposed by Flask app."
  type        = number
  default     = 5000
}

variable "desired_count" {
  description = "Initial desired number of ECS tasks."
  type        = number
  default     = 1
}

variable "min_task_count" {
  description = "Minimum tasks for autoscaling."
  type        = number
  default     = 1
}

variable "max_task_count" {
  description = "Maximum tasks for autoscaling."
  type        = number
  default     = 6
}

variable "cpu_target_percent" {
  description = "CPU target utilization for ECS autoscaling policy."
  type        = number
  default     = 75
}

variable "task_cpu" {
  description = "Fargate CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate memory in MiB."
  type        = number
  default     = 1024
}

variable "db_username" {
  description = "Database username used by app."
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "Database password used by app."
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name used by app."
  type        = string
  default     = "hardware_genie"
}

variable "rds_dns_endpoint" {
  description = "RDS endpoint DNS name."
  type        = string
  default     = null
}

variable "db_port" {
  description = "Database port."
  type        = number
  default     = 5432
}

variable "secret_key" {
  description = "Flask secret key injected into container."
  type        = string
  default     = "replace-me-with-a-strong-secret"
}

variable "seed_sqlite_to_rds" {
  description = "Whether app tasks should run SQLite-to-RDS seeding at startup."
  type        = bool
  default     = false
}

variable "scraper_lambda_name" {
  description = "Name of the wayback scraper Lambda function to invoke from the app."
  type        = string
  default     = "hardware-genie-wayback-scraper"
}

variable "scraper_lambda_arn" {
  description = "ARN of the wayback scraper Lambda (used to grant ECS invoke permission)."
  type        = string
  default     = null
}