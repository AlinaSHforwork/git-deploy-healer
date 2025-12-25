# variables.tf

variable "aws_region" {
  description = "The AWS region to deploy resources into."
  type        = string
  default     = "us-east-1" # Common region, often has broadest free tier access
}

variable "ami_id" {
  description = "The AMI ID for the EC2 instance (e.g., Ubuntu 22.04 LTS)."
  type        = string
  # IMPORTANT: Replace this with a valid, current AWS free-tier AMI ID for your chosen region
  default     = "ami-053b0a79040775d1d"
}

variable "instance_type" {
  description = "The size of the EC2 instance (t2.micro is free tier)."
  type        = string
  default     = "t2.micro"
}

variable "public_key_path" {
  description = "Path to the SSH public key (.pub) to allow access to the instance."
  type        = string
}
