# scripts/preparar_bd_pruebas.py
# Prepara la base de datos de PRUEBAS: la crea si no existe, crea todas las tablas
# (incluidas las de CU-03) y registra dos usuarios de prueba: uno ADMIN y uno USER.
#
# Uso (desde la carpeta PRUEBAS, con el entorno virtual activado):
#     python scripts\preparar_bd_pruebas.py
#
# Opciones:
#     --reiniciar-ordenes   Borra y vuelve a crear SOLO las tablas de órdenes de trabajo (CU-03).
#                           Necesario cuando cambia la estructura de esas tablas. Borra las órdenes de prueba.
#     --restablecer-claves  Vuelve a pedir la contraseña de admin_pruebas y usuario_pruebas.
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

load_dotenv()

parser = argparse.ArgumentParser(description="Prepara la base de datos de PRUEBAS del EBR.")
parser.add_argument("--reiniciar-ordenes", action="store_true", help="Recrea las tablas de órdenes de trabajo (CU-03).")
parser.add_argument("--restablecer-claves", action="store_true", help="Vuelve a pedir las contraseñas de los usuarios de prueba.")
opciones = parser.parse_args()

url = make_url(os.getenv("DATABASE_URL", ""))
if not url.database or "prueba" not in url.database.lower():
    sys.exit(
        f"[DETENIDO] DATABASE_URL apunta a '{url.database}'. Este script solo trabaja sobre una base "
        "cuyo nombre contenga 'prueba' (por ejemplo ebr_pruebas_db), para no tocar la base principal."
    )

# 1. Crear la base de datos si no existe
servidor = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
with servidor.connect() as conexion:
    existe = conexion.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}).scalar()
    if existe:
        print(f"[INFO] La base de datos {url.database} ya existe.")
    else:
        conexion.execute(text(f'CREATE DATABASE "{url.database}"'))
        print(f"[OK] Base de datos {url.database} creada.")
servidor.dispose()

# 2. Crear las tablas que falten (no borra ni modifica tablas existentes)
from app.database.base_declarativa import Base
from app.database.conexion_postgres import SessionLocal, engine
import app.models  # noqa: F401  carga todos los modelos, incluido CU-03
from app.models.modelo_usuario import Usuario, RolUsuario
from app.core.seguridad_cifrado import obtener_password_hash

from sqlalchemy import inspect

TABLAS_CU03 = ["lineas_material_orden", "versiones_orden_trabajo", "ordenes_trabajo", "archivos_carga_orden"]
inspector = inspect(engine)
if opciones.reiniciar_ordenes:
    with engine.begin() as conexion:
        for tabla in TABLAS_CU03:
            conexion.execute(text(f'DROP TABLE IF EXISTS "{tabla}" CASCADE'))
        conexion.execute(text("DROP TYPE IF EXISTS estado_orden_enum"))  # tipo de la versión anterior de CU-03
    print("[OK] Tablas de órdenes de trabajo (CU-03) eliminadas para recrearlas.")
elif inspector.has_table("ordenes_trabajo"):
    columnas = {c["name"] for c in inspector.get_columns("ordenes_trabajo")}
    if "version" not in columnas:
        sys.exit(
            "[DETENIDO] Las tablas de órdenes de trabajo tienen la estructura anterior de CU-03.\n"
            "Ejecute:  python scripts\\preparar_bd_pruebas.py --reiniciar-ordenes\n"
            "(borra solo las órdenes de prueba; los usuarios y el Audit Trail se conservan)."
        )

Base.metadata.create_all(engine)
print("[OK] Tablas verificadas: " + ", ".join(sorted(Base.metadata.tables)))

# 3. Usuarios de prueba
USUARIOS = [
    ("admin_pruebas", "admin.pruebas@yobel.com.co", "Administrador de Pruebas", RolUsuario.ADMIN),
    ("usuario_pruebas", "usuario.pruebas@yobel.com.co", "Usuario de Pruebas", RolUsuario.USER),
]

db = SessionLocal()
try:
    for username, email, nombre, rol in USUARIOS:
        existente = db.query(Usuario).filter(Usuario.username == username).first()
        if existente and not opciones.restablecer_claves:
            print(f"[INFO] El usuario {username} ya existe. Use --restablecer-claves si olvidó la contraseña.")
            continue
        while True:
            clave = getpass.getpass(f"Contraseña para {username} ({rol.value.upper()}): ")
            if len(clave) >= 4 and clave == getpass.getpass("Repita la contraseña: "):
                break
            print("Las contraseñas no coinciden o tienen menos de 4 caracteres. Intente de nuevo.")
        if existente:
            from datetime import datetime, timezone
            existente.password_hash = obtener_password_hash(clave)
            existente.requiere_cambio_password = False
            existente.activo = True
            existente.password_actualizada_en = datetime.now(timezone.utc)
            db.commit()
            print(f"[OK] Contraseña de {username} restablecida.")
            continue
        db.add(Usuario(
            username=username, email=email, nombre_completo=nombre, rol=rol,
            password_hash=obtener_password_hash(clave), activo=True, requiere_cambio_password=False,
        ))
        db.commit()
        print(f"[OK] Usuario {username} creado con rol {rol.value.upper()}.")
finally:
    db.close()

print("\nListo. Inicie el servidor con:  uvicorn app.main:app --reload")
