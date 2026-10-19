output "bucket_name" {
  value = aws_s3_bucket.data.bucket
}

output "lambda_name" {
  value = aws_lambda_function.processor.function_name
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}