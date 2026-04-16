output "ecr_repository_url" {
  description = "ECR repository URL."
  value       = aws_ecr_repository.this.repository_url
}

output "image_uri" {
  description = "Full image URI pushed to ECR."
  value       = local.image_uri
}