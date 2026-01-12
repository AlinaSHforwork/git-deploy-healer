import socket
from contextlib import closing
from typing import Any, Optional


class PortManager:
    def __init__(self, start_port: int = 8000, end_port: int = 9000):
        self.start_port = start_port
        self.end_port = end_port

    def find_free_port(self) -> int:
        for port in range(self.start_port, self.end_port):
            if not self.is_port_open("localhost", port):
                return port

        raise RuntimeError(
            f"No free ports available in range {self.start_port}-{self.end_port}"
        )

    def is_port_open(self, host: str, port: int) -> bool:
        if not (0 <= port <= 65535):
            return False
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(1)
            return sock.connect_ex((host, port)) == 0


def validate_port(port):
    if isinstance(port, float) and not port.is_integer():
        return None
    try:
        port_int = int(port)
        if 1 <= port_int <= 65535:
            return port_int
    except (ValueError, TypeError):
        pass
    return None


def parse_docker_port_mapping(ports: Any) -> Optional[int]:
    """Parse Docker container port mapping to extract host port.

    Handles various Docker SDK port mapping formats.

    Args:
        ports: Docker ports object (dict, list, str, or int)

    Returns:
        Host port number or None

    Examples:
        >>> parse_docker_port_mapping({'80/tcp': [{'HostPort': '8080'}]})
        8080
        >>> parse_docker_port_mapping('8080')
        8080
        >>> parse_docker_port_mapping(8080)
        8080
    """
    # Direct integer or string
    validated = validate_port(ports)
    if validated:
        return validated

    # Docker dict format
    if isinstance(ports, dict):
        for port_key, port_info in ports.items():
            if port_info and isinstance(port_info, list) and len(port_info) > 0:
                first = port_info[0]
                if isinstance(first, dict) and 'HostPort' in first:
                    return validate_port(first['HostPort'])

    # List format (edge case)
    if isinstance(ports, list) and len(ports) > 0:
        first = ports[0]
        if isinstance(first, dict) and 'HostPort' in first:
            return validate_port(first['HostPort'])

    return None
