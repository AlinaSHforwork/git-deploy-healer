# **PyPaaS – Git Deploy Healer**

[![CI/CD](https://github.com/AlinaSHforwork/git-deploy-healer/actions/workflows/ci.yml/badge.svg)](https://github.com/AlinaSHforwork/git-deploy-healer/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

PyPaaS is a lightweight, developer‑friendly Platform‑as‑a‑Service engine that automates deployments from Git repositories. It builds Docker images, deploys containers, updates Nginx routing, and includes a self‑healing daemon to restart unhealthy apps. Inspired by Heroku and Kubernetes, PyPaaS brings Git‑Ops workflows, observability, and cloud‑ready infrastructure — without the complexity.

Ideal for:
- local development PaaS
- self‑hosted mini‑cloud
- DevOps learning projects
- deployment automation demos

---

## **Features**

- **Automated Git Deployments**
  Webhook‑driven builds and deploys from GitHub/GitLab.

- **Zero‑Downtime Routing**
  Nginx reverse proxy updates with atomic config swaps.

- **Self‑Healing Engine**
  Background daemon detects unhealthy containers and restarts them.

- **Observability**
  Prometheus metrics for deploys, restarts, and active apps.

- **CLI Tooling**
  Manual deploys via `main.py`.

- **Cloud‑Ready IaC**
  Terraform modules for AWS (VPC, ALB, ASG, IAM, multi‑AZ).

- **CI/CD Pipeline**
  GitHub Actions for linting, testing, Docker builds, security scans, and Terraform validation.

- **Security**
  API key authentication, non‑root Docker runs, restricted security groups.

- **Extensible**
  `.env`‑based configuration, pluggable secrets manager (local or AWS SSM), dynamic port detection.

---

## **Architecture**

PyPaaS runs as a FastAPI service (port `8085`) with background tasks for deployments and healing. Terraform optionally provisions scalable AWS infrastructure.

```mermaid
flowchart TD
    A[Git Webhook Push Event] -->|Triggers| B[FastAPI Server /webhook]
    B -->|Validates & Queues| C[Background Deployment Task]
    C --> D[Git Manager: Clone/Update Repo]
    D --> E[Container Engine: Build Docker Image]
    E --> F[Deploy Container: Run with Ports/Labels]
    F --> G[Proxy Manager: Update Nginx Config]
    G -->|Routes Traffic| H[Running Containers]
    I[Healer Daemon] -->|Periodic Check| J[Detect Unhealthy Containers]
    J -->|Restart/Recreate| F
    K[ALB] -->|Forward to 8085| L[ASG EC2 Instances]
    L --> B

    subgraph LocalHost
        B
        C
        D
        E
        F
        G
        H
        I
        J
    end

    subgraph Cloud
        K
        L
    end

```

---

## **Tech Stack**

- **Backend:** Python 3.12, FastAPI, Uvicorn
- **DevOps:** Docker SDK, GitPython, Prometheus, Loguru
- **Infra:** Nginx, Terraform, AWS (optional)
- **CI/CD:** GitHub Actions, Pytest, Flake8, Trivy

---

## **Prerequisites**

- Python 3.12+
- Docker Engine
- Git
- Nginx (for routing)
- Terraform (optional, for AWS)
- AWS account (optional)

---

## **Local Setup**

### 1. Clone the repository
```bash
git clone https://github.com/AlinaSHforwork/git-deploy-healer.git
cd git-deploy-healer
```

### 2. Create your `.env`
```env
DEPLOYMENT_MODE=local
DATABASE_URL=sqlite:///./local.db
API_KEY=dev-api-key
GITHUB_WEBHOOK_SECRET=dev-webhook-secret
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the server
```bash
uvicorn api.server:app --host 0.0.0.0 --port 8085
```

- API Docs: http://localhost:8085/docs
- Health Check: http://localhost:8085/health
- Metrics: http://localhost:8085/metrics

### 5. Deploy a sample app
Use the included example:

```bash
python main.py my-webapp repos/my-webapp
```

Or simulate a webhook:

```json
{
  "repository": {
    "name": "my-webapp",
    "clone_url": "path/to/repo"
  }
}
```

### 6. Nginx proxy setup
Configure subdomain routing (e.g., `myapp.localhost`).
See `core/proxy_manager.py` for generated config templates.

### 7. Run tests
```bash
pytest --cov
flake8 .
```

---

## **Cloud Deployment (AWS)**

Terraform provisions:

- VPC + subnets
- ALB
- Auto Scaling Group (1–3 EC2 instances)
- IAM roles
- Security groups

### 1. Initialize Terraform
```bash
terraform init
```

### 2. Plan & apply
```bash
terraform plan
terraform apply
```

### 3. Provision EC2 instances
Using Ansible:
```bash
ansible-playbook ansible/provision.yml -i <ec2-ip>,
```

### 4. Access
- Dashboard: `http://<alb-dns>/`
- SSH:
  ```bash
  ssh -i ~/.ssh/id_rsa ubuntu@<ec2-ip>
  ```

### 5. Destroy
```bash
terraform destroy
```

---

## **CI/CD Pipeline**

GitHub Actions includes:

- Linting (Flake8)
- Testing (Pytest + Coverage)
- Docker build
- Security scan (Trivy)
- Terraform validate/plan

Secrets stored in repo settings:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `CODECOV_TOKEN` (optional)

---

## **Production Hardening**

- Enable HTTPS (ACM + ALB)
- Restrict IP ranges
- Use AWS SSM or Vault for secrets
- Add autoscaling policies
- Export metrics to Grafana/CloudWatch
- Add alerting for healer restarts
- Use Terraform workspaces for dev/staging/prod

---

## **Troubleshooting**

- **Docker build fails** → check Dockerfile in app repo
- **Container not running** → `docker logs <id>`
- **Webhook errors** → validate payload + clone URL
- **Terraform issues** → `terraform validate`

---

## **License**

MIT License — see [LICENSE](LICENSE).
