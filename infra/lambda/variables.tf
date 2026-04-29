/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure — Wayback Newegg Lambda
*/

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-west-1"
}

variable "function_name" {
  description = "Lambda function name."
  type        = string
  default     = "hardware-genie-wayback-scraper"
}

variable "timeout" {
  description = "Lambda timeout in seconds (max 900)."
  type        = number
  default     = 900
}

variable "memory_size" {
  description = "Lambda memory in MB."
  type        = number
  default     = 512
}

variable "schedule_expression" {
  description = "EventBridge cron/rate expression for automatic runs."
  type        = string
  default     = "rate(7 days)"
}

variable "event_payload" {
  description = "JSON payload passed to the Lambda on each scheduled invocation."
  type        = string
  default     = "{}"
}

variable "vpc_id" {
  description = "VPC ID override (reads from vpc state if null)."
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "Private subnet IDs override (reads from vpc state if empty)."
  type        = list(string)
  default     = []
}

variable "rds_dns_endpoint" {
  description = "RDS endpoint override (reads from rds state if null)."
  type        = string
  default     = null
}

variable "db_username" {
  description = "Database username."
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "Database password."
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name."
  type        = string
  default     = "hardware_genie"
}

variable "db_port" {
  description = "Database port."
  type        = number
  default     = 5432
}

variable "value_analysis_function_name" {
  description = "Name of the value analysis Lambda to invoke after scraping."
  type        = string
  default     = "hardware-genie-value-analysis"
}

variable "value_analysis_lambda_arn" {
  description = "ARN of the value analysis Lambda (for IAM invoke permission)."
  type        = string
}
