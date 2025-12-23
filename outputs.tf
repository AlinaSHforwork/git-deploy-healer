# outputs.tf

output "pypaas_host_public_ip" {
  description = "The public IP address of the PyPaaS host."
  value       = aws_instance.pypaas_host.public_ip
}

output "ssh_command" {
  description = "SSH command to connect to the instance."
  value       = "ssh -i <YOUR_PRIVATE_KEY> ubuntu@${aws_instance.pypaas_host.public_ip}"
}