"""Production runs `alembic upgrade head`; the resulting schema must match the models."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models.entities  # noqa: F401  (registers the tables)
from app.config import get_settings
from app.database import Base

BACKEND = Path(__file__).resolve().parents[1]


def test_migrations_build_the_model_schema(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    columns = [d for d in diff if isinstance(d, tuple) and d[0] in {"add_column", "remove_column", "add_table", "remove_table"}]
    assert columns == [], f"Models and migrations differ; add a migration: {columns}"
