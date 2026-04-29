/*
Description: Hardware-Genie Terraform Infrastructure — Value Analysis Lambda
*/

terraform {
  required_version = ">= 1.4.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "terraform_remote_state" "vpc" {
  backend = "local"
  config  = { path = abspath("${path.module}/../vpc/terraform.tfstate") }
}

data "terraform_remote_state" "rds" {
  backend = "local"
  config  = { path = abspath("${path.module}/../rds/terraform.tfstate") }
}

locals {
  vpc_id             = coalesce(var.vpc_id, data.terraform_remote_state.vpc.outputs.vpc_id)
  private_subnet_ids = length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : data.terraform_remote_state.vpc.outputs.private_subnet_ids
  rds_dns_endpoint   = coalesce(var.rds_dns_endpoint, try(data.terraform_remote_state.rds.outputs.rds_dns_endpoint, null))
  database_url       = "postgresql+psycopg2://${var.db_username}:${urlencode(var.db_password)}@${local.rds_dns_endpoint}:${var.db_port}/${var.db_name}?sslmode=require"
  src_dir            = abspath("${path.module}/../../src/lambda/value_analysis")
  repo_root          = abspath("${path.module}/../..")
  zip_path           = "${path.module}/value_analysis.zip"
}

# ── Package zip ───────────────────────────────────────────────────────────────

resource "null_resource" "package" {
  triggers = {
    src_hash          = sha256(join("", [for f in fileset(local.src_dir, "**") : filesha256("${local.src_dir}/${f}")]))
    dockerfile_hash    = filesha256("${path.module}/Dockerfile")
    packaging_version  = "2"
  }

  provisioner "local-exec" {
    command = <<-EOT
      $ErrorActionPreference = 'Stop'
      $imageName = 'hardware-genie-value-analysis-packager'
      $containerName = 'hardware-genie-value-analysis-packager'

      if (Test-Path "${local.zip_path}") {
        Remove-Item "${local.zip_path}" -Force
      }

      docker build -f "${path.module}/Dockerfile" -t $imageName "${local.repo_root}"
      if ($LASTEXITCODE -ne 0) { throw 'docker build failed for Value Analysis package.' }

      docker rm -f $containerName | Out-Null
      $containerId = docker create --name $containerName $imageName
      if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'docker create failed for Value Analysis package.' }

      try {
        docker cp "$${containerId}:/artifacts/value_analysis.zip" "${local.zip_path}"
        if ($LASTEXITCODE -ne 0) { throw 'docker cp failed for Value Analysis package.' }
      }
      finally {
        docker rm -f $containerId | Out-Null
      }
    EOT
    interpreter = ["PowerShell", "-NoProfile", "-Command"]
  }
}

# ── IAM ───────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda" {
  name = "${var.function_name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "vpc_access" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# ── Security group ────────────────────────────────────────────────────────────

resource "aws_security_group" "lambda" {
  name        = "${var.function_name}-sg"
  description = "Value analysis Lambda egress"
  vpc_id      = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group_rule" "rds_from_lambda" {
  type                     = "ingress"
  from_port                = var.db_port
  to_port                  = var.db_port
  protocol                 = "tcp"
  security_group_id        = data.terraform_remote_state.rds.outputs.postgres_security_group_id
  source_security_group_id = aws_security_group.lambda.id
  description              = "Postgres from value analysis Lambda"
}

# ── CloudWatch log group ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 7
}

# ── Lambda function ───────────────────────────────────────────────────────────

resource "aws_lambda_function" "value_analysis" {
  function_name    = var.function_name
  role             = aws_iam_role.lambda.arn
  filename         = local.zip_path
  source_code_hash = null_resource.package.triggers.src_hash
  handler          = "lambda_function.handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 256

  environment {
    variables = {
      DATABASE_URL = local.database_url
    }
  }

  vpc_config {
    subnet_ids         = local.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  depends_on = [
    null_resource.package,
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.vpc_access,
  ]
}
