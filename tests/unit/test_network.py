"""Tests for core.network module."""
import socket
from unittest.mock import patch

import pytest

from core.network import PortManager, parse_docker_port_mapping, validate_port


class TestValidatePort:
    """Test port validation function."""

    def test_validate_port_valid_integer(self):
        """Test validation of valid integer port."""
        assert validate_port(8080) == 8080
        assert validate_port(80) == 80
        assert validate_port(65535) == 65535
        assert validate_port(1) == 1

    def test_validate_port_valid_string(self):
        """Test validation of valid string port."""
        assert validate_port("8080") == 8080
        assert validate_port("80") == 80

    def test_validate_port_invalid_range(self):
        """Test validation of out-of-range ports."""
        assert validate_port(0) is None
        assert validate_port(-1) is None
        assert validate_port(65536) is None
        assert validate_port(100000) is None

    def test_validate_port_invalid_type(self):
        """Test validation of invalid types."""
        assert validate_port(None) is None
        assert validate_port("not-a-port") is None
        assert validate_port([8080]) is None
        assert validate_port({'port': 8080}) is None

    def test_validate_port_float(self):
        """Test validation of float values."""
        assert validate_port(8080.0) == 8080
        assert validate_port(8080.5) is None  # Non-integer float


class TestParseDockerPortMapping:
    """Test Docker port mapping parser."""

    def test_parse_integer(self):
        """Test parsing integer port."""
        assert parse_docker_port_mapping(8080) == 8080

    def test_parse_string(self):
        """Test parsing string port."""
        assert parse_docker_port_mapping("8080") == 8080

    def test_parse_docker_dict_single_port(self):
        """Test parsing Docker dict with single port."""
        ports = {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}]}
        assert parse_docker_port_mapping(ports) == 8080

    def test_parse_docker_dict_multiple_ports(self):
        """Test parsing Docker dict with multiple ports."""
        ports = {
            '80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}],
            '443/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8443'}],
        }
        result = parse_docker_port_mapping(ports)
        assert result in [8080, 8443]

    def test_parse_docker_dict_no_mapping(self):
        """Test parsing when port not mapped."""
        ports = {'80/tcp': None}
        assert parse_docker_port_mapping(ports) is None

    def test_parse_docker_dict_empty_list(self):
        """Test parsing with empty list."""
        ports = {'80/tcp': []}
        assert parse_docker_port_mapping(ports) is None

    def test_parse_list_format(self):
        """Test parsing list format."""
        ports = [{'HostIp': '0.0.0.0', 'HostPort': '9090'}]
        assert parse_docker_port_mapping(ports) == 9090

    def test_parse_none(self):
        """Test parsing None."""
        assert parse_docker_port_mapping(None) is None

    def test_parse_empty_dict(self):
        """Test parsing empty dict."""
        assert parse_docker_port_mapping({}) is None

    def test_parse_malformed_dict(self):
        """Test parsing malformed dict."""
        ports = {'80/tcp': [{'NoHostPort': 'wrong'}]}
        assert parse_docker_port_mapping(ports) is None

    def test_parse_invalid_port_in_dict(self):
        """Test parsing dict with invalid port number."""
        ports = {'80/tcp': [{'HostPort': 'not-a-number'}]}
        assert parse_docker_port_mapping(ports) is None

    def test_parse_out_of_range_port(self):
        """Test parsing out-of-range port."""
        ports = {'80/tcp': [{'HostPort': '99999'}]}
        assert parse_docker_port_mapping(ports) is None


class TestPortManager:
    """Test PortManager class."""

    def test_find_free_port(self):
        """Test finding a free port."""
        pm = PortManager(start_port=8000, end_port=9000)
        with patch.object(pm, 'is_port_open', return_value=False):
            port = pm.find_free_port()
            assert 8000 <= port < 9000

    def test_find_free_port_no_ports_available(self):
        """Test behavior when no ports available."""
        pm = PortManager(start_port=8000, end_port=8005)
        with patch.object(pm, 'is_port_open', return_value=True):
            with pytest.raises(RuntimeError, match="No free ports available"):
                pm.find_free_port()

    def test_is_port_open_closed_port(self):
        """Test checking if port is closed."""
        pm = PortManager()

        assert not pm.is_port_open("localhost", 99999)

    def test_is_port_open_invalid_host(self):
        """Test checking invalid host."""
        pm = PortManager()

        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.connect_ex.side_effect = (
                socket.gaierror
            )
            assert not pm.is_port_open("invalid-host-xyz", 8080)
