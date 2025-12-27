"""Universal SecretsManager supporting local (.env) and AWS Secrets Manager.

The class intentionally avoids hard failures when optional deps are missing so tests
and local development remain simple.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from loguru import logger

try:
    load_dotenv()
except Exception as e:  # pragma: no cover
    logger.warning(f"Failed to load .env file: {e}")


try:  # optional import for AWS mode
    import boto3  # type: ignore
except Exception:  # pragma: no cover - optional
    boto3 = None  # type: ignore


class SecretsManager:
    """
    Dual‑mode secrets manager:
    - local: loads from .env
    - aws: loads from AWS SSM Parameter Store
    """

    def __init__(self, mode: str = "local"):
        self.mode = mode.lower().strip()
        self._cache: Dict[str, str] = {}

        if self.mode == "local":
            self._load_local_env()
        elif self.mode == "aws":
            self._init_aws()
        else:
            raise ValueError(f"Unknown secrets mode: {self.mode}")

    # -------------------------
    # LOCAL MODE
    # -------------------------
    def _load_local_env(self) -> None:
        env_path = Path(".env")
        if not env_path.exists():
            raise FileNotFoundError(
                ".env file not found. Copy .env.example to .env and fill in values."
            )
        load_dotenv(env_path)

    # -------------------------
    # AWS MODE
    # -------------------------
    def _init_aws(self) -> None:
        if boto3 is None:
            raise RuntimeError("boto3 is required for AWS secrets mode")
        self.ssm = boto3.client("ssm")

    def _get_aws_secret(self, key: str) -> Optional[str]:
        try:
            response = self.ssm.get_parameter(
                Name=key,
                WithDecryption=True,
            )
            return response.get("Parameter", {}).get("Value")
        except Exception:
            return None

    # -------------------------
    # PUBLIC API
    # -------------------------
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Cache hit
        if key in self._cache:
            return self._cache[key]

        # Load from correct backend
        if self.mode == "local":
            value = os.getenv(key)
        else:
            value = self._get_aws_secret(key)

        # Cache only non-empty values
        if value:
            self._cache[key] = value
            return value

        # Return default if provided
        return default
