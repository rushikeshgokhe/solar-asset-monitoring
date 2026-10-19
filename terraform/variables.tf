variable "alert_email" {
  type        = string
  description = "Email address that receives SNS alerts"
}

variable "project" {
  type    = string
  default = "solar-monitoring"
}