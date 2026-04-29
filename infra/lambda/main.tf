/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure — Wayback Newegg Lambda
*/

terraform {
  required_version = ">= 1.4.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
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

data "terraform_remote_state" "vpc" {
  backend = "local"
  config = {
    path = abspath("${path.module}/../vpc/terraform.tfstate")
  }
}

data "terraform_remote_state" "rds" {
  backend = "local"
  config = {
    path = abspath("${path.module}/../rds/terraform.tfstate")
  }
}

locals {
  vpc_id             = coalesce(var.vpc_id, data.terraform_remote_state.vpc.outputs.vpc_id)
  private_subnet_ids = length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : data.terraform_remote_state.vpc.outputs.private_subnet_ids
  rds_dns_endpoint   = coalesce(var.rds_dns_endpoint, try(data.terraform_remote_state.rds.outputs.rds_dns_endpoint, null))
  database_url       = "postgresql+psycopg2://${var.db_username}:${urlencode(var.db_password)}@${local.rds_dns_endpoint}:${var.db_port}/${var.db_name}?sslmode=require"
  src_dir            = abspath("${path.module}/../../src/lambda/wayback_scraper")
  src_hash           = sha256(join("", [for f in fileset(local.src_dir, "**") : filesha256("${local.src_dir}/${f}")]))
  zip_path           = "${path.module}/wayback_scraper.zip"
}

# ── IAM ──────────────────────────────────────────────────────────────────────

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
  description = "Wayback scraper Lambda egress"
  vpc_id      = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Allow Lambda SG to reach RDS
resource "aws_security_group_rule" "rds_from_lambda" {
  type                     = "ingress"
  from_port                = var.db_port
  to_port                  = var.db_port
  protocol                 = "tcp"
  security_group_id        = data.terraform_remote_state.rds.outputs.postgres_security_group_id
  source_security_group_id = aws_security_group.lambda.id
  description              = "Postgres from wayback Lambda"
}

# ── CloudWatch log group ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 7
}

# ── Lambda function ───────────────────────────────────────────────────────────

resource "aws_lambda_function" "wayback_scraper" {
  function_name    = var.function_name
  role             = aws_iam_role.lambda.arn
  filename         = local.zip_path
  source_code_hash = local.src_hash
  handler          = "lambda_function.handler"
  runtime          = "python3.12"
  timeout          = var.timeout
  memory_size      = var.memory_size

  environment {
    variables = {
      DATABASE_URL                 = local.database_url
      SCRAPY_TIMEOUT               = tostring(var.timeout - 30)
      VALUE_ANALYSIS_FUNCTION_NAME = var.value_analysis_function_name
    }
  }

  vpc_config {
    subnet_ids         = local.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.vpc_access,
  ]
}

# ── EventBridge schedule ──────────────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.function_name}-schedule"
  description         = "Trigger wayback scraper on a cron schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "wayback-scraper"
  arn       = aws_lambda_function.wayback_scraper.arn
  input     = var.event_payload
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.wayback_scraper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

# Allow scraper Lambda to invoke value analysis Lambda
resource "aws_iam_role_policy" "invoke_value_analysis" {
  name = "invoke-value-analysis"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = var.value_analysis_lambda_arn
    }]
  })
}
