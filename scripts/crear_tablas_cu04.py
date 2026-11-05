# scripts/crear_tablas_cu04.py
# Crea en la base configurada en .env SOLO las tablas nuevas de CU-04 (desarrollo de la orden):
#   documentos_formato, registros_linea_formato, firmas_electronicas
# No borra ni modifica ninguna tabla existente. Si las tablas ya existen, no hace nada.
# Requiere que existan las tablas de CU-03 (ejecutar antes scripts\crear_tablas_cu03.py).
#
# Uso (desde C:\EBR_COLOMBIA):
#     .\.venv\Scripts\python.exe scripts\crear_tablas_cu04.py
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import inspect

from app.database.conexion_postgres import engine
import app.models  # noqa: F401  registra todos los modelos
from app.models.modelo_formato_ebr import DocumentoFormato, FirmaElectronica, RegistroLineaFormato

TABLAS = [DocumentoFormato.__table__, RegistroLineaFormato.__table__, FirmaElectronica.__table__]

engine.echo = False
inspector = inspect(engine)
print(f"Base de datos: {engine.url.database}")
for requerida in ("usuarios", "tokens_otp", "ordenes_trabajo", "lineas_material_orden"):
    if not inspector.has_table(requerida):
        sys.exit(f"[DETENIDO] Falta la tabla '{requerida}'. Ejecute primero scripts\\crear_tablas_cu03.py o revise DATABASE_URL en .env.")

existentes = [t.name for t in TABLAS if inspector.has_table(t.name)]
if existentes:
    print("[INFO] Ya existen: " + ", ".join(existentes))
if inspector.has_table("registros_linea_formato"):
    columnas = {c["name"] for c in inspector.get_columns("registros_linea_formato")}
    if "lotes_materiales" not in columnas:
        sys.exit("[DETENIDO] La tabla registros_linea_formato tiene una estructura anterior. No se modificó nada.")

for tabla in TABLAS:
    tabla.create(bind=engine, checkfirst=True)

print("[OK] Tablas de CU-04 verificadas: " + ", ".join(t.name for t in TABLAS))
