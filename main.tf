# main.tf

# 1. AWS Provider Configuration
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Added variable for allowed IPs
variable "allowed_ips" {
  type        = list(string)
  default     = ["0.0.0.0/0"]  # Change to your IP, e.g., ["203.0.113.0/24"]
  description = "List of CIDR blocks allowed for SSH and API access"
}

# 2. Key Pair (for SSH)
resource "aws_key_pair" "deployer_key" {
  key_name   = "pypaas-deployer-key"
  public_key = file(var.public_key_path)
}

# 3. Networking (VPC and Subnet)
resource "aws_vpc" "pypaas_vpc" {
  cidr_block = "10.0.0.0/16"
  tags = {
    Name = "pypaas-vpc"
  }
}

resource "aws_subnet" "pypaas_subnet" {
  vpc_id     = aws_vpc.pypaas_vpc.id
  cidr_block = "10.0.1.0/24"
  map_public_ip_on_launch = true # Required for public access
  tags = {
    Name = "pypaas-subnet"
  }
}

# 4. Internet Gateway (for outbound/inbound access)
resource "aws_internet_gateway" "pypaas_igw" {
  vpc_id = aws_vpc.pypaas_vpc.id
}

# 5. Route Table (directs traffic to IGW)
resource "aws_route_table" "pypaas_route_table" {
  vpc_id = aws_vpc.pypaas_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.pypaas_igw.id
  }
}

# Associate route table with subnet
resource "aws_route_table_association" "pypaas_rta" {
  subnet_id      = aws_subnet.pypaas_subnet.id
  route_table_id = aws_route_table.pypaas_route_table.id
}

# 6. Security Group (Firewall)
resource "aws_security_group" "pypaas_sg" {
  vpc_id = aws_vpc.pypaas_vpc.id

  # Inbound Rule: SSH access (port 22)
  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips 
  }

  # Inbound Rule: PyPaaS API/Dashboard (port 8085)
  ingress {
    description = "PyPaaS API/Dashboard"
    from_port   = 8085
    to_port     = 8085
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips 
  }
  
  # Outbound Rule: Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = {
    Name = "pypaas-security-group"
  }
}

# 7. EC2 Instance (The PyPaaS Host)
resource "aws_instance" "pypaas_host" {
  ami           = var.ami_id
  instance_type = var.instance_type
  key_name      = aws_key_pair.deployer_key.key_name
  subnet_id     = aws_subnet.pypaas_subnet.id
  vpc_security_group_ids = [aws_security_group.pypaas_sg.id]
  associate_public_ip_address = true

  tags = {
    Name = "PyPaaS-Engine-Host"
  }
}