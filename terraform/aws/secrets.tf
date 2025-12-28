/*
  Terraform config to create Secrets Manager entries for secrets used by the app.
  This is an optional convenience skeleton; do not store real secrets in code.
*/
provider "aws" {
  region = var.region
}

resource "aws_secretsmanager_secret" "api_key" {
  name = "git-deploy-healer/API_KEY"
}

resource "aws_secretsmanager_secret_version" "api_key_version" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = var.api_key_secret
}

resource "aws_secretsmanager_secret" "github_webhook" {
  name = "git-deploy-healer/GITHUB_WEBHOOK_SECRET"
}

resource "aws_secretsmanager_secret_version" "github_webhook_version" {
  secret_id     = aws_secretsmanager_secret.github_webhook.id
  secret_string = var.github_webhook_secret
}

output "api_key_secret_arn" {
  value = aws_secretsmanager_secret.api_key.arn
}
