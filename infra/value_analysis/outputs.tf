output "lambda_function_arn" {
  value = aws_lambda_function.value_analysis.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.value_analysis.function_name
}
