/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

locals {
  ecr_registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com"
  project_root = abspath("${path.module}/../..")
  image_uri    = "${aws_ecr_repository.this.repository_url}:${var.app_name}-latest"
  src_files    = sort(tolist(fileset(local.project_root, "src/**")))
  template_files = sort(tolist(fileset(local.project_root, "templates/**")))
  static_files   = sort(tolist(fileset(local.project_root, "static/**")))

  source_bundle_hash = sha256(join("", concat(
    [for file in local.src_files : filesha256("${local.project_root}/${file}")],
    [for file in local.template_files : filesha256("${local.project_root}/${file}")],
    [for file in local.static_files : filesha256("${local.project_root}/${file}")],
    [
      filesha256("${local.project_root}/Dockerfile"),
      filesha256("${local.project_root}/requirements.txt"),
      filesha256("${local.project_root}/.dockerignore"),
      try(filesha256("${local.project_root}/instance/parts.db"), "missing-parts-db")
    ]
  )))
}

resource "aws_ecr_repository" "this" {
  name                 = var.repo_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the latest 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "null_resource" "build_and_push_image" {
  triggers = {
    source_bundle_hash = local.source_bundle_hash
    app_name           = var.app_name
    repository_url     = aws_ecr_repository.this.repository_url
  }

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-Command"]
    working_dir = local.project_root
    command     = <<-EOT
      $ErrorActionPreference = 'Stop'
      cmd /c "aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${local.ecr_registry}"
      if ($LASTEXITCODE -ne 0) { throw 'Docker login to ECR failed.' }
      docker build --provenance=false -f Dockerfile -t ${local.image_uri} .
      if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
      $pushSucceeded = $false
      $maxAttempts = 5
      for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        cmd /c "aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${local.ecr_registry}"
        if ($LASTEXITCODE -ne 0) {
          Write-Host "docker login attempt $attempt failed."
          continue
        }
        docker push ${local.image_uri}
        if ($LASTEXITCODE -eq 0) {
          $pushSucceeded = $true
          break
        }
        Write-Host "docker push attempt $attempt failed."
      }
      if (-not $pushSucceeded) { throw 'Docker push failed after multiple attempts.' }
    EOT
  }

  depends_on = [aws_ecr_repository.this, aws_ecr_lifecycle_policy.this]
}

data "aws_ecr_image" "latest" {
  repository_name = aws_ecr_repository.this.name
  image_tag       = "${var.app_name}-latest"

  depends_on = [null_resource.build_and_push_image]
}