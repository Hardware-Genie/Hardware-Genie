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

variable "instance_name" {
  description = "Prefix used for naming resources."
  type        = string
  default     = "hardware-genie"
}

variable "ami" {
  description = "AMI for bastion host."
  type        = string
  default     = "ami-0fca1aacaa1ed9168"
}

variable "instance_type" {
  description = "EC2 type for bastion host."
  type        = string
  default     = "t3.micro"
}

variable "vpc_id" {
  description = "VPC ID where RDS and bastion are deployed."
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for DB subnet group."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for bastion placement."
  type        = list(string)
  default     = []
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to SSH into bastion host (recommend your public IP/32)."
  type        = string
}

variable "app_private_cidr_blocks" {
  description = "Private CIDR blocks where ECS tasks run (used to allow Postgres access)."
  type        = list(string)
  default     = []
}

variable "app_security_group_ids" {
  description = "Optional ECS/app security groups allowed to access Postgres."
  type        = list(string)
  default     = []
}

variable "db_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "hardware_genie"
}

variable "db_username" {
  description = "PostgreSQL master username."
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "PostgreSQL master password."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.db_password) >= 8
    error_message = "db_password must be at least 8 characters long."
  }
}

variable "engine_version" {
  description = "PostgreSQL engine version. Leave unset to let AWS pick a supported version."
  type        = string
  default     = null
}

variable "allocated_storage" {
  description = "Allocated storage size in GiB."
  type        = number
  default     = 20
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}