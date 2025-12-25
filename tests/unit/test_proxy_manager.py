"""
Unit tests for core.proxy_manager module.
Tests Nginx proxy configuration management including config generation and reload.
"""
import subprocess
from unittest.mock import Mock, mock_open, patch

import pytest

from core.proxy_manager import ProxyManager


@pytest.fixture
def proxy_manager():
    """Fixture to create a ProxyManager instance."""
    return ProxyManager(
        nginx_config_path="/etc/nginx/sites-available",
        nginx_enabled_path="/etc/nginx/sites-enabled",
    )


@pytest.fixture
def sample_nginx_config():
    """Fixture with sample Nginx configuration."""
    return """
server {
    listen 80;
    server_name test-app.local;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
    }
}
"""


class TestProxyManagerInit:
    """Test ProxyManager initialization."""

    def test_init_default_paths(self):
        """Test initialization with default paths."""
        manager = ProxyManager()
        assert "/etc/nginx" in manager.nginx_config_path
        assert "/etc/nginx" in manager.nginx_enabled_path

    def test_init_custom_paths(self):
        """Test initialization with custom paths."""
        manager = ProxyManager(
            nginx_config_path="/custom/nginx/available",
            nginx_enabled_path="/custom/nginx/enabled",
        )
        assert manager.nginx_config_path == "/custom/nginx/available"
        assert manager.nginx_enabled_path == "/custom/nginx/enabled"

    @patch('core.proxy_manager.Path.mkdir')
    def test_init_creates_directories(self, mock_mkdir):
        """Test that initialization creates necessary directories."""
        ProxyManager(
            nginx_config_path="/new/path/available",
            nginx_enabled_path="/new/path/enabled",
        )
        assert mock_mkdir.call_count >= 2


class TestGenerateConfig:
    """Test Nginx configuration generation."""

    def test_generate_config_basic(self, proxy_manager):
        """Test basic Nginx configuration generation."""
        config = proxy_manager.generate_config(
            app_name="test-app", port=8080, domain="test-app.local"
        )

        assert "server_name test-app.local" in config
        assert "proxy_pass http://localhost:8080" in config
        assert "listen 80" in config

    def test_generate_config_with_ssl(self, proxy_manager):
        """Test Nginx configuration with SSL."""
        config = proxy_manager.generate_config(
            app_name="test-app",
            port=8080,
            domain="test-app.local",
            ssl=True,
            ssl_certificate="/etc/ssl/cert.pem",
            ssl_certificate_key="/etc/ssl/key.pem",
        )

        assert "listen 443 ssl" in config
        assert "ssl_certificate /etc/ssl/cert.pem" in config
        assert "ssl_certificate_key /etc/ssl/key.pem" in config

    def test_generate_config_with_custom_headers(self, proxy_manager):
        """Test configuration with custom proxy headers."""
        config = proxy_manager.generate_config(
            app_name="test-app",
            port=8080,
            domain="test-app.local",
            custom_headers={
                "X-Custom-Header": "value",
                "X-Another-Header": "another-value",
            },
        )

        assert "proxy_set_header X-Custom-Header value" in config
        assert "proxy_set_header X-Another-Header another-value" in config

    def test_generate_config_with_websocket_support(self, proxy_manager):
        """Test configuration with WebSocket support."""
        config = proxy_manager.generate_config(
            app_name="test-app", port=8080, domain="test-app.local", websocket=True
        )

        assert "proxy_http_version 1.1" in config
        assert "Upgrade $http_upgrade" in config
        assert "Connection" in config


class TestWriteConfig:
    """Test writing Nginx configuration to file."""

    @patch('builtins.open', new_callable=mock_open)
    @patch('core.proxy_manager.Path.exists')
    def test_write_config_success(
        self, mock_exists, mock_file, proxy_manager, sample_nginx_config
    ):
        """Test successfully writing configuration to file."""
        mock_exists.return_value = False

        proxy_manager.write_config("test-app", sample_nginx_config)

        expected_path = f"{proxy_manager.nginx_config_path}/test-app"
        mock_file.assert_called_once_with(expected_path, 'w')
        mock_file().write.assert_called_once_with(sample_nginx_config)

    @patch('builtins.open', new_callable=mock_open)
    @patch('core.proxy_manager.Path.exists')
    def test_write_config_overwrite(
        self, mock_exists, mock_file, proxy_manager, sample_nginx_config
    ):
        """Test overwriting existing configuration."""
        mock_exists.return_value = True

        proxy_manager.write_config("test-app", sample_nginx_config, overwrite=True)

        mock_file().write.assert_called_once()

    @patch('core.proxy_manager.Path.exists')
    def test_write_config_no_overwrite(
        self, mock_exists, proxy_manager, sample_nginx_config
    ):
        """Test not overwriting existing configuration when overwrite=False."""
        mock_exists.return_value = True

        with pytest.raises(FileExistsError):
            proxy_manager.write_config("test-app", sample_nginx_config, overwrite=False)

    @patch('builtins.open', new_callable=mock_open)
    @patch('core.proxy_manager.Path.exists')
    def test_write_config_permission_error(
        self, mock_exists, mock_file, proxy_manager, sample_nginx_config
    ):
        """Test handling permission errors when writing config."""
        mock_exists.return_value = False
        mock_file.side_effect = PermissionError("Permission denied")

        with pytest.raises(PermissionError):
            proxy_manager.write_config("test-app", sample_nginx_config)


class TestEnableConfig:
    """Test enabling Nginx configuration (creating symlink)."""

    @patch('core.proxy_manager.Path.symlink_to')
    @patch('core.proxy_manager.Path.exists')
    def test_enable_config_success(self, mock_exists, mock_symlink, proxy_manager):
        """Test successfully enabling configuration."""
        mock_exists.side_effect = [True, False]  # available exists, enabled doesn't

        proxy_manager.enable_config("test-app")

        mock_symlink.assert_called_once()

    @patch('core.proxy_manager.Path.exists')
    def test_enable_config_already_enabled(self, mock_exists, proxy_manager):
        """Test enabling already enabled configuration."""
        mock_exists.side_effect = [True, True]  # Both available and enabled exist

        # Should not raise error
        proxy_manager.enable_config("test-app")

    @patch('core.proxy_manager.Path.exists')
    def test_enable_config_not_found(self, mock_exists, proxy_manager):
        """Test enabling non-existent configuration."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError):
            proxy_manager.enable_config("nonexistent-app")


class TestDisableConfig:
    """Test disabling Nginx configuration (removing symlink)."""

    @patch('core.proxy_manager.Path.unlink')
    @patch('core.proxy_manager.Path.exists')
    def test_disable_config_success(self, mock_exists, mock_unlink, proxy_manager):
        """Test successfully disabling configuration."""
        mock_exists.return_value = True

        proxy_manager.disable_config("test-app")

        mock_unlink.assert_called_once()

    @patch('core.proxy_manager.Path.exists')
    def test_disable_config_not_enabled(self, mock_exists, proxy_manager):
        """Test disabling non-enabled configuration."""
        mock_exists.return_value = False

        # Should not raise error
        proxy_manager.disable_config("test-app")


class TestRemoveConfig:
    """Test removing Nginx configuration."""

    @patch('core.proxy_manager.Path.unlink')
    @patch('core.proxy_manager.Path.exists')
    def test_remove_config_success(self, mock_exists, mock_unlink, proxy_manager):
        """Test successfully removing configuration."""
        mock_exists.side_effect = [True, True]  # Both available and enabled exist

        proxy_manager.remove_config("test-app")

        assert mock_unlink.call_count == 2  # Both files removed

    @patch('core.proxy_manager.Path.exists')
    def test_remove_config_not_found(self, mock_exists, proxy_manager):
        """Test removing non-existent configuration."""
        mock_exists.return_value = False

        # Should not raise error
        proxy_manager.remove_config("test-app")

    @patch('core.proxy_manager.Path.unlink')
    @patch('core.proxy_manager.Path.exists')
    def test_remove_config_only_available(
        self, mock_exists, mock_unlink, proxy_manager
    ):
        """Test removing when only available config exists."""
        mock_exists.side_effect = [True, False]

        proxy_manager.remove_config("test-app")

        mock_unlink.assert_called_once()


class TestReloadNginx:
    """Test Nginx reload functionality."""

    @patch('core.proxy_manager.subprocess.run')
    def test_reload_nginx_success(self, mock_run, proxy_manager):
        """Test successful Nginx reload."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        result = proxy_manager.reload_nginx()

        mock_run.assert_called_once()
        assert "nginx" in mock_run.call_args[0][0][0].lower()
        assert result is True

    @patch('core.proxy_manager.subprocess.run')
    def test_reload_nginx_failure(self, mock_run, proxy_manager):
        """Test handling of Nginx reload failure."""
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="nginx: configuration file test failed"
        )

        result = proxy_manager.reload_nginx()

        assert result is False

    @patch('core.proxy_manager.subprocess.run')
    def test_reload_nginx_command_not_found(self, mock_run, proxy_manager):
        """Test handling when nginx command is not found."""
        mock_run.side_effect = FileNotFoundError("nginx: command not found")

        with pytest.raises(FileNotFoundError):
            proxy_manager.reload_nginx()

    @patch('core.proxy_manager.subprocess.run')
    def test_reload_nginx_timeout(self, mock_run, proxy_manager):
        """Test handling of Nginx reload timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("nginx", 30)

        with pytest.raises(subprocess.TimeoutExpired):
            proxy_manager.reload_nginx()


class TestTestNginxConfig:
    """Test Nginx configuration testing."""

    @patch('core.proxy_manager.subprocess.run')
    def test_test_config_valid(self, mock_run, proxy_manager):
        """Test validating correct Nginx configuration."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="nginx: configuration file test is successful",
            stderr="",
        )

        result = proxy_manager.test_nginx_config()

        assert result is True
        assert "test" in mock_run.call_args[0][0] or "-t" in mock_run.call_args[0][0]

    @patch('core.proxy_manager.subprocess.run')
    def test_test_config_invalid(self, mock_run, proxy_manager):
        """Test validating invalid Nginx configuration."""
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="nginx: [emerg] unexpected '}'"
        )

        result = proxy_manager.test_nginx_config()

        assert result is False


class TestListConfigs:
    """Test listing Nginx configurations."""

    @patch('core.proxy_manager.Path.iterdir')
    def test_list_configs(self, mock_iterdir, proxy_manager):
        """Test listing all available configurations."""
        mock_files = [
            Mock(is_file=lambda: True, name="app1"),
            Mock(is_file=lambda: True, name="app2"),
            Mock(is_file=lambda: False, name="subdir"),
        ]
        mock_iterdir.return_value = mock_files

        configs = proxy_manager.list_configs()

        assert len(configs) == 2
        assert "app1" in configs
        assert "app2" in configs

    @patch('core.proxy_manager.Path.iterdir')
    def test_list_configs_empty(self, mock_iterdir, proxy_manager):
        """Test listing when no configurations exist."""
        mock_iterdir.return_value = []

        configs = proxy_manager.list_configs()

        assert configs == []


class TestReadConfig:
    """Test reading Nginx configuration."""

    @patch('builtins.open', new_callable=mock_open, read_data="server { listen 80; }")
    @patch('core.proxy_manager.Path.exists')
    def test_read_config_success(self, mock_exists, mock_file, proxy_manager):
        """Test successfully reading configuration."""
        mock_exists.return_value = True

        config = proxy_manager.read_config("test-app")

        assert "server" in config
        assert "listen 80" in config

    @patch('core.proxy_manager.Path.exists')
    def test_read_config_not_found(self, mock_exists, proxy_manager):
        """Test reading non-existent configuration."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError):
            proxy_manager.read_config("nonexistent-app")


class TestUpdateConfig:
    """Test updating existing Nginx configuration."""

    @patch('builtins.open', new_callable=mock_open)
    @patch('core.proxy_manager.Path.exists')
    def test_update_config_success(self, mock_exists, mock_file, proxy_manager):
        """Test successfully updating configuration."""
        mock_exists.return_value = True
        new_config = "server { listen 8080; }"

        proxy_manager.update_config("test-app", new_config)

        mock_file().write.assert_called_once_with(new_config)

    @patch('core.proxy_manager.Path.exists')
    def test_update_config_not_found(self, mock_exists, proxy_manager):
        """Test updating non-existent configuration."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError):
            proxy_manager.update_config("nonexistent-app", "new config")


class TestIntegration:
    """Integration tests combining multiple operations."""

    @patch('core.proxy_manager.subprocess.run')
    @patch('core.proxy_manager.Path.symlink_to')
    @patch('builtins.open', new_callable=mock_open)
    @patch('core.proxy_manager.Path.exists')
    def test_full_deployment_workflow(
        self, mock_exists, mock_file, mock_symlink, mock_run, proxy_manager
    ):
        """Test complete workflow: generate, write, enable, reload."""
        mock_exists.side_effect = [
            False,
            True,
            False,
        ]  # Not exists, then available, not enabled
        mock_run.return_value = Mock(returncode=0)

        # Generate config
        config = proxy_manager.generate_config(
            app_name="test-app", port=8080, domain="test-app.local"
        )

        # Write config
        proxy_manager.write_config("test-app", config)

        # Enable config
        proxy_manager.enable_config("test-app")

        # Reload Nginx
        result = proxy_manager.reload_nginx()

        assert "test-app" in config
        mock_file().write.assert_called_once()
        mock_symlink.assert_called_once()
        assert result is True

    @patch('core.proxy_manager.subprocess.run')
    @patch('core.proxy_manager.Path.unlink')
    @patch('core.proxy_manager.Path.exists')
    def test_removal_workflow(self, mock_exists, mock_unlink, mock_run, proxy_manager):
        """Test complete removal workflow: disable, remove, reload."""
        mock_exists.return_value = True
        mock_run.return_value = Mock(returncode=0)

        # Disable config
        proxy_manager.disable_config("test-app")

        # Remove config
        proxy_manager.remove_config("test-app")

        # Reload Nginx
        result = proxy_manager.reload_nginx()

        assert mock_unlink.call_count >= 2  # Disable + Remove
        assert result is True

    @patch('core.proxy_manager.subprocess.run')
    @patch('builtins.open', new_callable=mock_open)
    @patch('core.proxy_manager.Path.exists')
    def test_update_and_reload_workflow(
        self, mock_exists, mock_file, mock_run, proxy_manager
    ):
        """Test update configuration and reload workflow."""
        mock_exists.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0),  # Test config
            Mock(returncode=0),  # Reload
        ]

        # Update config
        new_config = "server { listen 9090; }"
        proxy_manager.update_config("test-app", new_config)

        # Test config
        test_result = proxy_manager.test_nginx_config()

        # Reload if test passes
        if test_result:
            reload_result = proxy_manager.reload_nginx()

        assert test_result is True
        assert reload_result is True
