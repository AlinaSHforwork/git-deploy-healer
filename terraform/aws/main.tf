variable "region" {
  type    = string
  default = "us-east-1"
}

variable "api_key_secret" {
  type = string
}

variable "github_webhook_secret" {
  type = string
}

provider "aws" {
  region = var.region
}

# This module currently only provisions secrets; expand with VPC/ecs as needed.

output "region" {
  value = var.region
}
