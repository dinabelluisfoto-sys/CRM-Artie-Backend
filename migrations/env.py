from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
import os

# 1. Añadimos la carpeta 'backend' al path para encontrar los archivos
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# 2. Importamos la URL real desde tu database.py y los modelos
from database import DATABASE_URL
from models import Base

target_metadata = Base.metadata
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 3. EL FIX: Obligamos a Alembic a usar tu URL real de Railway
# (Y corregimos el formato de Railway si es necesario)
if DATABASE_URL:
    fixed_url = DATABASE_URL.replace("postgres://", "postgresql://")
    config.set_main_option("sqlalchemy.url", fixed_url)

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()