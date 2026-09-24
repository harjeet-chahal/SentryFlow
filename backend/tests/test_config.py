"""Configuration resolution, including the production secret guard."""
import importlib

import pytest

from backend import config


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("anything-else", False),
])
def test_env_bool_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("SOME_FLAG", raw)
    assert config._env_bool("SOME_FLAG") is expected


def test_env_bool_uses_the_default_when_unset(monkeypatch):
    monkeypatch.delenv("MISSING_FLAG", raising=False)
    assert config._env_bool("MISSING_FLAG", True) is True
    assert config._env_bool("MISSING_FLAG", False) is False


def test_explicit_jwt_secret_is_used(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "an-explicit-secret")
    assert config._resolve_jwt_secret() == "an-explicit-secret"


def test_production_refuses_to_boot_without_a_jwt_secret(monkeypatch):
    """The original code shipped a hardcoded key; this makes that impossible."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="JWT_SECRET must be set"):
        config._resolve_jwt_secret()


def test_development_mints_an_ephemeral_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(config.settings, "ENVIRONMENT", "development")

    first = config._resolve_jwt_secret()
    second = config._resolve_jwt_secret()

    assert first and second
    assert first != second, "ephemeral keys should not be reused"


@pytest.mark.parametrize("env,expected", [
    ("production", True), ("prod", True), ("PRODUCTION", True),
    ("development", False), ("test", False), ("staging", False),
])
def test_is_production_detection(monkeypatch, env, expected):
    monkeypatch.setattr(config.settings, "ENVIRONMENT", env)
    assert config.settings.is_production is expected


def test_cors_origins_are_split_on_commas(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.settings.CORS_ORIGINS == ["https://a.example", "https://b.example"]
    finally:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        importlib.reload(config)
