# ---------- DynamoDB: persistent, idempotent incident history ----------
resource "aws_dynamodb_table" "incidents" {
  name         = "${var.project}-incidents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }
}

# ---------- SQS dead-letter queue: keeps events that failed ----------
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

# ---------- Extra permissions for the Lambda role ----------
data "aws_iam_policy_document" "reliability" {
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]
    resources = [aws_dynamodb_table.incidents.arn]
  }

  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "reliability" {
  name   = "${local.function_name}-reliability"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.reliability.json
}

# ---------- Failed invocations go to the dead-letter queue ----------
resource "aws_lambda_function_event_invoke_config" "processor" {
  function_name                = aws_lambda_function.processor.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }

  depends_on = [aws_iam_role_policy.reliability]
}

# ---------- CloudWatch alarm: email when the Lambda errors ----------
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project}-lambda-errors"
  alarm_description   = "The Lambda function reported one or more errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.processor.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

output "incidents_table" {
  value = aws_dynamodb_table.incidents.name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}