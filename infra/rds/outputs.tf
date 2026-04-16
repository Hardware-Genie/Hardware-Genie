/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure
*/

output "rds_dns_endpoint" {
  value = aws_db_instance.postgres.address
}

output "ec2_instance_public_ip" {
  value = aws_instance.bastion.public_ip
}

output "postgres_security_group_id" {
  value = aws_security_group.postgres.id
}

output "bastion_private_key_path" {
  value = local_file.bastion_private_key.filename
}