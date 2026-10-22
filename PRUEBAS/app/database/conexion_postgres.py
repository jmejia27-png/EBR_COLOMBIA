import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Carga de variables de entorno desde el archivo .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("ERROR: La variable DATABASE_URL no está configurada en el archivo .env")

# Creación del motor de la base de datos (Engine)
# echo=True permite ver las consultas SQL en la consola para depuración durante el desarrollo
engine = create_engine(
    DATABASE_URL,
    echo=True,
    pool_pre_ping=True
)

# Fábrica de sesiones
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Inyección de dependencia para obtener la sesión de base de datos en los controladores o servicios
def obtener_sesion_bd():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()