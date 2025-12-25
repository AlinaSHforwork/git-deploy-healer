# api/__init__.py
import importlib
from typing import Any

from . import server

__all__ = ["server", "schemas", "git_manager", "proxy_manager", "healer"]


def __getattr__(name: str) -> Any:
    """
    Lazy import submodules on attribute access, e.g. `from api import healer`.
    Avoids circular imports during package initialization.
    """
    if name in ("healer", "git_manager", "proxy_manager", "schemas"):
        mod = importlib.import_module(f"api.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
