# backend.tf
# Terraform backend configuration with variable support
# Usage: terraform init -backend-config="bucket=my-bucket" -backend-config="key=pypaas/terraform.tfstate"

terraform {
  backend "s3" {
    # These will be provided via -backend-config flags or environment variables
    # bucket         = var.state_bucket  # TF_VAR_state_bucket or -backend-config
    # key            = var.state_key     # TF_VAR_state_key or -backend-config
    # region         = var.aws_region
    # dynamodb_table = var.lock_table

    # Security settings (static)
    encrypt = true

    # KMS encryption (optional but recommended)
    # kms_key_id = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
  }
}

# Example backend configuration file (backend.hcl):
# Create a file named backend.hcl with:
#
# bucket         = "your-terraform-state-bucket"
# key            = "pypaas/prod/terraform.tfstate"
# region         = "us-east-1"
# dynamodb_table = "terraform-locks"
# encrypt        = true
#
# Then initialize with:
# terraform init -backend-config=backend.hcl

# For different environments, use workspaces:
# terraform workspace new dev
# terraform workspace new staging
# terraform workspace new prod
# terraform workspace select prod
