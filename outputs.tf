# outputs.tf

output "alb_dns_name" {
  value       = aws_lb.pypaas_alb.dns_name
  description = "DNS name of the ALB"
}

output "instance_profile_arn" {
  value = aws_iam_instance_profile.pypaas_profile.arn
}