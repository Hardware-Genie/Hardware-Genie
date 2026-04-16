/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

terraform {
  required_version = ">= 1.4.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = ">= 2.0"
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

resource "tls_private_key" "bastion" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

locals {
  vpc_id                    = coalesce(var.vpc_id, data.terraform_remote_state.vpc.outputs.vpc_id)
  private_subnet_ids        = length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : data.terraform_remote_state.vpc.outputs.private_subnet_ids
  public_subnet_ids         = length(var.public_subnet_ids) > 0 ? var.public_subnet_ids : data.terraform_remote_state.vpc.outputs.public_subnet_ids
  app_private_cidr_blocks   = length(var.app_private_cidr_blocks) > 0 ? var.app_private_cidr_blocks : data.terraform_remote_state.vpc.outputs.private_subnet_cidr_blocks
}

resource "local_file" "bastion_private_key" {
  content         = tls_private_key.bastion.private_key_pem
  filename        = "${path.module}/${var.instance_name}-bastion.pem"
  file_permission = "0600"
}

resource "aws_key_pair" "bastion" {
  key_name   = "${var.instance_name}-bastion-key"
  public_key = tls_private_key.bastion.public_key_openssh
}

resource "aws_security_group" "bastion" {
  name        = "${var.instance_name}-bastion-sg"
  description = "Bastion host security group"
  vpc_id      = local.vpc_id

  ingress {
    description = "SSH access to bastion"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.instance_name}-bastion-sg"
  }
}

resource "aws_security_group" "postgres" {
  name        = "${var.instance_name}-postgres-sg"
  description = "Postgres access from bastion and app network"
  vpc_id      = local.vpc_id

  ingress {
    description     = "Postgres from bastion"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
  }

  ingress {
    description = "Postgres from private app CIDRs"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = local.app_private_cidr_blocks
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.instance_name}-postgres-sg"
  }
}

resource "aws_security_group_rule" "postgres_from_app_sg" {
  for_each = toset(var.app_security_group_ids)

  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.postgres.id
  source_security_group_id = each.value
  description              = "Postgres from approved app security group"
}

resource "aws_db_subnet_group" "postgres" {
  name       = "${var.instance_name}-postgres-subnet-group"
  subnet_ids = local.private_subnet_ids

  tags = {
    Name = "${var.instance_name}-postgres-subnet-group"
  }
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.instance_name}-postgres"
  engine                 = "postgres"
  engine_version         = var.engine_version
  instance_class         = var.db_instance_class
  allocated_storage      = var.allocated_storage
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  storage_encrypted      = true
  backup_retention_period = 0
  skip_final_snapshot    = true
  publicly_accessible    = false
  vpc_security_group_ids = [aws_security_group.postgres.id]
  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  multi_az               = false

  tags = {
    Name = "${var.instance_name}-postgres"
  }
}

resource "aws_instance" "bastion" {
  ami                         = var.ami
  instance_type               = var.instance_type
  subnet_id                   = local.public_subnet_ids[0]
  key_name                    = aws_key_pair.bastion.key_name
  vpc_security_group_ids      = [aws_security_group.bastion.id]
  associate_public_ip_address = true

  tags = {
    Name = "${var.instance_name}-bastion"
  }
}