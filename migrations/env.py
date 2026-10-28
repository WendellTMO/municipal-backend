"""Alembic environment configuration.

This module configures Alembic to work with Flask-SQLAlchemy and
automatically detect model changes for migration generation.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Add the project root to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

# Import models to ensure they're registered with SQLAlchemy metadata
from app.models.base import db
from app.models import user, geo, rota, viagem, onibus, prefeitura, notificacao, password_reset, convite, convite

# Alembic Config object
config = context.config

# Setup logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = db.metadata


# ==========================================
# Exclusion filters for autogenerate
# ==========================================

# Tables managed by PostGIS (not our app)
EXCLUDED_TABLES = {"spatial_ref_sys", "topology", "layer"}

# Columns managed by PostgreSQL (computed/generated)
EXCLUDED_COLUMNS = {
    "ponto": ["geom"],  # Generated column: ST_SetSRID(ST_MakePoint(...))
}

# Indexes managed by PostGIS or that we want to ignore
EXCLUDED_INDEXES = {"idx_ponto_geom"}


def include_object(object, name, type_, reflected, compare_to):
    """Filter out PostGIS system objects from autogenerate."""
    if type_ == "table":
        if name in EXCLUDED_TABLES:
            return False

    if type_ == "column":
        table_name = object.table.name if hasattr(object, "table") else None
        if table_name in EXCLUDED_COLUMNS:
            if name in EXCLUDED_COLUMNS[table_name]:
                return False

    if type_ == "index":
        if name in EXCLUDED_INDEXES:
            return False

    return True


def get_url():
    """Build database URL from environment variables."""
    return (
        f"postgresql+psycopg2://"
        f"{os.getenv('DB_USER', 'buska_user')}:"
        f"{os.getenv('DB_PASSWORD', 'buska_pass')}@"
        f"{os.getenv('DB_HOST', 'localhost')}:"
        f"{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME', 'buska_db')}"
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=False,  # Don't compare column types (avoids ENUM noise)
        compare_server_default=False,  # Don't compare server defaults
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a
    connection with the context.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=False,  # Don't compare column types (avoids ENUM noise)
            compare_server_default=False,  # Don't compare server defaults
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
