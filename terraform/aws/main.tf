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

# main.tf - update user_data
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

# Clone repo (replace with your actual repo)
git clone https://github.com/AlinaSHforwork/git-deploy-healer.git .

# Create .env from template
cp .env.example .env

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
