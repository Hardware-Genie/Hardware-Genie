# Hardware-Genie Terraform

147.153.93.71/32

This repo now follows the same split Terraform layout as the Windoors project:

- `infra/vpc` creates the VPC, public subnets, private subnets, NAT gateway, and route tables.
- `infra/rds` creates the bastion host and PostgreSQL RDS instance.
- `infra/docker` creates ECR and builds/pushes the application image.
- `infra/ecs` creates the ALB, ECS cluster, task definition, and ECS service.

Typical deployment order:

1. Apply `infra/vpc` first.
2. Apply `infra/rds` next, passing the VPC and subnet outputs plus an SSH CIDR.
3. Apply `infra/docker` to build and push the image to ECR.
4. Apply `infra/ecs`, passing the RDS endpoint and DB password.

Current Docker outputs:

- `ecr_repository_url = "833337371951.dkr.ecr.us-west-1.amazonaws.com/hardware-genie"`
- `image_uri = "833337371951.dkr.ecr.us-west-1.amazonaws.com/hardware-genie:hardware-genie-latest"`

`infra/ecs` now reads `image_uri` from `infra/docker/terraform.tfstate` automatically (with a variable override available if needed).

The modules are intentionally separate so you can wire outputs between them the same way the Windoors project does today. The Flask app database model can be updated later without changing this infrastructure layout.