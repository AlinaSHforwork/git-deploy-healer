# api/healer.py
"""
Shim exposing the test-oriented Healer and a trigger helper used by tests.
"""
from typing import Any, Optional

_core_healer = None  # Prevent import loop in case core.healer imports api.healer


class _DefaultHealer:
    def check_and_heal(self, target: Any = None) -> bool:
        # simple no-op healer used during tests (can be monkeypatched)
        return True


# module-level symbol expected by tests; tests may monkeypatch this to None
Healer: Optional[Any] = _DefaultHealer()


def trigger_heal(target: Optional[Any] = None):
    """
    Trigger healing. Tests expect:
    - RuntimeError when module-level Healer is None
    - AttributeError when passed an object that lacks check_and_heal
    """
    if Healer is None:
        raise RuntimeError("Healer not available")

    if target is not None:
        if not hasattr(target, "check_and_heal"):
            raise AttributeError("target lacks check_and_heal")
        return target.check_and_heal()

    if not hasattr(Healer, "check_and_heal"):
        raise RuntimeError("Healer invalid")
    return Healer.check_and_heal(target)
