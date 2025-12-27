import pytest

from api import healer


def test_trigger_default_healer():
    assert healer.trigger_heal() is True


def test_trigger_with_valid_target():
    class Dummy:
        def check_and_heal(self):
            return "ok"

    assert healer.trigger_heal(Dummy()) == "ok"


def test_trigger_with_invalid_target():
    class Broken:
        pass

    with pytest.raises(AttributeError):
        healer.trigger_heal(Broken())


def test_trigger_with_none_healer(monkeypatch):
    monkeypatch.setattr(healer, "Healer", None)
    with pytest.raises(RuntimeError):
        healer.trigger_heal()


def test_trigger_with_invalid_healer(monkeypatch):
    class NoHeal:
        pass

    monkeypatch.setattr(healer, "Healer", NoHeal())
    with pytest.raises(RuntimeError):
        healer.trigger_heal()
