# scripts/crear_tablas_cu03.py
# Crea en la base configurada en .env SOLO las tablas nuevas de CU-03 (órdenes de trabajo):
#   archivos_carga_orden, ordenes_trabajo, lineas_material_orden, versiones_orden_trabajo
# No borra ni modifica ninguna tabla existente (usuarios, tokens_otp, audit_trail...).
# Si las tablas ya existen, no hace nada.
#
# Uso (desde C:\EBR_COLOMBIA):
#     .\.venv\Scripts\python.exe scripts\crear_tablas_cu03.py
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import inspect

from app.database.conexion_postgres import engine
import app.models  # noqa: F401  registra todos los modelos
from app.models.modelo_orden_trabajo import (
    ArchivoCargaOrden, LineaMaterialOrden, OrdenTrabajo, VersionOrdenTrabajo,
)

TABLAS = [ArchivoCargaOrden.__table__, OrdenTrabajo.__table__, LineaMaterialOrden.__table__, VersionOrdenTrabajo.__table__]

engine.echo = False
inspector = inspect(engine)
print(f"Base de datos: {engine.url.database}")
if not inspector.has_table("usuarios"):
    sys.exit("[DETENIDO] La base no tiene la tabla 'usuarios'. Revise DATABASE_URL en el archivo .env.")

existentes = [t.name for t in TABLAS if inspector.has_table(t.name)]
if existentes:
    print("[INFO] Ya existen: " + ", ".join(existentes))

if inspector.has_table("ordenes_trabajo"):
    columnas = {c["name"] for c in inspector.get_columns("ordenes_trabajo")}
    if "version" not in columnas:
        sys.exit("[DETENIDO] La tabla ordenes_trabajo tiene una estructura anterior. No se modificó nada.")

for tabla in TABLAS:
    tabla.create(bind=engine, checkfirst=True)

print("[OK] Tablas de CU-03 verificadas: " + ", ".join(t.name for t in TABLAS))
