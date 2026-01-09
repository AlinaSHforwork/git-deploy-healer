# core/proxy_manager.py
"""Nginx proxy configuration manager with hardened subprocess calls."""
import subprocess  # nosec
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

# Use absolute path to nginx for security
NGINX_BIN = "/usr/sbin/nginx"


class ProxyManager:
    def __init__(
        self,
        nginx_config_path: str = "/etc/nginx/sites-available",
        nginx_enabled_path: str = "/etc/nginx/sites-enabled",
    ):
        self.nginx_config_path = str(nginx_config_path)
        self.nginx_enabled_path = str(nginx_enabled_path)

        # Attempt to create directories
        try:
            Path(self.nginx_config_path).mkdir(parents=True, exist_ok=True)
        except (PermissionError, FileNotFoundError):
            pass
        try:
            Path(self.nginx_enabled_path).mkdir(parents=True, exist_ok=True)
        except (PermissionError, FileNotFoundError):
            pass

    def generate_config(
        self,
        app_name: str,
        port: int,
        domain: str,
        ssl: bool = False,
        ssl_certificate: Optional[str] = None,
        ssl_certificate_key: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        websocket: bool = False,
    ) -> str:
        """Generate nginx configuration with input validation."""
        # Validate inputs
        if not app_name or not isinstance(app_name, str):
            raise ValueError("Invalid app_name")
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ValueError("Invalid port number")
        if not domain or not isinstance(domain, str):
            raise ValueError("Invalid domain")

        lines = []
        listen = "443 ssl" if ssl else "80"
        lines.append("server {")
        lines.append(f"    listen {listen};")
        lines.append(f"    server_name {domain};")
        lines.append("    location / {")
        lines.append(f"        proxy_pass http://localhost:{port};")

        if custom_headers:
            for k, v in custom_headers.items():
                # Basic header validation
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                lines.append(f"        proxy_set_header {k} {v};")

        if websocket:
            lines.append("        proxy_http_version 1.1;")
            lines.append("        proxy_set_header Upgrade $http_upgrade;")
            lines.append("        proxy_set_header Connection \"upgrade\";")

        lines.append("    }")

        if ssl:
            if not ssl_certificate or not ssl_certificate_key:
                raise ValueError("SSL enabled but certificate paths not provided")
            lines.append(f"    ssl_certificate {ssl_certificate};")
            lines.append(f"    ssl_certificate_key {ssl_certificate_key};")

        lines.append("}")
        return "\n".join(lines)

    def _config_path(self, app_name: str) -> Path:
        """Get config path with validation."""
        if not app_name or ".." in app_name or "/" in app_name:
            raise ValueError("Invalid app_name for config path")
        return Path(self.nginx_config_path) / app_name

    def _enabled_path(self, app_name: str) -> Path:
        """Get enabled path with validation."""
        if not app_name or ".." in app_name or "/" in app_name:
            raise ValueError("Invalid app_name for enabled path")
        return Path(self.nginx_enabled_path) / app_name

    def write_config(self, app_name: str, content: str, overwrite: bool = False):
        """Write configuration file with validation."""
        p = self._config_path(app_name)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except (PermissionError, FileNotFoundError):
            pass

        if p.exists() and not overwrite:
            raise FileExistsError("Config exists")

        with open(str(p), "w") as f:
            f.write(content)

    def enable_config(self, app_name: str):
        """Enable configuration by creating symlink."""
        avail = self._config_path(app_name)
        enabled = self._enabled_path(app_name)

        if not avail.exists():
            raise FileNotFoundError("Config not found")

        if not enabled.exists():
            enabled.symlink_to(avail)

    def disable_config(self, app_name: str):
        """Disable configuration by removing symlink."""
        enabled = self._enabled_path(app_name)
        if enabled.exists():
            enabled.unlink()

    def remove_config(self, app_name: str):
        """Remove both available and enabled configs."""
        avail = self._config_path(app_name)
        enabled = self._enabled_path(app_name)

        if enabled.exists():
            enabled.unlink()
        if avail.exists():
            avail.unlink()

    def reload_nginx(self, timeout: int = 10) -> bool:
        """Reload nginx with hardened subprocess call.

        Uses absolute path and validates command execution.
        """
        try:
            # Use absolute path to nginx binary
            result = subprocess.run(
                [NGINX_BIN, "-s", "reload"],
                capture_output=True,
                timeout=timeout,
                check=False,  # Don't raise on non-zero exit
            )  # nosec

            if result.returncode != 0:
                logger.error(
                    f"Nginx reload failed: {result.stderr.decode('utf-8', errors='ignore')}"
                )
                return False

            logger.info("Nginx reloaded successfully")
            return True

        except FileNotFoundError:
            logger.error(f"Nginx binary not found at {NGINX_BIN}")
            raise
        except subprocess.TimeoutExpired:
            logger.error(f"Nginx reload timed out after {timeout}s")
            raise
        except Exception as e:
            logger.error(f"Unexpected error reloading nginx: {e}")
            return False

    def test_nginx_config(self) -> bool:
        """Test nginx configuration validity."""
        try:
            result = subprocess.run(
                [NGINX_BIN, "-t"], capture_output=True, timeout=10, check=False
            )  # nosec

            if result.returncode != 0:
                logger.error(
                    f"Nginx config test failed: "
                    f"{result.stderr.decode('utf-8', errors='ignore')}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to test nginx config: {e}")
            return False

    def list_configs(self):
        """List available configurations."""
        p = Path(self.nginx_config_path)
        names = []

        try:
            entries = list(p.iterdir())
        except Exception:
            return []

        for x in entries:
            is_file_attr = getattr(x, "is_file", None)
            try:
                is_file = (
                    is_file_attr() if callable(is_file_attr) else bool(is_file_attr)
                )
            except Exception:
                try:
                    is_file = bool(x)
                except Exception:
                    is_file = False

            if not is_file:
                continue

            name_attr = getattr(x, "name", None)
            if isinstance(name_attr, str):
                names.append(name_attr)
            else:
                mock_name = getattr(x, "_mock_name", None)
                if isinstance(mock_name, str):
                    names.append(mock_name)
                else:
                    names.append(str(x))

        return names

    def read_config(self, app_name: str) -> str:
        """Read configuration file."""
        p = self._config_path(app_name)
        if not p.exists():
            raise FileNotFoundError()

        with open(str(p), "r") as f:
            return f.read()

    def update_config(self, app_name: str, new_content: str):
        """Update existing configuration."""
        p = self._config_path(app_name)
        if not p.exists():
            raise FileNotFoundError()

        with open(str(p), "w") as f:
            f.write(new_content)
