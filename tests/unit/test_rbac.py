import pytest

from core.rbac import RBAC


def test_rbac_require_allows():
    r = RBAC({"admin": ["deploy"]})

    @r.require("admin", "deploy")
    def fn():
        return "ok"

    assert fn() == "ok"


def test_rbac_require_denies():
    r = RBAC({"user": ["read"]})

    @r.require("user", "deploy")
    def fn():
        return "should-not-run"

    with pytest.raises(PermissionError):
        fn()
