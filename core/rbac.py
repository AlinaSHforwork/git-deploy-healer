"""Lightweight role-based access control helpers."""
from __future__ import annotations

from typing import Callable, Dict, Iterable


class RBAC:
    def __init__(self, roles: Dict[str, Iterable[str]] | None = None):
        # roles: mapping role -> list of permissions
        self.roles = {k: set(v) for k, v in (roles or {}).items()}

    def has_permission(self, role: str, permission: str) -> bool:
        return permission in self.roles.get(role, set())

    def require(self, role: str, permission: str) -> Callable:
        def wrapper(fn: Callable) -> Callable:
            def inner(*args, **kwargs):
                if not self.has_permission(role, permission):
                    raise PermissionError("Access denied")
                return fn(*args, **kwargs)

            return inner

        return wrapper
