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
  default     = 2
}

variable "min_task_count" {
  description = "Minimum tasks for autoscaling."
  type        = number
  default     = 2
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