/*
DSML3850: Cloud Computing
Instructor: Thyago Mota
Description: Hardware-Genie Terraform Infrastructure — Wayback Newegg Lambda
*/

output "lambda_function_arn" {
  description = "ARN of the wayback scraper Lambda function."
  value       = aws_lambda_function.wayback_scraper.arn
}

output "lambda_function_name" {
  description = "Name of the wayback scraper Lambda function."
  value       = aws_lambda_function.wayback_scraper.function_name
}

output "schedule_rule_arn" {
  description = "ARN of the EventBridge schedule rule."
  value       = aws_cloudwatch_event_rule.schedule.arn
}
