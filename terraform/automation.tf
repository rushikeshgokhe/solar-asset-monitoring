# ---------- Variables for optional Jira integration ----------
variable "jira_base_url" {
  type        = string
  description = "Jira Cloud base URL (e.g. https://your-domain.atlassian.net)"
  default     = "https://example.atlassian.net"
}

variable "jira_project_key" {
  type        = string
  description = "Jira project key for solar incidents"
  default     = "SOLAR"
}

variable "enable_scheduled_generator" {
  type        = bool
  description = "Enable 5-minute EventBridge trigger for synthetic telemetry generation"
  default     = false
}

# ---------- Secure Jira credentials in SSM Parameter Store (Free Tier) ----------
resource "aws_ssm_parameter" "jira_email" {
  name  = "/${var.project}/jira/email"
  type  = "SecureString"
  value = "placeholder@example.com"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "jira_token" {
  name  = "/${var.project}/jira/api_token"
  type  = "SecureString"
  value = "placeholder-token"

  lifecycle {
    ignore_changes = [value]
  }
}

# ---------- Dedicated SQS Ticket Queue + Ticket DLQ ----------
resource "aws_sqs_queue" "ticket_dlq" {
  name                      = "${var.project}-ticket-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "tickets" {
  name                       = "${var.project}-tickets"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ticket_dlq.arn
    maxReceiveCount     = 3
  })
}

# Allow Processor Lambda to publish actionable incidents to the ticket queue
data "aws_iam_policy_document" "processor_tickets" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.tickets.arn]
  }
}

resource "aws_iam_role_policy" "processor_tickets" {
  name   = "${local.function_name}-tickets"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.processor_tickets.json
}

# ---------- Scheduled Synthetic Telemetry Generator Lambda ----------
locals {
  generator_name = "${var.project}-generator"
  ticket_fn_name = "${var.project}-ticket-processor"
}

resource "aws_cloudwatch_log_group" "generator" {
  name              = "/aws/lambda/${local.generator_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "generator" {
  name               = "${local.generator_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "generator" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/telemetry/*"]
  }

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.generator.arn}:*"]
  }
}

resource "aws_iam_role_policy" "generator" {
  name   = "${local.generator_name}-policy"
  role   = aws_iam_role.generator.id
  policy = data.aws_iam_policy_document.generator.json
}

data "archive_file" "generator" {
  type        = "zip"
  source_dir  = "${path.module}/../src/generator"
  output_path = "${path.module}/generator.zip"
  excludes    = ["__pycache__"]
}

resource "aws_lambda_function" "generator" {
  function_name    = local.generator_name
  role             = aws_iam_role.generator.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 128
  filename         = data.archive_file.generator.output_path
  source_code_hash = data.archive_file.generator.output_base64sha256

  environment {
    variables = {
      TELEMETRY_BUCKET = aws_s3_bucket.data.bucket
      TELEMETRY_PREFIX = "telemetry/"
      INJECT_FAULTS    = "true"
    }
  }

  depends_on = [aws_cloudwatch_log_group.generator, aws_iam_role_policy.generator]
}

resource "aws_cloudwatch_event_rule" "telemetry_schedule" {
  name                = "${var.project}-telemetry-schedule"
  description         = "Trigger synthetic solar telemetry generation every 5 minutes"
  schedule_expression = "rate(5 minutes)"
  state               = var.enable_scheduled_generator ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "telemetry_generator" {
  rule      = aws_cloudwatch_event_rule.telemetry_schedule.name
  target_id = "TelemetryGeneratorLambda"
  arn       = aws_lambda_function.generator.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.generator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.telemetry_schedule.arn
}

# ---------- Ticket Processor Lambda (SQS -> DynamoDB + Jira) ----------
resource "aws_cloudwatch_log_group" "ticket_processor" {
  name              = "/aws/lambda/${local.ticket_fn_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "ticket_processor" {
  name               = "${local.ticket_fn_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "ticket_processor" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.tickets.arn]
  }

  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.incidents.arn]
  }

  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.jira_email.arn, aws_ssm_parameter.jira_token.arn]
  }

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ticket_processor.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ticket_processor" {
  name   = "${local.ticket_fn_name}-policy"
  role   = aws_iam_role.ticket_processor.id
  policy = data.aws_iam_policy_document.ticket_processor.json
}

data "archive_file" "ticket_processor" {
  type        = "zip"
  source_dir  = "${path.module}/../src/ticket_processor"
  output_path = "${path.module}/ticket_processor.zip"
  excludes    = ["__pycache__"]
}

resource "aws_lambda_function" "ticket_processor" {
  function_name    = local.ticket_fn_name
  role             = aws_iam_role.ticket_processor.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 128
  filename         = data.archive_file.ticket_processor.output_path
  source_code_hash = data.archive_file.ticket_processor.output_base64sha256

  environment {
    variables = {
      INCIDENTS_TABLE  = aws_dynamodb_table.incidents.name
      JIRA_BASE_URL    = var.jira_base_url
      JIRA_PROJECT_KEY = var.jira_project_key
      JIRA_EMAIL_PARAM = aws_ssm_parameter.jira_email.name
      JIRA_TOKEN_PARAM = aws_ssm_parameter.jira_token.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.ticket_processor, aws_iam_role_policy.ticket_processor]
}

resource "aws_lambda_event_source_mapping" "ticket_sqs" {
  event_source_arn = aws_sqs_queue.tickets.arn
  function_name    = aws_lambda_function.ticket_processor.arn
  batch_size       = 1
}

output "ticket_queue_url" {
  value = aws_sqs_queue.tickets.url
}

output "generator_lambda_name" {
  value = aws_lambda_function.generator.function_name
}