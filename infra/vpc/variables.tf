/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

variable "region" {
  description = "AWS region to deploy resources in."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix used for naming AWS resources."
  type        = string
  default     = "hardware-genie"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.10.0.0/16"
}

variable "azs" {
  description = "List of availability zones to use (length must match the number of subnets per tier)."
  type        = list(string)
  default     = ["us-west-1a", "us-west-1c"]
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets (e.g., two for two AZs)."
  type        = list(string)
  default     = ["10.10.0.0/24", "10.10.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == length(var.azs)
    error_message = "public_subnet_cidrs length must match azs length."
  }
}

variable "private_subnet_cidrs" {
  description = "List of CIDR blocks for private subnets (e.g., two for two AZs)."
  type        = list(string)
  default     = ["10.10.100.0/24", "10.10.101.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) == length(var.azs)
    error_message = "private_subnet_cidrs length must match azs length."
  }
}