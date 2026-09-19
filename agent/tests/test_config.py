import psycopg

from config import DEFAULT_MODEL, Settings


def test_defaults_when_env_is_empty():
    settings = Settings.from_env({})
    assert settings.model == DEFAULT_MODEL
    assert settings.google_api_key is None
    assert settings.database_url is None
    assert settings.environment == "dev"


def test_reads_every_variable():
    settings = Settings.from_env(
        {
            "AGENT_MODEL": "test",
            "GOOGLE_AI_STUDIO_KEY": "k",
            "DATABASE_URL": "postgresql://a:b@h:1/d",
            "AGENT_ENV": "prod",
        }
    )
    assert settings.model == "test"
    assert settings.google_api_key == "k"
    assert settings.database_url == "postgresql://a:b@h:1/d"
    assert settings.environment == "prod"


def test_secrets_stay_out_of_repr_and_str():
    settings = Settings.from_env(
        {
            "GOOGLE_AI_STUDIO_KEY": "sekrit-key",
            "DATABASE_URL": "postgresql://agent:sekrit-password@h:1/d",
        }
    )
    for rendered in (repr(settings), str(settings)):
        assert "sekrit-key" not in rendered
        assert "sekrit-password" not in rendered
        assert settings.database_url not in rendered
        # The harmless fields still render, so this is not an empty repr.
        assert DEFAULT_MODEL in rendered


def test_blank_values_count_as_missing():
    settings = Settings.from_env({"GOOGLE_AI_STUDIO_KEY": "", "DATABASE_URL": ""})
    assert settings.google_api_key is None
    assert settings.database_url is None


def test_seed_is_loaded(database_url):
    with psycopg.connect(database_url) as conn:
        (count,) = conn.execute("SELECT count(*) FROM payments").fetchone()
    assert count == 18
