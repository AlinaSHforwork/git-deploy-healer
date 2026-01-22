# tests/unit/test_security.py
"""Tests for security validation module."""
import pytest

from core.security import (
    FORBIDDEN_CREDENTIALS,
    check_secrets_on_startup,
    validate_credential_strength,
    validate_production_secrets,
)


class TestCredentialStrengthValidation:
    """Test credential strength validation."""

    def test_strong_credential_passes(self):
        """Test that strong credentials pass validation."""
        strong_cred = "aB3$xK9#mP2@vL7&qR5!wT8^nH4*jF6_"
        is_valid, issues = validate_credential_strength(strong_cred)
        assert is_valid
        assert len(issues) == 0

    def test_empty_credential_fails(self):
        """Test that empty credentials fail."""
        is_valid, issues = validate_credential_strength("")
        assert not is_valid
        assert "empty" in issues[0].lower()

    def test_short_credential_fails(self):
        """Test that short credentials fail."""
        is_valid, issues = validate_credential_strength("short", min_length=32)
        assert not is_valid
        assert any("too short" in issue.lower() for issue in issues)

    def test_forbidden_credential_fails(self):
        """Test that forbidden credentials fail."""
        for forbidden in FORBIDDEN_CREDENTIALS:
            is_valid, issues = validate_credential_strength(forbidden)
            assert not is_valid
            assert any("forbidden" in issue.lower() for issue in issues)

    def test_only_letters_fails(self):
        """Test that credentials with only letters fail."""
        is_valid, issues = validate_credential_strength("onlylettershere" * 3)
        assert not is_valid
        assert any("only letters" in issue.lower() for issue in issues)

    def test_low_entropy_fails(self):
        """Test that low entropy credentials fail."""
        is_valid, issues = validate_credential_strength(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        assert not is_valid
        assert any("entropy" in issue.lower() for issue in issues)


class TestProductionSecretsValidation:
    """Test production secrets validation."""

    def test_validation_skipped_in_test_mode(self, monkeypatch):
        """Test that validation is skipped when TESTING=1."""
        monkeypatch.setenv("TESTING", "1")
        is_valid, issues = validate_production_secrets()
        assert is_valid
        assert len(issues) == 0

    def test_missing_api_key_fails(self, monkeypatch):
        """Test that missing API_KEY fails validation."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)

        is_valid, issues = validate_production_secrets()
        assert not is_valid
        assert any("API_KEY" in issue for issue in issues)

    def test_weak_api_key_fails(self, monkeypatch):
        """Test that weak API_KEY fails validation."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("API_KEY", "test-key")

        is_valid, issues = validate_production_secrets()
        assert not is_valid
        assert any(
            "API_KEY" in issue and "forbidden" in issue.lower() for issue in issues
        )

    def test_sqlite_in_aws_mode_fails(self, monkeypatch):
        """Test that SQLite fails in AWS mode."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("DEPLOYMENT_MODE", "aws")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./local.db")
        monkeypatch.setenv("API_KEY", "a" * 32 + "B3$")
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "b" * 32 + "C4%")

        is_valid, issues = validate_production_secrets()
        assert not is_valid
        assert any("sqlite" in issue.lower() for issue in issues)

    def test_strong_credentials_pass(self, monkeypatch):
        """Test that strong credentials pass validation."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("API_KEY", "aB3$xK9#mP2@vL7&qR5!wT8^nH4*jF6$")
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "cD5%yM1!nQ3@pS7&rV9#tX2^wZ4*hB8$")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

        is_valid, issues = validate_production_secrets()
        assert is_valid
        assert len(issues) == 0


class TestStartupValidation:
    """Test startup validation behavior."""

    def test_startup_check_passes_in_test_mode(self, monkeypatch):
        """Test that startup check passes in test mode."""
        monkeypatch.setenv("TESTING", "1")
        # Should not raise
        check_secrets_on_startup(strict=True)

    def test_startup_check_raises_in_strict_mode(self, monkeypatch):
        """Test that startup check raises in strict mode with weak credentials."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("API_KEY", "test-key")

        with pytest.raises(ValueError, match="Security validation failed"):
            check_secrets_on_startup(strict=True)

    def test_startup_check_warns_in_non_strict_mode(self, monkeypatch, caplog):
        """Test that startup check logs warnings in non-strict mode."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("API_KEY", "test-key")

        # Should not raise in non-strict mode
        check_secrets_on_startup(strict=False)

        # Should have logged errors
        assert any(
            "SECURITY VALIDATION FAILED" in record.message for record in caplog.records
        )
