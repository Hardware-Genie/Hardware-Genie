/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = [for s in aws_subnet.public : s.id]
}

output "public_subnet_cidr_blocks" {
  description = "CIDR blocks of the public subnets"
  value       = [for s in aws_subnet.public : s.cidr_block]
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = [for s in aws_subnet.private : s.id]
}

output "private_subnet_cidr_blocks" {
  description = "CIDR blocks of the private subnets"
  value       = [for s in aws_subnet.private : s.cidr_block]
}