"""Production must refuse development secrets."""

from app.config import Settings


def test_dev_defaults_are_reported() -> None:
    insecure = set(Settings(_env_file=None).insecure_defaults())  # type: ignore[call-arg]
    expected = {"JWT_SECRET", "SEED_ADMIN_PASSWORD", "SEED_ANALYST_PASSWORD", "SEED_AGENT_PASSWORD"}
    assert expected <= insecure


def test_strong_settings_pass() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        jwt_secret="x" * 48,
        seed_admin_password="a-long-unique-admin-pass",
        seed_analyst_password="a-long-unique-analyst-pass",
        seed_agent_password="a-long-unique-agent-pass",
    )
    assert settings.insecure_defaults() == []


def test_short_jwt_secret_flagged() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        jwt_secret="short-but-custom",
        seed_admin_password="p1",
        seed_analyst_password="p2",
        seed_agent_password="p3",
    )
    assert settings.insecure_defaults() == ["JWT_SECRET (shorter than 32 characters)"]
