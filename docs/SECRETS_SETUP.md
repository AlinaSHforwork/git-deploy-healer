# Secrets Setup

This project supports two secrets modes: `local` and `aws`.

Local (recommended for development)

1. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
# edit .env and fill values
```

2. Use the `SecretsManager` in code:

```python
from core.secrets_manager import SecretsManager
sm = SecretsManager('local')
print(sm.get_secret('API_KEY'))
```

AWS (optional)

1. Set `DEPLOYMENT_MODE=aws` in env or pass `SecretsManager('aws')`.
2. Ensure the IAM permissions for `secretsmanager:GetSecretValue`.

Testing examples

Local mode:

```bash
cp .env.example .env
python -c "from core.secrets_manager import SecretsManager; print(SecretsManager('local').get_secret('API_KEY'))"
```

AWS mode (requires credentials):

```bash
export DEPLOYMENT_MODE=aws
python -c "from core.secrets_manager import SecretsManager; print(SecretsManager('aws').get_secret('API_KEY'))"
```
# Secrets Setup Guide

This project supports two modes for managing secrets:

- **Local mode** (default)
- **AWS mode** (production)

---

## Local Mode

Local mode loads secrets from a `.env` file.

### Steps

1. Copy the example file:

```bash
   cp .env.example .env
```

2. Fill in your secrets inside .env.

3. Test:

```bash
    python -c "from core.secrets_manager import SecretsManager; sm = SecretsManager('local'); print(sm.get_secret('API_KEY'))"
```

## AWS Mode

AWS mode loads secrets from AWS SSM Parameter Store.

Requirements:
- AWS credentials configured (aws configure)
- Parameters stored in SSM (e.g. /pypaas/API_KEY)

Test:
```bash
    export DEPLOYMENT_MODE=aws
python -c "from core.secrets_manager import SecretsManager; sm = SecretsManager('aws'); print(sm.get_secret('API_KEY'))"
```

 ## Switching Modes
The mode is controlled by:

- .env → DEPLOYMENT_MODE=local

-  or environment variable:

```bash
export DEPLOYMENT_MODE=aws
```
## Notes

- Secrets are cached in memory for performance.

- AWS mode requires boto3.

- Local mode requires .env and python-dotenv.
