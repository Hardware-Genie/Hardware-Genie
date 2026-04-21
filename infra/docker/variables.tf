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

variable "app_name" {
  description = "Application name used in image tag."
  type        = string
  default     = "hardware-genie"
}

variable "repo_name" {
  description = "ECR repository name."
  type        = string
  default     = "hardware-genie"
}