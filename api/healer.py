# api/healer.py
"""
Shim exposing the test-oriented Healer and a trigger helper used by tests.
"""
from importlib import import_module as _import

_core_healer = _import("core.healer")

Healer = getattr(_core_healer, "Healer", None)
ContainerHealer = getattr(_core_healer, "ContainerHealer", None)


def trigger_heal(healer_obj=None):
    """
    Tests monkeypatch this function. Return the coroutine from check_and_heal
    so tests can await or patch it. If Healer is available and healer_obj is None,
    create one.
    """
    if healer_obj is None:
        if Healer is None:
            raise RuntimeError("No Healer available")
        healer_obj = Healer()
    coro = getattr(healer_obj, "check_and_heal", None)
    if coro is None:
        raise AttributeError("Healer object has no check_and_heal")
    return coro()
