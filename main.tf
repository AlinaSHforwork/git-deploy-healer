# main.tf

# 1. AWS Provider Configuration
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Remote state backend for collaboration/CI
  backend "s3" {
    bucket         = "your-terraform-state-bucket"  # Replace with your S3 bucket
    key            = "pypaas/terraform.tfstate"
    region         = "us-east-1"  # Replace with your region
    dynamodb_table = "terraform-locks"  # Replace with your DynamoDB table for locking
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables (expanded for flexibility)
variable "aws_region" { default = "us-east-1" }
variable "ami_id" { default = "ami-0abcdef1234567890" }  # Replace with actual AMI
variable "instance_type" { default = "t3.micro" }
variable "public_key_path" { default = "~/.ssh/id_rsa.pub" }
variable "allowed_ips" {
  type        = list(string)
  default     = ["203.0.113.0/24"]  # Restrict to your IP/CIDR by default
  description = "List of CIDR blocks allowed for SSH and HTTP/HTTPS access"
}
variable "min_instances" { default = 1 }
variable "max_instances" { default = 3 }
variable "desired_capacity" { default = 1 }

# 2. Key Pair (for SSH)
resource "aws_key_pair" "deployer_key" {
  key_name   = "pypaas-deployer-key"
  public_key = file(var.public_key_path)
}

# 3. Networking (VPC, Multi-AZ Subnets)
resource "aws_vpc" "pypaas_vpc" {
  cidr_block = "10.0.0.0/16"
  tags = { Name = "pypaas-vpc" }
}

resource "aws_subnet" "pypaas_subnet_a" {
  vpc_id                  = aws_vpc.pypaas_vpc.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true
  tags = { Name = "pypaas-subnet-a" }
}

resource "aws_subnet" "pypaas_subnet_b" {
  vpc_id                  = aws_vpc.pypaas_vpc.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = true
  tags = { Name = "pypaas-subnet-b" }
}

# 4. Internet Gateway
resource "aws_internet_gateway" "pypaas_igw" {
  vpc_id = aws_vpc.pypaas_vpc.id
}

# 5. Route Table
resource "aws_route_table" "pypaas_route_table" {
  vpc_id = aws_vpc.pypaas_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.pypaas_igw.id
  }
}

resource "aws_route_table_association" "pypaas_rta_a" {
  subnet_id      = aws_subnet.pypaas_subnet_a.id
  route_table_id = aws_route_table.pypaas_route_table.id
}

resource "aws_route_table_association" "pypaas_rta_b" {
  subnet_id      = aws_subnet.pypaas_subnet_b.id
  route_table_id = aws_route_table.pypaas_route_table.id
}

# 6. Security Group (with ALB ingress)
resource "aws_security_group" "pypaas_sg" {
  vpc_id = aws_vpc.pypaas_vpc.id

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips
  }

  ingress {
    description = "PyPaaS API/Dashboard (from ALB)"
    from_port   = 8085
    to_port     = 8085
    protocol    = "tcp"
    security_groups = [aws_security_group.pypaas_alb_sg.id]  # Restrict to ALB
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "pypaas-security-group" }
}

# ALB Security Group (public access)
resource "aws_security_group" "pypaas_alb_sg" {
  vpc_id = aws_vpc.pypaas_vpc.id

  ingress {
    description = "HTTP access"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips  # Or ["0.0.0.0/0"] for public
  }

  ingress {
    description = "HTTPS access"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "pypaas-alb-security-group" }
}

# 7. IAM Role for EC2 (example: SSM access)
resource "aws_iam_role" "pypaas_ec2_role" {
  name = "pypaas-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "pypaas_ssm" {
  role       = aws_iam_role.pypaas_ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_launch_template" "pypaas_lt" {
  name          = "pypaas-launch-template"
  image_id      = var.ami_id
  instance_type = var.instance_type
  key_name      = aws_key_pair.deployer_key.key_name
  iam_instance_profile { name = aws_iam_instance_profile.pypaas_profile.name }
  vpc_security_group_ids = [aws_security_group.pypaas_sg.id]
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # REPLACE THE EMPTY user_data WITH THIS:
  user_data = base64encode(<<EOF
#!/bin/bash
set -e

# Update system
apt-get update
apt-get install -y docker.io python3-pip git

# Add ubuntu to docker group
usermod -aG docker ubuntu

# Install docker-compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p /opt/pypaas
cd /opt/pypaas

# Clone repo
git clone https://github.com/AlinaSHforwork/git-deploy-healer.git .

# Create .env
cp .env.example .env
# TODO: Populate .env with secrets from Parameter Store

# Install Python deps
pip3 install -r requirements.txt

# Create systemd service
cat > /etc/systemd/system/pypaas.service <<'SERVICE'
[Unit]
Description=PyPaaS Service
After=network.target docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/pypaas
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/local/bin/uvicorn api.server:app --host 0.0.0.0 --port 8085
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

# Start service
systemctl daemon-reload
systemctl enable pypaas
systemctl start pypaas
EOF
  )
}

resource "aws_iam_instance_profile" "pypaas_profile" {
  name = "pypaas-ec2-profile"
  role = aws_iam_role.pypaas_ec2_role.name
}

# 8. Launch Template
resource "aws_launch_template" "pypaas_lt" {
  name          = "pypaas-launch-template"
  image_id      = var.ami_id
  instance_type = var.instance_type
  key_name      = aws_key_pair.deployer_key.key_name
  iam_instance_profile { name = aws_iam_instance_profile.pypaas_profile.name }
  vpc_security_group_ids = [aws_security_group.pypaas_sg.id]
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"  # IMDSv2 for security
    http_put_response_hop_limit = 1
  }
  user_data = base64encode(<<EOF
#!/bin/bash
# Your provisioning script here (e.g., install Docker, run Ansible)
EOF
  )
}

# 9. Auto Scaling Group
resource "aws_autoscaling_group" "pypaas_asg" {
  name                = "pypaas-asg"
  min_size            = var.min_instances
  max_size            = var.max_instances
  desired_capacity    = var.desired_capacity
  vpc_zone_identifier = [aws_subnet.pypaas_subnet_a.id, aws_subnet.pypaas_subnet_b.id]
  target_group_arns   = [aws_lb_target_group.pypaas_tg.arn]

  launch_template {
    id      = aws_launch_template.pypaas_lt.id
    version = "$Latest"
  }
}

# 10. Application Load Balancer
resource "aws_lb" "pypaas_alb" {
  name               = "pypaas-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.pypaas_alb_sg.id]
  subnets            = [aws_subnet.pypaas_subnet_a.id, aws_subnet.pypaas_subnet_b.id]
}

resource "aws_lb_target_group" "pypaas_tg" {
  name     = "pypaas-tg"
  port     = 8085
  protocol = "HTTP"
  vpc_id   = aws_vpc.pypaas_vpc.id
  health_check {
    path = "/"
    port = "8085"
  }
}

resource "aws_lb_listener" "pypaas_http" {
  load_balancer_arn = aws_lb.pypaas_alb.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.pypaas_tg.arn
  }
}

# Add HTTPS listener (requires ACM certificate)
# resource "aws_lb_listener" "pypaas_https" { ... }
