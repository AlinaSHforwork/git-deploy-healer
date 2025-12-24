import socket
from contextlib import closing


class PortManager:
    def __init__(self, start_port: int = 8000, end_port: int = 9000):
        self.start_port = start_port
        self.end_port = end_port

    def find_free_port(self) -> int:
        for port in range(self.start_port, self.end_port):
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                try:
                    sock.bind(('', port))
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    return port
                except OSError:
                    continue
        raise RuntimeError(f"No free ports available in range {self.start_port}-{self.end_port}")

    def is_port_open(self, host: str, port: int) -> bool:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(1)
            return sock.connect_ex((host, port)) == 0
