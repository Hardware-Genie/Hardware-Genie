output "ecr_repository_url" {
  description = "ECR repository URL."
  value       = aws_ecr_repository.this.repository_url
}

output "image_uri" {
  description = "Digest-pinned image URI for ECS task definitions."
  value       = "${aws_ecr_repository.this.repository_url}@${data.aws_ecr_image.latest.image_digest}"
}