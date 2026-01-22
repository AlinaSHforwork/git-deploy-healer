# core/security.py
"""Security validation utilities for production deployments."""
import logging
import os
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Known test/weak credentials that should never be used in production
FORBIDDEN_CREDENTIALS = {
    "test-key",
    "test-api-key",
    "test-webhook-secret",
    "dev-api-key",
    "your-secret-api-key-here",
    "your-webhook-secret",
    "your-jwt-secret-here",
    "secret",
    "password",
    "admin",
    "123456",
}


def validate_credential_strength(
    credential: str, min_length: int = 32
) -> Tuple[bool, List[str]]:
    """
    Validate credential meets minimum security requirements.

    Args:
        credential: The credential to validate
        min_length: Minimum required length (default 32 for API keys)

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    if not credential:
        issues.append("Credential is empty")
        return False, issues

    # Check length
    if len(credential) < min_length:
        issues.append(f"Credential too short (minimum {min_length} characters)")

    # Check against forbidden list
    if credential.lower() in FORBIDDEN_CREDENTIALS:
        issues.append("Using forbidden test/weak credential")

    # Check for common patterns
    if re.match(r'^[a-z]+$', credential.lower()):
        issues.append(
            "Credential contains only letters (should include numbers/symbols)"
        )

    # Check entropy (basic check)
    unique_chars = len(set(credential))
    if unique_chars < 10:
        issues.append("Credential has low entropy (too few unique characters)")

    return len(issues) == 0, issues


def validate_production_secrets() -> Tuple[bool, List[str]]:
    """
    Validate all production secrets are properly configured.

    Returns:
        Tuple of (all_valid, list_of_all_issues)
    """
    all_issues = []
    deployment_mode = os.getenv("DEPLOYMENT_MODE", "local").lower()

    # Skip validation in test mode
    if os.getenv("TESTING") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        return True, []

    # API Key validation
    api_key = os.getenv("API_KEY")
    if api_key:
        is_valid, issues = validate_credential_strength(api_key, min_length=32)
        if not is_valid:
            all_issues.extend([f"API_KEY: {issue}" for issue in issues])
    else:
        all_issues.append("API_KEY is not set")

    # Webhook secret validation
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if webhook_secret:
        is_valid, issues = validate_credential_strength(webhook_secret, min_length=32)
        if not is_valid:
            all_issues.extend([f"GITHUB_WEBHOOK_SECRET: {issue}" for issue in issues])
    else:
        all_issues.append("GITHUB_WEBHOOK_SECRET is not set")

    # JWT secret validation (if JWT is enabled)
    jwt_secret = os.getenv("JWT_SECRET")
    if jwt_secret:
        is_valid, issues = validate_credential_strength(jwt_secret, min_length=32)
        if not is_valid:
            all_issues.extend([f"JWT_SECRET: {issue}" for issue in issues])

    # Database URL validation for production
    if deployment_mode == "aws":
        db_url = os.getenv("DATABASE_URL", "")
        if "sqlite" in db_url.lower():
            all_issues.append(
                "DATABASE_URL: SQLite not recommended for production (use PostgreSQL)"
            )
        if not db_url:
            all_issues.append("DATABASE_URL is not set for AWS deployment")

    return len(all_issues) == 0, all_issues


def check_secrets_on_startup(strict: bool = False) -> None:
    """
    Check secrets on application startup and log warnings/errors.

    Args:
        strict: If True, raise exception on validation failure

    Raises:
        ValueError: If strict=True and validation fails
    """
    from loguru import logger as loguru_logger

    is_valid, issues = validate_production_secrets()

    if not is_valid:
        error_msg = "SECURITY VALIDATION FAILED - WEAK OR TEST CREDENTIALS DETECTED"
        logger.error("=" * 80)
        logger.error(error_msg)
        logger.error("=" * 80)
        loguru_logger.error("=" * 80)
        loguru_logger.error(error_msg)
        loguru_logger.error("=" * 80)
        for issue in issues:
            logger.error(f"  - {issue}")
            loguru_logger.error(f"  - {issue}")
        logger.error("")
        loguru_logger.error("")
        logger.error("To fix:")
        logger.error("  1. Generate strong secrets:")
        logger.error(
            "     python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
        logger.error("  2. Update your .env file with the new secrets")
        logger.error("  3. Never use test credentials in production")
        logger.error("=" * 80)
        loguru_logger.error("To fix:")
        loguru_logger.error("  1. Generate strong secrets:")
        loguru_logger.error(
            "     python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
        loguru_logger.error("  2. Update your .env file with the new secrets")
        loguru_logger.error("  3. Never use test credentials in production")
        loguru_logger.error("=" * 80)

        if strict:
            raise ValueError(
                f"Security validation failed: {len(issues)} issue(s) found. "
                "Fix secrets before deploying to production."
            )
