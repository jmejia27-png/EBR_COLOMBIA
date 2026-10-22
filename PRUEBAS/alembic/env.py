import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Agregar el directorio raíz al path de Python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Cargar variables de entorno
load_dotenv()

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

# Asignar la URL desde la variable de entorno DATABASE_URL
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Cargar los modelos para autogeneración de migraciones
from app.database.base_declarativa import Base
import app.models  # Carga modelo_usuario, modelo_token_otp, modelo_bitacora_auditoria

target_metadata = Base.metadata

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
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()