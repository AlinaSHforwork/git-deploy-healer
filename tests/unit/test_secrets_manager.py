from unittest.mock import MagicMock

import pytest

from core.secrets_manager import SecretsManager

# -------------------------
# LOCAL MODE TESTS
# -------------------------


def test_local_env_load(tmp_path, monkeypatch):
    # Create a temporary .env file
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY=123\n")

    monkeypatch.chdir(tmp_path)

    sm = SecretsManager(mode="local")
    assert sm.get_secret("TEST_KEY") == "123"


def test_local_env_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        SecretsManager(mode="local")


def test_local_secret_default(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")  # empty env
    monkeypatch.chdir(tmp_path)

    sm = SecretsManager("local")
    assert sm.get_secret("MISSING", default="fallback") == "fallback"


def test_local_cache(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CACHED=abc\n")
    monkeypatch.chdir(tmp_path)

    sm = SecretsManager("local")
    first = sm.get_secret("CACHED")
    second = sm.get_secret("CACHED")  # should hit cache
    assert first == second == "abc"


# -------------------------
# AWS MODE TESTS
# -------------------------


def test_aws_mode_requires_boto3(monkeypatch):
    monkeypatch.setattr("core.secrets_manager.boto3", None)
    with pytest.raises(RuntimeError):
        SecretsManager(mode="aws")


def test_aws_secret_success(monkeypatch):
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "secret-value"}}

    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_ssm

    monkeypatch.setattr("core.secrets_manager.boto3", mock_boto3)

    sm = SecretsManager("aws")
    assert sm.get_secret("MY_KEY") == "secret-value"


def test_aws_secret_failure(monkeypatch):
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.side_effect = Exception("boom")

    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_ssm

    monkeypatch.setattr("core.secrets_manager.boto3", mock_boto3)

    sm = SecretsManager("aws")
    assert sm.get_secret("MISSING") is None


# -------------------------
# INVALID MODE
# -------------------------


def test_invalid_mode():
    with pytest.raises(ValueError):
        SecretsManager("invalid")
