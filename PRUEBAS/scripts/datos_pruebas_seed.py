import sys
import os

# Agregar la raíz del proyecto al sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from argon2 import PasswordHasher
from app.database.conexion_postgres import SessionLocal
from app.models.modelo_usuario import Usuario

ph = PasswordHasher()

def sembrar_datos_demo():
    db = SessionLocal()
    try:
        # Verificar si el usuario demo ya existe
        usuario_existente = db.query(Usuario).filter(Usuario.username == "operador_demo").first()
        if usuario_existente:
            print("[INFO] El usuario 'operador_demo' ya existe en PostgreSQL.")
            return

        # Crear hash seguro Argon2 para la contraseña de pruebas
        pass_hash = ph.hash("Demo2026*")

        nuevo_usuario = Usuario(
            username="operador_demo",
            email="operador.demo@yobel.com.co",
            nombre_completo="Operador de Maquila Demo",
            password_hash=pass_hash,
            activo=True
        )

        db.add(nuevo_usuario)
        db.commit()
        print("[ÉXITO] Usuario 'operador_demo' (Clave: Demo2026*) creado correctamente en PostgreSQL.")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] No se pudo crear el usuario demo: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    sembrar_datos_demo()