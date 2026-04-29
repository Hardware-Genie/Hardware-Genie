variable "region" {
  type    = string
  default = "us-west-1"
}

variable "function_name" {
  type    = string
  default = "hardware-genie-value-analysis"
}

variable "vpc_id" {
  type    = string
  default = null
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []
}

variable "rds_dns_endpoint" {
  type    = string
  default = null
}

variable "db_username" {
  type    = string
  default = "postgres"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "db_name" {
  type    = string
  default = "hardware_genie"
}

variable "db_port" {
  type    = number
  default = 5432
}
