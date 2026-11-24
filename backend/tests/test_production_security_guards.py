import pytest
from app.core.config import Settings, validate_runtime


def production(**overrides):
    values = dict(environment="production", demo_mode=False,
                  jwt_secret="a" * 48, database_url="postgresql://localhost/pmab",
                  storage_backend="s3", s3_bucket="pmab-test")
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("overrides", [
    {"jwt_secret": "short"},
    {"database_url": "mysql://localhost/pmab"},
    {"storage_backend": "unknown"},
    {"s3_bucket": ""},
    {"cors_origins": "*"},
])
def test_unsafe_production_settings_rejected(overrides):
    with pytest.raises(RuntimeError):
        validate_runtime(production(**overrides))


def test_valid_production_settings():
    validate_runtime(production())
