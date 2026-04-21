/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

output "load_balancer_dns_name" {
  description = "The DNS name of the application load balancer"
  value       = aws_lb.this.dns_name
}

output "ecs_service_security_group_id" {
  description = "Security group ID attached to ECS tasks."
  value       = aws_security_group.ecs_service.id
}