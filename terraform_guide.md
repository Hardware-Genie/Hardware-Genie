# Hardware-Genie Terraform

This repo now follows the same split Terraform layout as the Windoors project:

- `infra/vpc` creates the VPC, public subnets, private subnets, NAT gateway, and route tables.
- `infra/rds` creates the bastion host and PostgreSQL RDS instance.
- `infra/docker` creates ECR and builds/pushes the application image.
- `infra/ecs` creates the ALB, ECS cluster, task definition, and ECS service.

Typical deployment order:

1. Apply `infra/vpc` first.
2. Apply `infra/rds` next, passing the VPC and subnet outputs plus an SSH CIDR.
3. Apply `infra/docker` to build and push the image to ECR.
4. Apply `infra/ecs`, passing only the DB password (VPC, image URI, and RDS endpoint are read from remote state outputs).

Current Docker outputs:

- `ecr_repository_url = "833337371951.dkr.ecr.us-west-1.amazonaws.com/hardware-genie"`
- `image_uri = "833337371951.dkr.ecr.us-west-1.amazonaws.com/hardware-genie:hardware-genie-latest"`

`infra/ecs` now reads `image_uri` from `infra/docker/terraform.tfstate` automatically (with a variable override available if needed).

Current RDS outputs:

- `bastion_private_key_path = "./hardware-genie-bastion.pem"`
- `ec2_instance_public_ip = "3.101.85.242"`
- `postgres_security_group_id = "sg-0220145effc18d2c1"`
- `rds_dns_endpoint = "hardware-genie-postgres.c384e28igf92.us-west-1.rds.amazonaws.com"`

`infra/ecs` now reads `rds_dns_endpoint` from `infra/rds/terraform.tfstate` automatically (with a variable override available if needed).

Database migration behavior:

- The app now prefers `DATABASE_URL` (RDS/PostgreSQL in ECS) and falls back to local SQLite for local development.
- On first ECS startup, if RDS is empty, the app seeds PostgreSQL from `instance/parts.db`.
- Seeding runs only once using a PostgreSQL advisory lock + seed status table (`app_seed_status`) to avoid duplicate imports when multiple tasks start.

The modules are intentionally separate so you can wire outputs between them the same way the Windoors project does today. The Flask app database model can be updated later without changing this infrastructure layout.

Force a new deployment 
aws ecs update-service --cluster hardware-genie-cluster --service hardware-genie-service --force-new-deployment --region us-west-1